"""The Muse — the story's AI companion, behind one HTTP boundary (D16/D17/D19).

The upstream brain is any of three wire dialects (Ollama on the LAN, an
OpenAI-compatible gateway, or a Messages-shape gateway); `app/upstream.py` is the
only place that knows which. Everything here speaks one internal shape.

Public surface:
    chat(messages, chapter_id, chip)        agentic: reads the story with tools and
                                            stages edits to chapters/bible (never saves)
    rewrite(text, style, chapter_id)        one-shot rewrite of a selection
    complete_text(before, chapter_id)       one-sentence ghost-text continuation
    sweep_report / sweep_bible              whole-book continuity pass
    list/read/delete/refresh_proposal       the staged-change store (.katha/proposals)

Streams yield visible prose (never <think> blocks) plus marker objects —
`Status`, `Proposal`, `Usage` — that the HTTP layer turns into SSE events.

The upstream client lives at module scope so tests can swap its transport via
`monkeypatch.setattr(muse_mod, "_client", mock_client)`.

Context the Muse gets: the story's file index, a cached style digest (D19), the
author's rules from `bible/rules.md` (D56), and any files @-mentioned (D57). The
rewrite path additionally gets the current chapter + FTS-ranked bible hits (D18).
Every exchange is appended to `archive/.katha/muse/<book>-<chapter>.md` (D19, D35).
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import httpx

from . import archive as ar_mod
from . import db
from . import upstream as up_mod
from .config import (
    ARCHIVE_ROOT,
    MUSE_AGENT_MAX_TOKENS,
    MUSE_AGENT_MODEL,
    MUSE_COMPLETE_MAX_TOKENS,
    MUSE_COMPLETE_MODEL,
    MUSE_MAX_TOOL_ROUNDS,
    MUSE_NUM_PREDICT,
    MUSE_REWRITE_MODEL,
    MUSE_STYLE_PROSE_CHAPTERS,
    MUSE_UPSTREAM_TIMEOUT,
    MUSECONTEXT_MAX_TOKENS,
)

# Module-level client — patchable from tests.
_client = httpx.AsyncClient(timeout=MUSE_UPSTREAM_TIMEOUT)

# Muse-side data lives inside the archive under `.katha/muse/`. Already
# git-ignored because archive/ is git-ignored.
_MUSE_ROOT = ARCHIVE_ROOT / ".katha" / "muse"
# Staged changes (proposals) live beside the threads in `.katha/proposals/` —
# inside the archive, so a backup covers them, and under a dot-directory, so no
# listing or search ever sees them. See the "staged changes" section below.


# --- token stripping ------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think>.*$", re.DOTALL)  # unterminated


def strip_think(text: str) -> str:
    """Remove <think>…</think> blocks from a chunk of model output.

    Ollama streams token-by-token, so a single chunk may begin inside a
    thinking block. We strip complete blocks greedily; an unterminated
    opening is also stripped so the user never sees reasoning start.
    """
    text = _THINK_RE.sub("", text)
    text = _THINK_OPEN_RE.sub("", text)
    return text


class ThinkStreamFilter:
    """Stateful <think> stripper for streamed NDJSON chunks.

    A tag can be split across chunks (`<thi` + `nk>`), which a per-chunk regex
    leaks. This buffers only the tail that could begin/end a tag, so the
    reader never sees chain-of-thought and never loses prose either.
    """

    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self):
        self._in_think = False
        self._buf = ""

    def feed(self, text: str) -> str:
        self._buf += text or ""
        out: list[str] = []
        while self._buf:
            if self._in_think:
                end = self._buf.find(self.CLOSE)
                if end == -1:
                    # Hold back a tail that may be a partial closing tag.
                    self._buf = self._buf[-len(self.CLOSE):]
                    return "".join(out)
                self._buf = self._buf[end + len(self.CLOSE):]
                self._in_think = False
                continue

            start = self._buf.find(self.OPEN)
            if start == -1:
                # Hold back a tail that may be a partial opening tag.
                keep = 0
                for k in range(1, len(self.OPEN)):
                    if self._buf.endswith(self.OPEN[:k]):
                        keep = k
                if keep:
                    out.append(self._buf[:-keep])
                    self._buf = self._buf[-keep:]
                else:
                    out.append(self._buf)
                    self._buf = ""
                return "".join(out)

            out.append(self._buf[:start])
            self._buf = self._buf[start + len(self.OPEN):]
            self._in_think = True
        return "".join(out)

    def finish(self) -> str:
        """Flush a held-back partial tag (it was prose, not a tag)."""
        if self._in_think:
            self._buf = ""
            return ""
        out, self._buf = self._buf, ""
        return out


# Words too common to anchor a canon lookup — they would match half the book.
_STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does for from had has have
he her here him his how i if in into is it its me my no not of on or our she
should so that the their them then there these they this those to was we were
what when where which who why will with would you your
""".split())
_WORD_RE = re.compile(r"[A-Za-z0-9']{3,}")


def _fts_or_query(text: str, max_terms: int = 24) -> str:
    """Turn prose into an FTS5 query that matches ANY distinctive term.

    FTS5 ANDs bare terms, so handing it a whole paragraph (the old canon
    behaviour) almost never matched a bible entry. Each token is quoted — no
    operator injection — and OR'd; bm25 still ranks the entries that share
    more terms first.
    """
    seen: list[str] = []
    for word in _WORD_RE.findall((text or "").lower()):
        if word in _STOPWORDS or word in seen:
            continue
        seen.append(word)
        if len(seen) >= max_terms:
            break
    return " OR ".join(f'"{w}"' for w in seen)


def _plain_snippet(text: str) -> str:
    """FTS snippets carry <mark> tags for the UI — prompts want plain text."""
    return (text or "").replace("<mark>", "").replace("</mark>", "")


# --- upstream call --------------------------------------------------------
# The dialect (Ollama-native vs OpenAI-compatible vs Messages) lives in
# app/upstream.py — this module only ever sees normalized
# `{"content"|"tool_calls"|"usage"|"notice"}` events (D20).

class Status:
    """Marker yielded from a Muse generator to emit an SSE `[STATUS]` event
    (progress, e.g. 'reading ch-03…') rather than prose."""
    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text


class Proposal:
    """Marker yielded from a Muse generator to emit an SSE `[PROPOSAL] <id>` event:
    the Muse has staged a change to a story file and is waiting for the author to
    review it (2.9, D45; any file since 3.1, D54)."""
    __slots__ = ("proposal_id",)

    def __init__(self, proposal_id: str):
        self.proposal_id = proposal_id


class Usage:
    """Marker yielded at the end of a Muse reply to emit an SSE `[USAGE]` event: how
    many tokens the reply cost, summed over every round (3.1, D59). Only emitted
    when the upstream actually reported a count."""
    __slots__ = ("input", "output")

    def __init__(self, input: int = 0, output: int = 0):
        self.input = int(input or 0)
        self.output = int(output or 0)

    def add(self, usage: dict | None) -> None:
        if usage:
            self.input += int(usage.get("input") or 0)
            self.output += int(usage.get("output") or 0)

    def __bool__(self) -> bool:
        return bool(self.input or self.output)


async def _stream_visible(payload: dict, meta: dict) -> AsyncIterator[str]:
    """Stream one upstream turn; yield visible text only (never <think> blocks).

    Side channels land in `meta`: `tool_calls` (list), `usage` (a Usage), and
    `notice` (True when the only text was the adapter's "the model wrote nothing"
    sentence — which must never be mistaken for a file's new contents).
    """
    meta.setdefault("tool_calls", [])
    meta.setdefault("usage", Usage())
    filt = ThinkStreamFilter()
    async for event in up_mod.stream_events({**payload, "stream": True}, _client):
        for tc in event.get("tool_calls") or []:
            meta["tool_calls"].append(tc)
        meta["usage"].add(event.get("usage"))
        if event.get("notice"):
            meta["notice"] = True
        visible = filt.feed(event.get("content") or "")
        if visible:
            yield visible
    tail = filt.finish()
    if tail:
        yield tail


async def _post_chat(payload: dict, meta: dict | None = None) -> AsyncIterator[str]:
    """Stream a turn from the active upstream; yield visible-only deltas."""
    async for visible in _stream_visible(payload, meta if meta is not None else {}):
        yield visible


# --- agentic chat: the model fetches story files via tools (1.1) ----------
# Instead of pre-injecting the chapter, the chat model gets tools to read the
# story on demand. Scope: the current book + the series root, .md only, never
# hidden dirs (.katha/) or anything outside the story archive.

class _ToolCtx:
    __slots__ = ("series_dir", "book_dir", "cid")

    def __init__(self, series_dir: Path, book_dir: Path, cid: str = ""):
        self.series_dir = series_dir
        self.book_dir = book_dir
        self.cid = cid            # the chapter this conversation is about (2.9)


def _tool_ctx(chapter_id: str | None) -> _ToolCtx | None:
    parsed = _parse_chapter_id(chapter_id) if chapter_id else None
    if not parsed:
        return None
    series_slug, book_slug, cid = parsed
    bdir = _resolve_bdir(series_slug, book_slug)
    if bdir is None:
        return None
    return _ToolCtx(bdir.parent, bdir, cid)


def _safe_story_path(ctx: _ToolCtx, rel: str) -> Path | None:
    """Resolve a tool path to a readable story .md, or None.

    Allowed: a .md inside the book dir, or a direct .md child of the series dir
    (addressed as 'series/<name>.md'). Never absolute, never '..', never a
    hidden segment (.katha/, dotfiles), never non-.md. This is the security
    boundary — the model chooses the path, so it must not escape the story.
    """
    if not rel or rel.startswith("/") or "\\" in rel:
        return None
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." or p.startswith(".") for p in parts):
        return None
    if not parts[-1].endswith(".md"):
        return None
    if parts[0] == "series":
        if len(parts) != 2:
            return None
        cand = ctx.series_dir / parts[1]
    else:
        cand = ctx.book_dir.joinpath(*parts)
    try:
        cand = cand.resolve()
    except OSError:
        return None
    try:
        cand.relative_to(ctx.book_dir.resolve())
        return cand if cand.is_file() else None
    except ValueError:
        pass
    if cand.parent == ctx.series_dir.resolve() and cand.is_file():
        return cand
    return None


def _story_files(ctx: _ToolCtx) -> list[str]:
    out: list[str] = []
    for f in ar_mod.chapter_files(ctx.book_dir / "chapters"):
        out.append(f"chapters/{f.name}")
    bd = ctx.book_dir / "bible"
    for f in ar_mod._iter_bible_files(bd):  # type: ignore[attr-defined]
        out.append(f"bible/{f.relative_to(bd).as_posix()}")
    for f in sorted(ctx.book_dir.glob("*.md")):
        out.append(f.name)
    for f in sorted(ctx.series_dir.glob("*.md")):
        out.append(f"series/{f.name}")
    return out


def _list_story_files(ctx: _ToolCtx) -> str:
    out = _story_files(ctx)
    return "\n".join(out) if out else "(no files)"


def _read_story_file(ctx: _ToolCtx, rel: str) -> str:
    p = _safe_story_path(ctx, rel)
    if p is None:
        return "ERROR: path not allowed — only story .md files in this book or the series root."
    # If the Muse already has a change waiting on this file, it must read *that*: its
    # next edit applies on top of the draft, so an `old_text` copied from the file on
    # disk would not match (3.1, D55).
    target = _edit_target(ctx, rel)
    if isinstance(target, tuple):
        draft = _live_draft(ctx, target[1])
        if draft is not None:
            return (f"[Your pending revision of {target[1]} — NOT yet accepted by the "
                    "author. Further edits apply on top of this text.]\n\n"
                    + (draft.get("content") or ""))
    try:
        return p.read_text(encoding="utf-8")
    except OSError as e:
        return f"ERROR: {e}"


def _search_story(ctx: _ToolCtx, query: str) -> str:
    q = (query or "").strip()
    if not q:
        return "ERROR: empty query"
    # Search only this book, and match ANY term (prose queries are long).
    fts = _fts_or_query(q) or q
    try:
        hits = db.search(fts, limit=12, book_id=ctx.book_dir.name)
    except Exception:
        return "(no results)"
    if not hits:
        return "(no results)"
    return "\n".join(
        f"{h.get('kind')} {h.get('doc_id')} — {h.get('title')}: {_plain_snippet(h.get('snippet', ''))}"
        for h in hits[:6]
    )


# --- the author's rules (3.1, D56) ----------------------------------------
# `bible/rules.md` is the book's standing orders — "British spelling", "no
# em-dashes", "Kael never swears". The style digest is the Muse's *guess* at the
# voice; the rules are the author's word, so every Muse call carries them.

RULES_FILE = "rules.md"
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def load_rules(bdir: Path | None) -> str:
    """The author's rules for this book, or "" when there are none worth sending.

    The scaffolded template is all comment, heading and an empty bullet — that is
    not a rule, and sending it would only cost tokens."""
    if bdir is None:
        return ""
    p = bdir / "bible" / RULES_FILE
    if not p.is_file():
        return ""
    try:
        text = _COMMENT_RE.sub("", p.read_text(encoding="utf-8"))
    except OSError:
        return ""
    real = [ln for ln in text.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
            and ln.strip() not in ("-", "*")]
    return "\n".join(real).strip() if real else ""


def _rules_block(bdir: Path | None) -> str:
    rules = load_rules(bdir)
    return ("## THE AUTHOR'S RULES FOR THIS BOOK (always follow these)\n\n" + rules
            if rules else "")


# --- @-mentions (3.1, D57) ------------------------------------------------
# `@ch-03` or `@kael` in a message attaches that file to the turn, so the Muse
# doesn't have to go looking for what the author already pointed at.

_MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9][\w./-]*)")
_CH_MENTION_RE = re.compile(r"^(?:ch|chapter)-?(\d{1,3})$")
_MENTION_CAP = 16000           # chars per attached file
_MENTION_TOTAL = 40000         # chars across every attachment in one message


def resolve_mentions(ctx: _ToolCtx, text: str) -> list[str]:
    """Story paths named by `@…` tokens in `text`, in order, without repeats."""
    files = _story_files(ctx)
    lower = {f.lower(): f for f in files}
    out: list[str] = []
    for raw in _MENTION_RE.findall(text or ""):
        t = raw.rstrip(".,;:!?)'\"").lower()
        if not t:
            continue
        hit = (lower.get(t) or lower.get(t + ".md")
               or lower.get(f"bible/{t}") or lower.get(f"bible/{t}.md"))
        if hit is None:
            m = _CH_MENTION_RE.match(t)
            if m:
                n = int(m.group(1))
                hit = lower.get(f"chapters/ch-{n:02d}.md") or lower.get(f"chapters/ch-{n}.md")
        if hit is None:
            stems = [f for f in files if Path(f).stem.lower() == t]
            if len(stems) == 1:
                hit = stems[0]
        if hit and hit not in out:
            out.append(hit)
    return out


def _mention_block(ctx: _ToolCtx, paths: list[str]) -> str:
    parts: list[str] = []
    used = 0
    for rel in paths:
        body = _read_story_file(ctx, rel)
        if body.startswith("ERROR"):
            continue
        body = body[:_MENTION_CAP]
        if used + len(body) > _MENTION_TOTAL:
            break
        used += len(body)
        parts.append(f"### {rel}\n\n{body.strip()}")
    if not parts:
        return ""
    return ("## FILES THE AUTHOR ATTACHED WITH @ (already read for you)\n\n"
            + "\n\n---\n\n".join(parts))


# --- staged changes: the Muse proposes, the author disposes (2.9 → 3.1) ----
# Every change the Muse makes is a *proposal*: a JSON file under
# `.katha/proposals/`, never the story file itself. A proposal targets one file —
# a chapter or a bible file (3.1, D54) — and there is at most ONE live draft per
# file: new edits stack onto it (D55), a full rewrite supersedes it. Accepting is a
# normal save, so the time machine keeps everything (D9, D45).
#
# Record shape:
#   id, series, book, kind ('chapter'|'bible'), path ('chapters/ch-03.md' |
#   'bible/characters/kael.md'), chapter (the chapter id for chapter kind),
#   origin (the chapter the conversation was in), batch (the turn that made it),
#   created_at, content, words,
#   base_revision (chapter kind: the revision the Muse read),
#   base_content  (bible kind: the text the Muse read — bible files keep no
#                  revisions),
#   edits         (the find/replace edits that built it, or None for a full
#                  rewrite — what lets a draft survive the author typing, D58),
#   dropped       (edits that no longer applied after the author's changes).

_PROPOSAL_ROOT = ARCHIVE_ROOT / ".katha" / "proposals"
PROPOSAL_MIN_CHARS = 200     # shorter than this is not a chapter, it's a fragment
PROPOSAL_KEEP = 1            # one live draft per file (3.1, D55)
_PID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}$")
_CHAPTER_PATH_RE = re.compile(r"^chapters/(ch-\d+)\.md$")
_BARE_CHAPTER_RE = re.compile(r"^(ch-\d+)(?:\.md)?$")

# What a read tool is doing, when its arguments don't say (2.9.3): the author saw
# 'reading list_story_files…' in the panel and it read like a bug rather than progress.
_TOOL_LABELS = {
    "list_story_files": "the story index",
    "search_story": "the story",
}


def proposal_target(p: dict) -> tuple[str, str]:
    """(kind, book-relative path) of a proposal — pre-3.1 records only had `chapter`."""
    kind = p.get("kind") or "chapter"
    path = p.get("path") or (f"chapters/{p.get('chapter', '')}.md" if kind == "chapter" else "")
    return kind, path


def _proposal_path(pid: str) -> Path | None:
    """Resolve a proposal id to its file, or None.

    The id arrives from a URL, so it is validated as a single slug segment and must
    resolve to a real file inside the proposals directory — no traversal, no dots.
    """
    if not _PID_RE.match(pid or ""):
        return None
    p = _PROPOSAL_ROOT / f"{pid}.json"
    return p if p.is_file() else None


def _write_proposal(meta: dict) -> None:
    _PROPOSAL_ROOT.mkdir(parents=True, exist_ok=True)
    (_PROPOSAL_ROOT / f"{meta['id']}.json").write_text(json.dumps(meta, indent=2),
                                                       encoding="utf-8")


def list_proposals() -> list[dict]:
    """Pending changes, newest first — metadata only, never the body."""
    if not _PROPOSAL_ROOT.is_dir():
        return []
    out: list[dict] = []
    files = sorted(_PROPOSAL_ROOT.glob("*.json"),
                   key=lambda q: q.stat().st_mtime, reverse=True)
    for p in files:
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        kind, path = proposal_target(meta)
        out.append({
            "id": meta.get("id", p.stem),
            "series": meta.get("series", ""),
            "book": meta.get("book", ""),
            "kind": kind,
            "path": path,
            "chapter": meta.get("chapter", ""),
            "origin": meta.get("origin", meta.get("chapter", "")),
            "batch": meta.get("batch", ""),
            "created_at": meta.get("created_at", ""),
            "words": meta.get("words", 0),
            "base_revision": meta.get("base_revision", 0),
            "edit_based": meta.get("edits") is not None,
        })
    return out


def read_proposal(pid: str) -> dict | None:
    p = _proposal_path(pid)
    if p is None:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def delete_proposal(pid: str) -> bool:
    p = _proposal_path(pid)
    if p is None:
        return False
    p.unlink()
    return True


def rebase_proposal(pid: str, base_revision: int | None = None,
                    base_content: str | None = None) -> bool:
    """After a partial accept the file moved, so the text the proposal was built
    against is no longer the file. Re-point it (the content is unchanged and still
    applies) so the remaining hunks stay reviewable and honest about their base."""
    meta = read_proposal(pid)
    if meta is None:
        return False
    if base_revision is not None:
        meta["base_revision"] = int(base_revision)
    if base_content is not None:
        meta["base_content"] = base_content
    _write_proposal(meta)
    return True


def delete_proposals_for(book: str = "", series: str = "") -> int:
    """Drop pending changes for a book or a whole series (2.9.1).

    A proposal for a file that no longer exists is a banner nobody can act on, so
    it goes with the book. (Found by leaving one behind during verification.)
    """
    gone = 0
    for meta in list_proposals():
        if (book and meta["book"] == book) or (series and meta["series"] == series):
            gone += 1 if delete_proposal(meta["id"]) else 0
    return gone


def _supersede(book: str, path: str, keep_id: str) -> None:
    """One live draft per file: a new one replaces any older one (3.1, D55).

    Unaccepted changes are drafts. Nothing else prunes them, on purpose — like the
    trash, they are never erased by time alone."""
    mine = [m for m in list_proposals() if m["book"] == book and m["path"] == path]
    for stale in mine:
        if stale["id"] != keep_id:
            delete_proposal(stale["id"])


_HEADING_RE = re.compile(r"^\s*#\s+(\S.*?)\s*$", re.M)


def split_heading(text: str, fallback: str = "") -> tuple[str, str]:
    """Pull a leading `# Title` line off a revision → (body, title).

    The Muse is asked to send the complete chapter *including* its heading, but the
    save path writes its own heading — two of them would be a bug the author has to
    clean up by hand.
    """
    text = text or ""
    m = _HEADING_RE.match(text)
    if not m:
        return text.strip(), fallback
    return text[m.end():].lstrip("\n").rstrip(), (m.group(1).strip() or fallback)


def _edit_target(ctx: _ToolCtx, rel: str | None):
    """Resolve an editable path → (kind, normalized path, Path), or an ERROR string.

    Editable: a chapter of this book (`chapters/ch-03.md`, or just `ch-03`), or a
    bible file (`bible/places.md`, which may be new). Nothing else — not notes,
    not the series root, not hidden files. Empty → the conversation's chapter.
    """
    rel = (rel or "").strip().strip("/")
    if not rel:
        if not ctx.cid:
            return "ERROR: no chapter in context — name the file to edit."
        rel = f"chapters/{ctx.cid}.md"
    m = _BARE_CHAPTER_RE.match(rel)
    if m:
        rel = f"chapters/{m.group(1)}.md"
    m = _CHAPTER_PATH_RE.match(rel)
    if m:
        chapter = ar_mod.get_chapter(ctx.book_dir, m.group(1))
        if chapter is None:
            return f"ERROR: {rel} is not a chapter of this book."
        return ("chapter", f"chapters/{chapter.stem}.md", chapter)
    if rel.startswith("bible/"):
        dest = ar_mod.safe_bible_path(ctx.book_dir, rel[len("bible/"):])
        if dest is None:
            return f"ERROR: {rel} is not an editable bible file (bible/<name>.md only)."
        norm = "bible/" + dest.relative_to(
            (ctx.book_dir / "bible").resolve()).as_posix()
        return ("bible", norm, dest)
    return ("ERROR: you can only edit this book's chapters (chapters/ch-NN.md) and "
            "bible files (bible/<name>.md).")


def file_text(kind: str, f: Path) -> str:
    """What the file says now ("" for a bible file that doesn't exist yet)."""
    try:
        return f.read_text(encoding="utf-8") if f.is_file() else ""
    except OSError:
        return ""


def proposal_file(p: dict, bdir: Path) -> Path | None:
    """The story file a proposal targets, or None if it can no longer be resolved."""
    kind, path = proposal_target(p)
    if kind == "chapter":
        return ar_mod.get_chapter(bdir, p.get("chapter") or Path(path).stem)
    if path.startswith("bible/"):
        return ar_mod.safe_bible_path(bdir, path[len("bible/"):])
    return None


def is_stale(p: dict, bdir: Path) -> bool:
    """Has the file moved since the Muse read it?"""
    f = proposal_file(p, bdir)
    if f is None:
        return True
    kind, _ = proposal_target(p)
    if kind == "chapter":
        return int(p.get("base_revision") or 0) != ar_mod._read_revision_marker(f)
    return file_text(kind, f) != (p.get("base_content") or "")


def _normalized(text: str) -> str:
    return " ".join((text or "").split())


def _apply_strict(text: str, edits) -> tuple[str, str]:
    """Apply find/replace edits all-or-nothing → (new text, "") or (text, error)."""
    if not isinstance(edits, list) or not edits:
        return text, ("ERROR: send `edits` as a non-empty list of {old_text, new_text}. "
                      "Nothing was changed.")
    for n, e in enumerate(edits, 1):
        if not isinstance(e, dict):
            return text, f"ERROR: edit {n} is not an object. Nothing was changed."
        old, new = e.get("old_text"), e.get("new_text")
        if not isinstance(new, str) or not isinstance(old, str):
            return text, (f"ERROR: edit {n} needs an `old_text` and a `new_text` "
                          "(empty to delete). Nothing was changed.")
        if not old:
            if text.strip():
                return text, (f"ERROR: edit {n} needs a non-empty `old_text` — only a "
                              "brand-new file may be written from nothing. Nothing was "
                              "changed.")
            text = new
            continue
        hits = text.count(old)
        if hits == 0:
            return text, (f"ERROR: edit {n}: `old_text` was not found. Copy it exactly — "
                          "same words, punctuation and line breaks — from the file as "
                          "read_story_file returned it (or as your earlier edits left "
                          "it). Nothing was changed.")
        if hits > 1:
            return text, (f"ERROR: edit {n}: `old_text` appears {hits} times. Include "
                          "more of the surrounding text so it matches exactly once. "
                          "Nothing was changed.")
        text = text.replace(old, new, 1)
    return text, ""


def replay_edits(text: str, edits: list[dict]) -> tuple[str, list[dict]]:
    """Re-apply a draft's edits to a file the author has changed since (D58).

    Lenient where the tool call is strict: an edit whose `old_text` is gone but
    whose result is already there (the author accepted it, or wrote the same thing)
    is satisfied and skipped; one that matches is applied; anything else no longer
    applies and is returned in `dropped` — the author's newer prose always wins.
    """
    dropped: list[dict] = []
    for e in edits or []:
        old, new = e.get("old_text") or "", e.get("new_text") or ""
        if not old:
            if not text.strip():
                text = new
            continue
        hits = text.count(old)
        if hits == 1:
            text = text.replace(old, new, 1)
        elif hits == 0 and (not new or new in text):
            continue                       # already says what the edit wanted
        else:
            dropped.append(e)
    return text, dropped


def refresh_proposal(p: dict, bdir: Path) -> dict:
    """Bring a stale, edit-built draft up to date with the file (D58).

    A full rewrite can't be replayed (there is nothing to replay), so it stays stale
    and the accept route refuses it, as before (D49). Returns the (possibly
    rewritten) record; `p["empty"]` is set when nothing of the draft survives.
    """
    if not is_stale(p, bdir) or p.get("edits") is None:
        return p
    f = proposal_file(p, bdir)
    if f is None:
        return p
    kind, _ = proposal_target(p)
    current = file_text(kind, f)
    text, dropped = replay_edits(current, p["edits"])
    p["content"] = text
    p["words"] = ar_mod._count_words(text)
    p["edits"] = [e for e in p["edits"] if e not in dropped]
    p["dropped"] = (p.get("dropped") or []) + dropped
    if kind == "chapter":
        p["base_revision"] = ar_mod._read_revision_marker(f)
    else:
        p["base_content"] = current
    if _normalized(text) == _normalized(current):
        p["empty"] = True
    _write_proposal(p)
    return p


def _live_draft(ctx: _ToolCtx, path: str) -> dict | None:
    """The pending draft for `path` that new edits should stack on, if any (D55)."""
    for meta in list_proposals():
        if meta["book"] != ctx.book_dir.name or meta["path"] != path:
            continue
        full = read_proposal(meta["id"])
        if full is None:
            continue
        full = refresh_proposal(full, ctx.book_dir)
        if full.get("empty"):
            delete_proposal(full["id"])
            return None
        return None if is_stale(full, ctx.book_dir) else full
    return None


def _new_pid(book: str, path: str, now: datetime) -> str:
    stem = path[:-3] if path.endswith(".md") else path
    tag = stem.split("/", 1)[1] if stem.startswith("chapters/") else stem
    tag = re.sub(r"[^a-z0-9]+", "-", tag.lower()).strip("-")[:48] or "file"
    # Microseconds, deliberately: two drafts in the same second must not share an id,
    # or the second silently overwrites the first.
    return f"{book[:48]}-{tag}-{now.strftime('%Y%m%dt%H%M%S%f')}"


def _park(ctx: _ToolCtx, kind: str, path: str, f: Path, text: str,
          edits: list | None, turn: dict | None) -> str:
    """Write a new pending draft of `path` holding `text`; return its id."""
    now = datetime.now(timezone.utc)
    pid = _new_pid(ctx.book_dir.name, path, now)
    meta = {
        "id": pid,
        "series": ctx.series_dir.name,
        "book": ctx.book_dir.name,
        "kind": kind,
        "path": path,
        "chapter": f.stem if kind == "chapter" else "",
        "origin": ctx.cid,
        "batch": (turn or {}).get("batch", ""),
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "content": text,
        "words": ar_mod._count_words(text),
        "edits": list(edits) if edits is not None else None,
    }
    if kind == "chapter":
        meta["base_revision"] = ar_mod._read_revision_marker(f)
    else:
        meta["base_content"] = file_text(kind, f)
    _write_proposal(meta)
    _supersede(ctx.book_dir.name, path, pid)
    _touch(turn, path, pid)
    return pid


def _touch(turn: dict | None, path: str, pid: str) -> None:
    """Remember, for this turn, which draft holds `path` — and that it changed."""
    if turn is None:
        return
    turn.setdefault("staged", {})[path] = pid
    touched = turn.setdefault("touched", [])
    if pid not in touched:
        touched.append(pid)
    turn["proposal_id"] = pid


def _save_draft(meta: dict, text: str, turn: dict | None) -> None:
    meta["content"] = text
    meta["words"] = ar_mod._count_words(text)
    if turn and turn.get("batch"):
        meta["batch"] = turn["batch"]
    _write_proposal(meta)
    _touch(turn, proposal_target(meta)[1], meta["id"])


def _propose_rewrite(ctx: _ToolCtx, content: str, turn: dict | None) -> str:
    """Stage a whole-chapter revision for approval; tell the model what happened.

    It parks a proposal, the author reviews it, and *accepting* is a normal save —
    so D9's time machine snapshots it like any other edit. Nothing an LLM says ever
    rewrites the author's prose unattended.
    """
    text = (content or "").strip()
    if not text:
        return ("ERROR: nothing arrived. Send the COMPLETE revision in markdown, "
                "including its `# Title` line. Nothing was handed over.")
    if not ctx.cid:
        return "ERROR: no chapter in context — nothing was handed over."
    chapter = ar_mod.get_chapter(ctx.book_dir, ctx.cid)
    if chapter is None:
        return (f"ERROR: {ctx.cid} is not in this book any more — nothing was "
                "handed over.")
    path = f"chapters/{chapter.stem}.md"

    staged_id = ((turn or {}).get("staged") or {}).get(path)
    prior = read_proposal(staged_id) if staged_id else None
    if prior is not None and prior.get("edits") is not None:
        # Edits were staged earlier in this turn and now a whole chapter arrives: it
        # supersedes them (it was written knowing them, or instead of them).
        if len(text) >= PROPOSAL_MIN_CHARS:
            prior["edits"] = None
            _save_draft(prior, text, turn)
            return ("The staged edits were replaced by this complete revision — NOT "
                    "saved. Tell the author it is ready to review.")
    elif prior is not None:
        # A later part of the same revision, inside the same turn: append instead of
        # starting over. This is what makes "send it in parts" real for chapters that
        # are too long to fit in one response.
        merged = (prior.get("content") or "").rstrip() + "\n\n" + text
        _save_draft(prior, merged, turn)
        return (f"Part appended — the revision now stands at {prior['words']} "
                "words. Send the next part if the chapter is not finished, "
                "otherwise tell the author it is ready to review.")

    if len(text) < PROPOSAL_MIN_CHARS:
        return (f"ERROR: that is only {len(text)} characters — not a chapter. Send "
                f"the COMPLETE revision (at least {PROPOSAL_MIN_CHARS} characters) in "
                "markdown, including its `# Title` line. Nothing was handed over.")
    current = chapter.read_text(encoding="utf-8")
    if _normalized(text) == _normalized(current):
        return ("ERROR: that is identical to the chapter as it stands, so there is "
                "nothing for the author to review.")

    _park(ctx, "chapter", path, chapter, text, None, turn)
    return ("Handed to the author for approval — NOT saved. They are being shown a "
            "diff of your revision against the current chapter. Do NOT paste the "
            "chapter into the chat: reply in one or two sentences telling them to "
            "review the diff and Accept.")


def _edit_file(ctx: _ToolCtx, path: str | None, edits, turn: dict | None) -> str:
    """Targeted find/replace edits to a chapter or bible file, staged for review.

    The IDE-shaped way to change the story: the Muse names the exact passage and its
    replacement instead of re-sending 5,000 words. The edits apply to a *copy* — the
    live draft for that file if there is one (D55), else the file as it stands — and
    the result is parked for the author to review per hunk; accepting is a normal
    save. A call is all-or-nothing, so a half-applied set of edits can never reach
    the review pane.
    """
    target = _edit_target(ctx, path)
    if isinstance(target, str):
        return target
    kind, rel, f = target
    current = file_text(kind, f)
    if kind == "chapter" and not current:
        return f"ERROR: {rel} could not be read. Nothing was changed."

    staged_id = ((turn or {}).get("staged") or {}).get(rel)
    prior = read_proposal(staged_id) if staged_id else None
    if prior is None:
        prior = _live_draft(ctx, rel)
    base = prior["content"] if prior is not None else current

    text, err = _apply_strict(base, edits)
    if err:
        return err
    if _normalized(text) == _normalized(current):
        return ("ERROR: those edits leave the file exactly as it is on disk. Nothing "
                "was staged.")
    if kind == "bible" and not text.endswith("\n"):
        text += "\n"

    if prior is not None:
        if prior.get("edits") is not None:
            prior["edits"] = list(prior["edits"]) + list(edits)
        _save_draft(prior, text, turn)
    else:
        _park(ctx, kind, rel, f, text, list(edits), turn)
    creating = kind == "bible" and not f.is_file()
    return (f"{len(edits)} edit(s) to {rel} staged for the author's review"
            f"{' (a new file)' if creating else ''} — NOT saved. Further edit_file calls "
            "stack on the same draft, and read_story_file now shows you the draft. When "
            "you are done, tell the author in a sentence or two what you changed and "
            "that it is waiting for them to review and accept. Do not paste the text.")


def _run_tool(ctx: _ToolCtx, name: str, args: dict, out: dict | None = None) -> str:
    args = args or {}
    if args.get("__malformed"):
        # Truncated tool arguments: say so plainly instead of reporting an empty
        # handover, or the model retries the same doomed call (it did, five times).
        return ("ERROR: your tool arguments arrived as invalid JSON — they were cut off "
                "before the end, which happens when a long single response runs out of "
                "output room. Nothing was handed over. If the revision is long, send it "
                "in PARTS: call this tool once per part, in order, and each call appends "
                "to the same revision — or use edit_file for targeted changes.")
    if name == "list_story_files":
        return _list_story_files(ctx)
    if name == "read_story_file":
        return _read_story_file(ctx, str(args.get("path", "")))
    if name == "search_story":
        return _search_story(ctx, str(args.get("query", "")))
    if name == "propose_chapter_rewrite":
        return _propose_rewrite(ctx, str(args.get("content", "")), out)
    if name == "edit_file":
        return _edit_file(ctx, args.get("path"), args.get("edits"), out)
    return f"ERROR: unknown tool {name}"


_TOOLS = [
    {"type": "function", "function": {
        "name": "list_story_files",
        "description": "List every readable story file for the current book (chapters, bible, notes) plus the series root.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "read_story_file",
        "description": ("Read one story file by its exact path as returned by "
                        "list_story_files. If you have a change waiting on that file, "
                        "you get your pending draft (edits apply on top of it)."),
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string",
                                    "description": "e.g. chapters/ch-03.md, bible/characters/kael.md, or series/<name>.md"}},
            "required": ["path"],
        },
    }},
    {"type": "function", "function": {
        "name": "search_story",
        "description": "Full-text search across this book's chapters and bible.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": (
            "Edit a chapter or bible file with targeted find-and-replace changes. Use "
            "this for any change smaller than a full rewrite: fixing lines, tightening "
            "paragraphs, renaming, inserting or cutting a passage, updating the bible. "
            "Call it once per file; a change that spans files (e.g. renaming a "
            "character everywhere) is one call per file. Each `old_text` must be copied "
            "EXACTLY from the file (read it first with read_story_file) and must match "
            "exactly once; `new_text` replaces it (empty deletes it). To create a NEW "
            "bible file, send a single edit with an empty `old_text` and the whole file "
            "as `new_text`. The edits are staged, NOT saved: the author reviews each "
            "change and accepts or rejects it. More calls on the same file stack on the "
            "same draft."),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "chapters/ch-NN.md or bible/<name>.md; omit "
                                        "for the chapter the author has open"},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_text": {"type": "string",
                                         "description": "exact text currently in the file"},
                            "new_text": {"type": "string",
                                         "description": "what replaces it"},
                        },
                        "required": ["old_text", "new_text"],
                    },
                },
            },
            "required": ["edits"],
        },
    }},
    {"type": "function", "function": {
        "name": "propose_chapter_rewrite",
        "description": (
            "Hand the author a COMPLETE revised version of the open chapter for "
            "approval. Use this only when they ask you to write, rewrite or restructure "
            "the whole chapter — for smaller changes use edit_file. It is NOT saved and you "
            "cannot save it: the author is shown a word-level diff and accepting it "
            "creates a normal revision snapshot. Send the entire chapter in "
            "markdown, including its `# Title` line. One call is enough for a normal "
            "chapter; for a very long one, send it in PARTS — call this tool once per "
            "part, in order, and each call appends to the same revision. Do NOT also "
            "paste the chapter into the chat — afterwards just tell them it is ready "
            "to review."),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string",
                            "description": "the complete revised chapter, in markdown, "
                                           "starting with its `# Title` line"},
            },
            "required": ["content"],
        },
    }},
]

AGENT_SYSTEM = (
    "You are the Muse, a story-writing companion working inside the author's "
    "story archive. Use the provided tools to read the story files (chapters, "
    "bible, notes) whenever you need detail — never invent plot, characters, or "
    "facts you have not read. Discuss only this story. "
    # Two rules learned the hard way (2.8.1):
    #  * the model would announce a tool use and end the turn — the author was
    #    left with "I'll re-open ch-01…" and no work;
    #  * it would offer to fix a chapter without producing the prose.
    "If you need to read something, CALL the tool in the same turn you decide to: "
    "never end a reply with a statement of intent ('I'll re-open ch-01', 'let me "
    "read that file') instead of calling it, because that leaves the author with "
    "nothing to act on. You edit the story the way a coding assistant edits files: "
    "when the author asks you to write, fix, tighten or rewrite anything in a "
    "chapter or the bible, make the change yourself with edit_file (targeted "
    "edits, any chapter or bible file) or propose_chapter_rewrite (the whole open "
    "chapter). You cannot save: every change is staged as a proposal the author "
    "reviews and accepts, so make the edit rather than describing it, and don't "
    "paste the changed text into the chat. Never answer a writing request with a "
    "plan to do it later. "
    "When you have what you need, answer the author directly and concisely."
)


# --- public: chat ---------------------------------------------------------

CHIP_PROMPTS: dict[str, str] = {
    "rewrite": "Rewrite the user's selected passage in proper novel English. Reply with ONLY the rewrite — no preamble, no explanation.",
    "continue": "Continue the scene from where it left off, matching the established voice and cadence. Write 1–3 paragraphs.",
    "scene": "Write a new scene that follows naturally from the current chapter. Include a setting, characters from the bible if relevant, and a hook at the end.",
    "canon": "Check the user's claim against the canon (the chapter text + bible). Reply with: VERIFIED / CONTRADICTS / UNCLEAR, then one short sentence explaining.",
    # Inline edit on a selection (3.1, D57): the IDE's "edit this, here".
    "inline": (
        "The author selected a passage in the open chapter and gave an instruction "
        "for it. Change ONLY that passage, with ONE edit_file call on the open "
        "chapter whose `old_text` is the selected passage exactly as quoted (it is "
        "already saved in the file) and whose `new_text` carries out the "
        "instruction. Do not touch anything outside the selection and do not read "
        "other files unless the instruction needs them. Then reply with one short "
        "sentence."),
    # A Fix button on a continuity issue (3.1, D60).
    "fix": (
        "The author wants a continuity issue fixed. Read the files involved, decide "
        "which side is wrong (the bible usually records intent; the latest chapter "
        "usually records what the author wrote last), and fix it with edit_file — "
        "one call per file, smallest change that resolves the issue. Then say in one "
        "or two sentences what you changed and why."),
}


def _new_batch() -> str:
    return datetime.now(timezone.utc).strftime("t%Y%m%d%H%M%S%f")


async def chat(
    messages: list[dict],
    chapter_id: str | None = None,
    chip: str | None = None,
) -> AsyncIterator:
    """Stream an agentic chat reply from the Muse.

    `messages` is the full OpenAI-style thread (last item is the user turn).
    When `chapter_id` resolves, the model is given tools to fetch the story on
    demand — we hand it the file index + style digest + the author's rules, NOT
    the chapter itself (plus whatever the author @-mentioned).
    `chip` (rewrite/continue/scene/canon/inline/fix) rides along as a system hint.
    """
    ctx = _tool_ctx(chapter_id)
    sys_parts: list[dict] = [{"role": "system", "content": AGENT_SYSTEM}]
    if chip and chip in CHIP_PROMPTS:
        sys_parts.append({"role": "system", "content": CHIP_PROMPTS[chip]})
    attached: list[str] = []
    if ctx is not None:
        index = _list_story_files(ctx)
        if index and index != "(no files)":
            sys_parts.append({"role": "system", "content": "FILES IN THIS STORY:\n" + index})
        digest = await _load_style_summary(ctx.book_dir.name, ctx.book_dir)
        if digest:
            sys_parts.append({"role": "system", "content": "## STORY STYLE (keep this voice)\n\n" + digest})
        rules = _rules_block(ctx.book_dir)
        if rules:
            sys_parts.append({"role": "system", "content": rules})
        last_user = next((m.get("content") or "" for m in reversed(messages)
                          if m.get("role") == "user"), "")
        attached = resolve_mentions(ctx, last_user)
        block = _mention_block(ctx, attached)
        if block:
            sys_parts.append({"role": "system", "content": block})

    if attached:
        yield Status("attached " + ", ".join(Path(a).name for a in attached))

    payload: dict = {
        "model": MUSE_AGENT_MODEL,
        "messages": [*sys_parts, *messages],
        # MUSE_AGENT_MAX_TOKENS, not MUSE_NUM_PREDICT: this turn may have to write a
        # whole chapter into a tool argument (2.9.1).
        "options": {"num_predict": MUSE_AGENT_MAX_TOKENS, "temperature": 0.8},
    }
    if ctx is not None:
        payload["tools"] = _TOOLS

    full_text_parts: list[str] = []
    hit_limit = False
    usage = Usage()
    # These live OUTSIDE the round loop: a revision can span several tool calls (and
    # therefore several rounds), and it is announced once the whole turn is finished.
    turn: dict = {"batch": _new_batch()}
    for _round in range(MUSE_MAX_TOOL_ROUNDS):
        meta: dict = {}
        async for delta in _stream_visible(payload, meta):
            full_text_parts.append(delta)
            yield delta
        usage.add({"input": meta["usage"].input, "output": meta["usage"].output})
        calls = meta.get("tool_calls") or []
        if not calls or ctx is None:
            hit_limit = False
            break
        hit_limit = True
        # Echo the assistant's tool-call turn, then answer each call.
        payload["messages"].append({"role": "assistant", "content": "", "tool_calls": calls})
        for tc in calls:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    # The arguments were cut off mid-JSON. That happens when one turn
                    # runs out of output room to write a whole chapter (~4096 tokens
                    # before 2.9.1), and it must NOT look like an empty handover to the
                    # model — it spent five retries doing exactly that, live.
                    args = {"__malformed": True}
            args = args or {}
            if name == "propose_chapter_rewrite":
                # Not a read: the Muse is handing over a whole-chapter revision for
                # approval (2.9, D45).
                yield Status("preparing a full-chapter revision…")
            elif name == "edit_file":
                yield Status(f"editing {args.get('path') or 'the chapter'}…")
            else:
                label = args.get("path") or args.get("query")
                if not label:
                    # A tool that takes no path still deserves a human status line:
                    # the author saw 'reading list_story_files…' and it read like a bug.
                    label = _TOOL_LABELS.get(name) or name.replace("_", " ")
                yield Status(f"reading {label}…")
            result = _run_tool(ctx, name, args, turn)
            payload["messages"].append({"role": "tool", "tool_name": name, "content": result})

    if hit_limit:
        # Ran out of rounds mid-fetch: force a final answer with no tools.
        payload.pop("tools", None)
        meta = {}
        async for delta in _stream_visible(payload, meta):
            full_text_parts.append(delta)
            yield delta
        usage.add({"input": meta["usage"].input, "output": meta["usage"].output})

    # Announced only once the turn is over: a revision that arrives in parts must not
    # raise the "review" banner while it is still half-sent, or the author could
    # accept a third of a chapter (2.9.2).
    for pid in turn.get("touched", []):
        if read_proposal(pid) is not None:
            yield Proposal(pid)
    if usage:
        yield usage

    # Persist the exchange AFTER the stream finishes.
    if chapter_id and messages:
        _persist_thread(chapter_id, messages, "".join(full_text_parts))


# --- public: rewrite ------------------------------------------------------

STYLE_PROMPTS: dict[str, str] = {
    "novel": "Rewrite the user's selection as polished literary prose. Maintain the original's voice but tighten cadence, vary sentence length, and surface sensory detail. Reply with ONLY the rewrite.",
    "scene": "Rewrite the selection as a vivid, cinematic scene. Strong verbs, specific nouns, present-tense energy. Reply with ONLY the rewrite.",
    "clean": "Clean up grammar and word choice with minimal stylistic change. Preserve the author's voice exactly; only fix the rough edges. Reply with ONLY the rewrite.",
}


async def rewrite(
    text: str,
    style: str = "novel",
    chapter_id: str | None = None,
) -> AsyncIterator:
    """Stream a single rewrite proposal for `text` in the chosen `style`."""
    sys_parts: list[dict] = [{"role": "system", "content": STYLE_PROMPTS.get(style, STYLE_PROMPTS["novel"])}]
    if chapter_id:
        parsed = _parse_chapter_id(chapter_id)
        rules = _rules_block(_resolve_bdir(parsed[0], parsed[1]) if parsed else None)
        if rules:
            sys_parts.append({"role": "system", "content": rules})
        canon = await _load_canon_context(chapter_id, user_prompt=text)
        if canon:
            sys_parts.append({"role": "system", "content": canon})

    payload = {
        "model": MUSE_REWRITE_MODEL,
        "messages": [
            *sys_parts,
            {"role": "user", "content": text},
        ],
        "options": {"num_predict": MUSE_NUM_PREDICT, "temperature": 0.7},
    }
    full_text_parts: list[str] = []
    meta: dict = {}
    async for delta in _post_chat(payload, meta):
        full_text_parts.append(delta)
        yield delta
    if meta.get("usage"):
        yield meta["usage"]
    if chapter_id:
        _persist_thread(chapter_id, [{"role": "user", "content": text}], "".join(full_text_parts))


# --- public: ghost-text completion (3.1, D59) ------------------------------

COMPLETE_SYSTEM = (
    "You are an autocomplete inside a novelist's editor. Continue the text from "
    "exactly where it stops: at most one sentence (under 25 words), in the same "
    "voice, tense and point of view. Reply with ONLY the continuation — no quotes, "
    "no preamble, no explanation. If the text ends mid-word, finish the word."
)
COMPLETE_CONTEXT = 3000       # chars before the cursor the model sees


async def complete_text(before: str, chapter_id: str | None = None) -> str:
    """A short continuation of `before` — one sentence, for Tab-to-accept ghost text."""
    before = (before or "")[-COMPLETE_CONTEXT:]
    if not before.strip():
        return ""
    sys_parts = [{"role": "system", "content": COMPLETE_SYSTEM}]
    parsed = _parse_chapter_id(chapter_id) if chapter_id else None
    rules = _rules_block(_resolve_bdir(parsed[0], parsed[1]) if parsed else None)
    if rules:
        sys_parts.append({"role": "system", "content": rules})
    payload = {
        "model": MUSE_COMPLETE_MODEL,
        "messages": [*sys_parts, {"role": "user", "content": before}],
        "stream": False,
        "options": {"num_predict": MUSE_COMPLETE_MAX_TOKENS, "temperature": 0.7},
    }
    obj = await up_mod.complete(payload, _client)
    text = strip_think((obj.get("message") or {}).get("content") or "")
    text = text.split("\n", 1)[0].rstrip()
    text = text.strip("\"“”")
    if not text.strip():
        return ""
    # Glue: the model rarely knows whether the cursor sits after a space. After
    # whitespace, no leading space; after a word or punctuation, a new word needs one.
    if before[-1:].isspace():
        text = text.lstrip()
    elif text[:1].isalnum():
        text = " " + text
    return text[:240]


# --- public: models info --------------------------------------------------

def models_info() -> dict:
    """Return the models the server actually routes to (for the UI/health).

    The upstream base URL is deliberately not exposed — a client never needs
    it, and it is an internal network address."""
    return {
        "chat_model": MUSE_AGENT_MODEL,      # agentic chat
        "agent_model": MUSE_AGENT_MODEL,     # same setting, explicit name
        "rewrite_model": MUSE_REWRITE_MODEL,  # rewrite + sweep + style digest
    }


# --- canon context (D18) --------------------------------------------------

def _resolve_bdir(series_slug: str, book_slug: str) -> Path | None:
    """Resolve a series+book to a book dir, matching by slug/id/title (same
    fallback as main.py:_resolve_book_path). None if not found."""
    if not ar_mod.is_slug(series_slug) or not book_slug:
        return None
    sd = ARCHIVE_ROOT / series_slug
    if not sd.is_dir():
        return None
    if ar_mod.is_slug(book_slug):
        bdir = sd / book_slug
        if bdir.is_dir():
            return bdir
    for b in sorted(sd.iterdir()):
        if not b.is_dir() or b.name.startswith("."):
            continue
        meta = ar_mod._read_book_json(b)  # type: ignore[attr-defined]
        if meta.get("id") == book_slug or meta.get("title") == book_slug:
            return b
    return None


def _parse_chapter_id(chapter_id: str) -> tuple[str, str, str] | None:
    """`series/book/ch-XX` → (series_slug, book_slug, chapter_id)."""
    parts = chapter_id.split("/")
    if len(parts) != 3:
        return None
    series_slug, book_slug, cid = parts
    if not ar_mod.is_slug(series_slug) or not ar_mod.is_slug(book_slug):
        return None
    if not ar_mod.is_chapter_id(cid):
        return None
    return series_slug, book_slug, cid


async def _load_canon_context(chapter_id: str, user_prompt: str = "") -> str:
    """Build the canon-context system prompt for `chapter_id`.

    Returns "" if the chapter doesn't resolve. Otherwise returns a string
    containing:
      - a STYLE summary (cached per book, from D19-style)
      - the CURRENT CHAPTER full text
      - up to 4 FTS5-ranked BIBLE entries matching the user prompt
    The whole block is capped at MUSECONTEXT_MAX_TOKENS (~6000) chars/4.
    """
    parsed = _parse_chapter_id(chapter_id)
    if not parsed:
        return ""
    series_slug, book_slug, cid = parsed
    bdir = _resolve_bdir(series_slug, book_slug)
    if bdir is None:
        return ""
    chapter_path = bdir / "chapters" / f"{cid}.md"
    if not chapter_path.is_file():
        return ""
    chapter_text = chapter_path.read_text(encoding="utf-8")

    # Style digest (cached per book). Auto-generates on first touch.
    style_digest = await _load_style_summary(book_slug, bdir)

    # Bible hits — rank against the user prompt (or the chapter text), scoped
    # to this book and matched on ANY distinctive term (see _fts_or_query).
    query = _fts_or_query((user_prompt or chapter_text)[:500])
    bible_hits: list[dict] = []
    if query:
        try:
            bible_hits = db.search(query, limit=8, book_id=bdir.name)
        except Exception:
            bible_hits = []
    bible_block = ""
    if bible_hits:
        blocks = []
        for h in bible_hits:
            if h.get("kind") != "bible":
                continue
            blocks.append(
                f"### {h.get('title') or h.get('doc_id')}\n"
                f"{_plain_snippet(h.get('snippet', ''))}"
            )
            if len(blocks) >= 4:
                break
        if blocks:
            bible_block = "## CANON (relevant bible entries)\n\n" + "\n\n".join(blocks)

    style_part = (
        "## STORY STYLE (the voice you've established)\n\n" + style_digest
        if style_digest else ""
    )
    chapter_part = (
        "## CURRENT CHAPTER (what you're rewriting inside)\n\n"
        + chapter_text.strip()
    )
    block = "\n\n---\n\n".join(p for p in (style_part, chapter_part, bible_block) if p)

    # Cap at ~6000 tokens = ~24000 chars. Keep the chapter (the centerpiece)
    # intact for as long as the budget allows; trim style + canon first.
    char_cap = MUSECONTEXT_MAX_TOKENS * 4
    if len(block) > char_cap:
        budget = max(0, char_cap - 200)
        style_keep = style_part[: min(len(style_part), budget // 6)]
        canon_keep = bible_block[: min(len(bible_block), budget // 4)]
        remaining = max(0, budget - len(style_keep) - len(canon_keep))
        chapter_keep = chapter_text.strip()[:remaining]
        block = "\n\n---\n\n".join(
            p for p in (
                style_keep,
                "## CURRENT CHAPTER (what you're rewriting inside)\n\n" + chapter_keep,
                canon_keep,
            ) if p
        ) + "\n\n[…truncated…]"
    return block


# --- thread persistence (D19) --------------------------------------------

def _thread_path(chapter_id: str, *, legacy: bool = False) -> Path | None:
    """Where a chapter's Muse conversation lives.

    Named `<book>-<chapter>.md`, NOT `<chapter>.md`: chapter ids repeat across
    books (`ch-01` exists in every book), so a chapter-only name means two books
    silently share one conversation log — and deleting a chapter would take the
    other book's history with it. The legacy chapter-only name is still *read*
    (see `read_thread`) and carried over on first write, so the author's existing
    threads keep working.
    """
    parsed = _parse_chapter_id(chapter_id)
    if not parsed:
        return None
    _series, book, cid = parsed
    return _MUSE_ROOT / (f"{cid}.md" if legacy else f"{book}-{cid}.md")


def _persist_thread(chapter_id: str, user_messages: list[dict], assistant_text: str) -> None:
    """Append ONE exchange to this chapter's thread file.

    Only the final user turn is written — the client already re-sends the
    whole thread on every request, so persisting all of it grew the file
    quadratically. Best-effort: failures here MUST NOT break the stream.
    """
    try:
        path = _thread_path(chapter_id)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        last_user = next(
            (m for m in reversed(user_messages) if m.get("role") == "user"),
            None,
        )
        user_text = (last_user or {}).get("content", "")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n## {ts}\n\n")
            f.write(f"<!-- katha:user -->\n{user_text}\n\n")
            f.write(f"<!-- katha:assistant -->\n{assistant_text}\n\n")
            f.write("<!-- katha:end -->\n")
    except Exception as e:
        # Never break the response over persistence.
        import sys
        print(f"[muse] persist_thread failed: {e}", file=sys.stderr)


async def _load_style_summary(book_slug: str, bdir: Path) -> str:
    """Return the cached style digest for `book_slug`, or generate one.

    Reads the last `MUSE_STYLE_PROSE_CHAPTERS` chapter files from `bdir`,
    asks MUSE_REWRITE_MODEL for a one-paragraph cadence/syntax/tone digest,
    writes it to `archive/.katha/muse/style-<book-slug>.md`, and returns it.

    Returns "" if the book has no chapters yet, or if generation fails — the
    Muse just skips the style digest and proceeds with the canon context.
    """
    style_path = _MUSE_ROOT / f"style-{book_slug}.md"
    if style_path.is_file():
        return style_path.read_text(encoding="utf-8").strip()

    chapters_dir = bdir / "chapters"
    if not chapters_dir.is_dir():
        return ""

    # Most recent N chapters by filename sort (ch-01, ch-02, …).
    chap_files = ar_mod.chapter_files(chapters_dir)
    chap_files = chap_files[-MUSE_STYLE_PROSE_CHAPTERS:]
    if not chap_files:
        return ""

    prose = "\n\n---\n\n".join(p.read_text(encoding="utf-8") for p in chap_files)
    # ~6000 chars is plenty for the model to see cadence without flooding context.
    prose = prose[:6000]

    prompt = (
        "Read the following excerpts from a novel-in-progress. In ONE paragraph "
        "(3–5 sentences), describe the prose voice — cadence (sentence length "
        "and rhythm), syntax (clause structure, punctuation habits), tone "
        "(mood, formality, sensory density). The output will be used as a "
        "style fingerprint to keep future rewrites consistent. Reply with ONLY "
        "the paragraph, no preamble.\n\n---\n\n" + prose
    )
    digest = ""
    try:
        payload = {
            "model": MUSE_REWRITE_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_predict": 400, "temperature": 0.4},
        }
        # Async on purpose: this runs inside streaming generators. A sync
        # client here froze the whole event loop for up to the full timeout.
        obj = await up_mod.complete(payload, _client)
        digest = strip_think((obj.get("message") or {}).get("content") or "").strip()
    except Exception as e:
        import sys
        print(f"[muse] style digest generation failed: {e}", file=sys.stderr)
        return ""

    if not digest:
        return ""

    try:
        style_path.parent.mkdir(parents=True, exist_ok=True)
        style_path.write_text(digest + "\n", encoding="utf-8")
    except Exception as e:
        import sys
        print(f"[muse] style digest write failed: {e}", file=sys.stderr)
    return digest


def read_thread(chapter_id: str) -> str:
    """Return the persisted thread for `chapter_id` (empty if none).

    **Book-scoped only.** A chapter id is not unique across books (`ch-01` is in
    every one of them), so there is deliberately no fallback to the old
    chapter-only name: that fallback meant a *different* book's ch-01 was served
    the first book's conversation. Pre-2.4 files are attributed to their book
    once, at boot, by `migrate_legacy_threads()`.
    """
    path = _thread_path(chapter_id)
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


# Where un-attributable pre-2.4 threads are kept. Kept — never deleted — but
# never served either.
_LEGACY_DIR = _MUSE_ROOT / "legacy"

# A chapter written within this many seconds of the thread counts as "existing
# when the chat happened" — files get touched by saves, editors and moves.
_CLAIM_SLACK = 60.0


def _chapter_claimants(cid: str, before: float | None = None) -> set[str]:
    """Every book id that has a chapter `<cid>` — in the archive *and* the trash.

    The trash lives inside the archive (`.katha/trash/`), so one scan covers
    both. That matters: a book the author has deleted (and can restore) must
    still be able to claim its own conversation, and a book that no longer exists
    claims nothing.

    With `before` (an mtime) only books whose chapter already existed by then
    count. That is how two books sharing a chapter id are told apart: a
    conversation cannot belong to a book whose `ch-01` was written afterwards.
    """
    owners: set[str] = set()
    for chapters in ARCHIVE_ROOT.glob("**/chapters"):
        if not chapters.is_dir() or chapters.parent.name == "chapters":
            continue
        chapter = chapters / f"{cid}.md"
        if not chapter.is_file():
            continue
        if before is not None:
            try:
                if chapter.stat().st_mtime > before + _CLAIM_SLACK:
                    continue          # the chapter is newer than the conversation
            except OSError:
                continue
        owners.add(chapters.parent.name)
    return owners


def migrate_legacy_threads() -> dict:
    """Give pre-2.4 chapter-only threads a home under the book that owns them.

    Before 2.4 a thread file was named after the chapter alone (`ch-01.md`), so
    every book's ch-01 shared one file. Each legacy file is adopted by the single
    book that both owns that chapter id and had that chapter when the
    conversation was written. Anything still un-attributable is *kept* in
    `.katha/muse/legacy/` and re-examined on the next boot — never served to a
    book that might not own it, never deleted.

    Runs at startup, so a book deleted today and restored tomorrow gets its chat
    back then.
    """
    result: dict = {"adopted": [], "set_aside": [], "kept": []}
    if not _MUSE_ROOT.is_dir():
        return result
    candidates = list(_MUSE_ROOT.glob("ch-*.md"))
    if _LEGACY_DIR.is_dir():
        candidates += list(_LEGACY_DIR.glob("ch-*.md"))
    for path in sorted(candidates):
        cid = path.stem
        try:
            written = path.stat().st_mtime
        except OSError:
            written = None
        owners = _chapter_claimants(cid, before=written)
        if len(owners) == 1:
            dest = _MUSE_ROOT / f"{next(iter(owners))}-{cid}.md"
            if not dest.exists():
                shutil.move(str(path), str(dest))
                result["adopted"].append(dest.name)
                continue
        if path.parent == _LEGACY_DIR:
            result["kept"].append(path.name)      # still nobody's: leave it be
            continue
        _LEGACY_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(_LEGACY_DIR / path.name))
        result["set_aside"].append(path.name)
    return result


_THREAD_TURN_RE = re.compile(
    r"\*\*(USER|ASSISTANT)\*\*:\s*(.*?)(?=\n\*\*(?:USER|ASSISTANT)\*\*:|\n---|\Z)",
    re.DOTALL,
)
# New format: HTML-comment markers are invisible in rendered markdown and
# cannot be produced by ordinary prose (a horizontal rule or a `## ` heading
# used to truncate the exchange).
_THREAD_MARK_RE = re.compile(r"<!--\s*katha:(user|assistant|end)\s*-->")


def thread_messages(chapter_id: str) -> list[dict]:
    """Parse the persisted thread md into [{role, text}] (oldest first).

    This is what makes persistence useful: the client reloads the thread when
    a chapter opens instead of the file being a write-only log."""
    text = read_thread(chapter_id)
    if not text:
        return []
    if not _THREAD_MARK_RE.search(text):
        # Legacy files (pre-2.0.1) used `**USER**: …` + a `---` terminator.
        return [
            {"role": m.group(1).lower(), "text": m.group(2).strip()}
            for m in _THREAD_TURN_RE.finditer(text)
            if m.group(2).strip()
        ]

    out: list[dict] = []
    role: str | None = None
    pos = 0
    for m in _THREAD_MARK_RE.finditer(text):
        if role and m.start() > pos:
            chunk = text[pos:m.start()].strip()
            if chunk:
                out.append({"role": role, "text": chunk})
        role = None if m.group(1) == "end" else m.group(1)
        pos = m.end()
    if role and text[pos:].strip():
        out.append({"role": role, "text": text[pos:].strip()})
    return out


# --- canon sweep (0.4) ----------------------------------------------------
# A whole-manuscript continuity pass. Two targets:
#   report → stream a markdown audit, one located issue per bullet (read-only;
#            each issue gets a Fix button in the app, 3.1, D60)
#   bible  → a proposed rewrite of one bible file, staged as a proposal and
#            reviewed per hunk like any other Muse change (3.1, D54)

SWEEP_REPORT_PROMPT = (
    "You are a continuity editor for a novel-in-progress. Read the whole "
    "manuscript and its story bible below, then write a concise markdown report "
    "with exactly these four sections: `## Canon contradictions`, `## Timeline "
    "errors`, `## Character inconsistencies` (names, traits, voice), `## Open "
    "questions`. Under each, write ONE bullet per issue, and start every bullet "
    "with where the issue is, in square brackets: the chapter id (`- [ch-03] …`), "
    "a bible file (`- [bible/timeline.md] …`), several separated by commas "
    "(`- [ch-02, bible/characters/kael.md] …`), or `[general]`. Then state the "
    "issue in one or two sentences, quoting the conflicting details. Report only "
    "real issues; if a section is clean, write a single bullet `- none`."
)

SWEEP_BIBLE_PROMPT = (
    "You maintain the story bible. Below is the full manuscript and the "
    "current version of one bible file. Rewrite that bible file so it "
    "accurately reflects the manuscript — fix omissions, wrong facts, and "
    "drift. Keep the existing markdown style and headings. Reply with ONLY "
    "the new file contents, no preamble."
)

# A sweep needs the whole book in context, so allow a larger cap than a
# single-chapter Muse call. (Wide, not infinite — deepseek-r1 has 131K.)
_SWEEP_CHAR_CAP = MUSECONTEXT_MAX_TOKENS * 8


def _load_full_book_context(bdir: Path) -> str:
    """Whole-book context: every chapter + every bible file, char-capped."""
    parts: list[str] = []
    for f in ar_mod.chapter_files(bdir / "chapters"):
        parts.append(f"### CHAPTER {f.stem}\n\n{f.read_text(encoding='utf-8').strip()}")
    bd = bdir / "bible"
    for f in ar_mod._iter_bible_files(bd):  # type: ignore[attr-defined]
        rel = f.relative_to(bd).as_posix()
        parts.append(f"### BIBLE: {rel}\n\n{f.read_text(encoding='utf-8').strip()}")
    block = "\n\n---\n\n".join(parts)
    if len(block) > _SWEEP_CHAR_CAP:
        block = block[:_SWEEP_CHAR_CAP] + "\n\n[…truncated…]"
    return block


async def sweep_report(series: str, book_id: str) -> AsyncIterator:
    """Stream a whole-book continuity audit (read-only)."""
    bdir = _resolve_bdir(series, book_id)
    if bdir is None:
        yield "Book not found."
        return
    context = _load_full_book_context(bdir) or "(this book has no chapters yet)"
    system = SWEEP_REPORT_PROMPT
    rules = _rules_block(bdir)
    if rules:
        system += "\n\n" + rules
    payload = {
        "model": MUSE_REWRITE_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": context},
        ],
        "options": {"num_predict": MUSE_NUM_PREDICT, "temperature": 0.3},
    }
    meta: dict = {}
    async for delta in _post_chat(payload, meta):
        yield delta
    if meta.get("usage"):
        yield meta["usage"]


async def sweep_bible(series: str, book_id: str, bible_name: str) -> AsyncIterator:
    """Stream a proposed rewrite of one bible file, then stage it for review.

    `bible_name` may be nested (`characters/kael.md`); the shared guard is the
    same one the PUT route uses, so sweep and save accept exactly the same
    paths and nothing outside bible/*.md. The streamed text is only a preview:
    what the author decides on is the staged proposal (`[PROPOSAL] <id>`)."""
    bdir = _resolve_bdir(series, book_id)
    if bdir is None:
        yield "Book not found."
        return
    target = ar_mod.safe_bible_path(bdir, bible_name or "")
    if target is None:
        yield "Invalid bible file name."
        return
    current = target.read_text(encoding="utf-8") if target.is_file() else "(new file)"
    context = _load_full_book_context(bdir)
    user = (
        f"## CURRENT BIBLE FILE: {bible_name}\n\n{current}\n\n"
        f"## FULL MANUSCRIPT\n\n{context}"
    )
    payload = {
        "model": MUSE_REWRITE_MODEL,
        "messages": [
            {"role": "system", "content": SWEEP_BIBLE_PROMPT},
            {"role": "user", "content": user},
        ],
        "options": {"num_predict": MUSE_NUM_PREDICT, "temperature": 0.4},
    }
    parts: list[str] = []
    meta: dict = {}
    async for delta in _post_chat(payload, meta):
        parts.append(delta)
        yield delta
    if meta.get("usage"):
        yield meta["usage"]

    text = "".join(parts).strip()
    # The adapter's "the model wrote nothing" sentence is a message to the author,
    # never a bible file — staging it would offer to replace the canon with an apology.
    if not text or meta.get("notice"):
        return
    text += "\n"
    if _normalized(text) == _normalized(file_text("bible", target)):
        yield Status("the bible file already matches the manuscript")
        return
    ctx = _ToolCtx(bdir.parent, bdir, "")
    rel = "bible/" + target.relative_to((bdir / "bible").resolve()).as_posix()
    pid = _park(ctx, "bible", rel, target, text, None, {"batch": _new_batch()})
    yield Proposal(pid)

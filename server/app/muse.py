"""Muse proxy — talks to a friend's Ollama box, hides the upstream from the
client (D16/D17/D19).

Public functions:
    chat(messages, chapter_id=None, chip=None) -> AsyncIterator[str]
    rewrite(text, style, chapter_id=None)      -> AsyncIterator[str]

Both yield visible prose tokens (never <think> blocks). The HTTP layer wraps
these in SSE.

The Ollama client lives at module scope so tests can swap its transport via
`monkeypatch.setattr(muse_mod, "_client", mock_client)`.

Canon context (D18): if a `chapter_id` like "series/book/ch-01" is passed, the
system prompt is prefixed with the current chapter + up to 4 FTS5-ranked bible
hits, capped at MUSECONTEXT_MAX_TOKENS (~6000 tokens).

Style learning (D19): the first time a book is touched, we read the last N
chapters and ask the Muse to summarize its cadence/syntax/tone. Cached to
`archive/.katha/muse/style-<book-slug>.md`.

Thread persistence (D19): every Muse exchange (user + assistant pair) is
appended to `archive/.katha/muse/<chapter-slug>.md`.
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
# Whole-chapter revisions the Muse hands to the author for approval (2.9, D45).
# They live beside the threads — inside the archive, so a backup covers them, and
# under a dot-directory, so no listing or search ever sees them. Nothing here is
# ever applied without the author's word.
_PROPOSAL_ROOT = ARCHIVE_ROOT / ".katha" / "proposals"
PROPOSAL_MIN_CHARS = 200     # shorter than this is not a chapter, it's a fragment
PROPOSAL_KEEP = 3            # newest N per book+chapter; older ones are pruned
_PID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}$")


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
# The dialect (Ollama-native vs OpenAI-compatible) lives in app/upstream.py —
# this module only ever sees normalized `{"content"|"tool_calls"}` events (D20).

async def _post_chat(payload: dict) -> AsyncIterator[str]:
    """Stream a turn from the active upstream; yield visible-only deltas."""
    filt = ThinkStreamFilter()
    async for event in up_mod.stream_events({**payload, "stream": True}, _client):
        visible = filt.feed(event.get("content") or "")
        if visible:
            yield visible
    tail = filt.finish()
    if tail:
        yield tail


# --- agentic chat: the model fetches story files via tools (1.1) ----------
# Instead of pre-injecting the chapter, the chat model gets tools to read the
# story on demand. Scope: the current book + the series root, .md only, never
# hidden dirs (.katha/) or anything outside the story archive.

class Status:
    """Marker yielded from a Muse generator to emit an SSE `[STATUS]` event
    (progress, e.g. 'reading ch-03…') rather than prose."""
    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text


class Proposal:
    """Marker yielded from a Muse generator to emit an SSE `[PROPOSAL] <id>` event:
    the Muse has handed over a whole-chapter revision and is waiting for the
    author to accept it (2.9, D45)."""
    __slots__ = ("proposal_id",)

    def __init__(self, proposal_id: str):
        self.proposal_id = proposal_id


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


def _list_story_files(ctx: _ToolCtx) -> str:
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
    return "\n".join(out) if out else "(no files)"


def _read_story_file(ctx: _ToolCtx, rel: str) -> str:
    p = _safe_story_path(ctx, rel)
    if p is None:
        return "ERROR: path not allowed — only story .md files in this book or the series root."
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


# --- whole-chapter proposals (2.9, D45) -----------------------------------

def _proposal_path(pid: str) -> Path | None:
    """Resolve a proposal id to its file, or None.

    The id arrives from a URL, so it is validated as a single slug segment and must
    resolve to a real file inside the proposals directory — no traversal, no dots.
    """
    if not _PID_RE.match(pid or ""):
        return None
    p = _PROPOSAL_ROOT / f"{pid}.json"
    return p if p.is_file() else None


def list_proposals() -> list[dict]:
    """Pending revisions, newest first — metadata only, never the chapter body."""
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
        out.append({
            "id": meta.get("id", p.stem),
            "series": meta.get("series", ""),
            "book": meta.get("book", ""),
            "chapter": meta.get("chapter", ""),
            "created_at": meta.get("created_at", ""),
            "words": meta.get("words", 0),
            "base_revision": meta.get("base_revision", 0),
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


def delete_proposals_for(book: str = "", series: str = "") -> int:
    """Drop pending revisions for a book or a whole series (2.9.1).

    A proposal for a chapter that no longer exists is a banner nobody can act on, so
    it goes with the book. (Found by leaving one behind during verification.)
    """
    gone = 0
    for meta in list_proposals():
        if (book and meta["book"] == book) or (series and meta["series"] == series):
            gone += 1 if delete_proposal(meta["id"]) else 0
    return gone


def _prune_proposals(book: str, cid: str) -> None:
    """Keep the newest PROPOSAL_KEEP revisions for one chapter.

    Unaccepted revisions are drafts; a handful per chapter is plenty. Nothing else
    prunes them, on purpose — like the trash, they are never erased by time alone.
    """
    mine = [m for m in list_proposals() if m["book"] == book and m["chapter"] == cid]
    for stale in mine[PROPOSAL_KEEP:]:
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


def _propose_rewrite(ctx: _ToolCtx, content: str, out: dict | None) -> str:
    """Park a whole-chapter revision for approval; tell the model what happened.

    This is the only way the Muse can touch the archive, and it still cannot: it
    parks a proposal, the author reviews a diff, and *accepting* is a normal save —
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

    # A later part of the same revision, inside the same turn: append instead of
    # starting over. This is what makes "send it in parts" real for chapters that are
    # too long to fit in one response.
    existing_id = (out or {}).get("proposal_id")
    if existing_id:
        prior = read_proposal(existing_id)
        if prior:
            merged = (prior.get("content") or "").rstrip() + "\n\n" + text
            prior["content"] = merged
            prior["words"] = ar_mod._count_words(merged)
            (_PROPOSAL_ROOT / f"{existing_id}.json").write_text(
                json.dumps(prior, indent=2), encoding="utf-8")
            return (f"Part appended — the revision now stands at {prior['words']} "
                    "words. Send the next part if the chapter is not finished, "
                    "otherwise tell the author it is ready to review.")

    if len(text) < PROPOSAL_MIN_CHARS:
        return (f"ERROR: that is only {len(text)} characters — not a chapter. Send "
                f"the COMPLETE revision (at least {PROPOSAL_MIN_CHARS} characters) in "
                "markdown, including its `# Title` line. Nothing was handed over.")

    current = chapter.read_text(encoding="utf-8")
    if " ".join(text.split()) == " ".join(current.split()):
        return ("ERROR: that is identical to the chapter as it stands, so there is "
                "nothing for the author to review.")

    now = datetime.now(timezone.utc)
    # Microseconds, deliberately: two revisions in the same second must not share an
    # id, or the second silently overwrites the first.
    pid = f"{ctx.book_dir.name}-{ctx.cid}-{now.strftime('%Y%m%dt%H%M%S%f')}"
    meta = {
        "id": pid,
        "series": ctx.series_dir.name,
        "book": ctx.book_dir.name,
        "chapter": ctx.cid,
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "content": text,
        "words": ar_mod._count_words(text),
        "base_revision": ar_mod._read_revision_marker(chapter),
    }
    _PROPOSAL_ROOT.mkdir(parents=True, exist_ok=True)
    (_PROPOSAL_ROOT / f"{pid}.json").write_text(json.dumps(meta, indent=2),
                                                encoding="utf-8")
    _prune_proposals(ctx.book_dir.name, ctx.cid)
    if out is not None:
        out["proposal_id"] = pid
    return ("Handed to the author for approval — NOT saved. They are being shown a "
            "diff of your revision against the current chapter. Do NOT paste the "
            "chapter into the chat: reply in one or two sentences telling them to "
            "review the diff and Accept.")


def _run_tool(ctx: _ToolCtx, name: str, args: dict, out: dict | None = None) -> str:
    args = args or {}
    if args.get("__malformed"):
        # Truncated tool arguments: say so plainly instead of reporting an empty
        # handover, or the model retries the same doomed call (it did, five times).
        return ("ERROR: your tool arguments arrived as invalid JSON — they were cut off "
                "before the end, which happens when a long single response runs out of "
                "output room. Nothing was handed over. If the revision is long, send it "
                "in PARTS: call this tool once per part, in order, and each call appends "
                "to the same revision.")
    if name == "list_story_files":
        return _list_story_files(ctx)
    if name == "read_story_file":
        return _read_story_file(ctx, str(args.get("path", "")))
    if name == "search_story":
        return _search_story(ctx, str(args.get("query", "")))
    if name == "propose_chapter_rewrite":
        return _propose_rewrite(ctx, str(args.get("content", "")), out)
    return f"ERROR: unknown tool {name}"


_TOOLS = [
    {"type": "function", "function": {
        "name": "list_story_files",
        "description": "List every readable story file for the current book (chapters, bible, notes) plus the series root.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }},
    {"type": "function", "function": {
        "name": "read_story_file",
        "description": "Read one story file by its exact path as returned by list_story_files.",
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
        "name": "propose_chapter_rewrite",
        "description": (
            "Hand the author a COMPLETE revised version of the chapter for approval. "
            "Use this whenever they ask you to write, rewrite, fix, tighten, "
            "restructure or clean up the whole chapter. It is NOT saved and you "
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
    #  * it would offer to fix a chapter without producing the prose, expecting a
    #    write tool it does not have.
    "If you need to read something, CALL the tool in the same turn you decide to: "
    "never end a reply with a statement of intent ('I'll re-open ch-01', 'let me "
    "read that file') instead of calling it, because that leaves the author with "
    "nothing to act on. Your tools are read-only — you cannot write or save any "
    "file. So when the author asks you to write, fix, tighten or rewrite "
    "anything, put the actual prose in your reply, ready to apply, and state "
    "plainly that it is a proposal for them to accept. Never answer a writing "
    "request with a plan to do it later. "
    "When you have what you need, answer the author directly and concisely."
)


async def _stream_turn(payload: dict, holder: dict) -> AsyncIterator[str]:
    """Stream one assistant turn. Yields visible text; collects any tool calls
    into holder['tool_calls']."""
    holder["tool_calls"] = []
    filt = ThinkStreamFilter()
    async for event in up_mod.stream_events({**payload, "stream": True}, _client):
        for tc in event.get("tool_calls") or []:
            holder["tool_calls"].append(tc)
        visible = filt.feed(event.get("content") or "")
        if visible:
            yield visible
    tail = filt.finish()
    if tail:
        yield tail


# --- public: chat ---------------------------------------------------------

CHIP_PROMPTS: dict[str, str] = {
    "rewrite": "Rewrite the user's selected passage in proper novel English. Reply with ONLY the rewrite — no preamble, no explanation.",
    "continue": "Continue the scene from where it left off, matching the established voice and cadence. Write 1–3 paragraphs.",
    "scene": "Write a new scene that follows naturally from the current chapter. Include a setting, characters from the bible if relevant, and a hook at the end.",
    "canon": "Check the user's claim against the canon (the chapter text + bible). Reply with: VERIFIED / CONTRADICTS / UNCLEAR, then one short sentence explaining.",
}


async def chat(
    messages: list[dict],
    chapter_id: str | None = None,
    chip: str | None = None,
) -> AsyncIterator:
    """Stream an agentic chat reply from the Muse.

    `messages` is the full OpenAI-style thread (last item is the user turn).
    When `chapter_id` resolves, the model is given tools to fetch the story on
    demand — we hand it the file index + style digest, NOT the chapter itself.
    `chip` (rewrite/continue/scene/canon) rides along as a system hint.
    """
    ctx = _tool_ctx(chapter_id)
    sys_parts: list[dict] = [{"role": "system", "content": AGENT_SYSTEM}]
    if chip and chip in CHIP_PROMPTS:
        sys_parts.append({"role": "system", "content": CHIP_PROMPTS[chip]})
    if ctx is not None:
        index = _list_story_files(ctx)
        if index and index != "(no files)":
            sys_parts.append({"role": "system", "content": "FILES IN THIS STORY:\n" + index})
        digest = await _load_style_summary(ctx.book_dir.name, ctx.book_dir)
        if digest:
            sys_parts.append({"role": "system", "content": "## STORY STYLE (keep this voice)\n\n" + digest})

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
    for _round in range(MUSE_MAX_TOOL_ROUNDS):
        holder: dict = {}
        async for delta in _stream_turn(payload, holder):
            full_text_parts.append(delta)
            yield delta
        calls = holder.get("tool_calls") or []
        if not calls or ctx is None:
            hit_limit = False
            break
        hit_limit = True
        # Echo the assistant's tool-call turn, then answer each call.
        payload["messages"].append({"role": "assistant", "content": "", "tool_calls": calls})
        # Shared by every tool call in THIS turn, so a long revision can arrive in
        # parts: the second call appends to the proposal the first one parked.
        turn: dict = {}
        announced: set = set()
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
            else:
                label = args.get("path") or args.get("query") or name
                yield Status(f"reading {label}…")
            result = _run_tool(ctx, name, args, turn)
            payload["messages"].append({"role": "tool", "tool_name": name, "content": result})
            pid = turn.get("proposal_id")
            if pid and pid not in announced:
                announced.add(pid)
                # The client turns this marker into the "review the diff" affordance.
                yield Proposal(pid)

    if hit_limit:
        # Ran out of rounds mid-fetch: force a final answer with no tools.
        payload.pop("tools", None)
        holder = {}
        async for delta in _stream_turn(payload, holder):
            full_text_parts.append(delta)
            yield delta

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
) -> AsyncIterator[str]:
    """Stream a single rewrite proposal for `text` in the chosen `style`."""
    sys_parts: list[dict] = [{"role": "system", "content": STYLE_PROMPTS.get(style, STYLE_PROMPTS["novel"])}]
    if chapter_id:
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
    async for delta in _post_chat(payload):
        full_text_parts.append(delta)
        yield delta
    if chapter_id:
        _persist_thread(chapter_id, [{"role": "user", "content": text}], "".join(full_text_parts))


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
#   report → stream a markdown audit of contradictions / drift (read-only)
#   bible  → stream a proposed rewrite of one bible file (approval-gated)

SWEEP_REPORT_PROMPT = (
    "You are a continuity editor for a novel-in-progress. Read the whole "
    "manuscript and its story bible below, then write a concise markdown "
    "report covering: (1) canon contradictions, (2) timeline errors, "
    "(3) character inconsistencies (names, traits, voice), (4) open questions "
    "worth resolving. Cite the chapter or bible entry where relevant. Report "
    "only real issues; if a section is clean, say so in one line."
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
        parts.append(f.read_text(encoding="utf-8").strip())
    bd = bdir / "bible"
    for f in ar_mod._iter_bible_files(bd):  # type: ignore[attr-defined]
        rel = f.relative_to(bd).as_posix()
        parts.append(f"### BIBLE: {rel}\n\n{f.read_text(encoding='utf-8').strip()}")
    block = "\n\n---\n\n".join(parts)
    if len(block) > _SWEEP_CHAR_CAP:
        block = block[:_SWEEP_CHAR_CAP] + "\n\n[…truncated…]"
    return block


async def sweep_report(series: str, book_id: str) -> AsyncIterator[str]:
    """Stream a whole-book continuity audit (read-only)."""
    bdir = _resolve_bdir(series, book_id)
    if bdir is None:
        yield "Book not found."
        return
    context = _load_full_book_context(bdir) or "(this book has no chapters yet)"
    payload = {
        "model": MUSE_REWRITE_MODEL,
        "messages": [
            {"role": "system", "content": SWEEP_REPORT_PROMPT},
            {"role": "user", "content": context},
        ],
        "options": {"num_predict": MUSE_NUM_PREDICT, "temperature": 0.3},
    }
    async for delta in _post_chat(payload):
        yield delta


async def sweep_bible(series: str, book_id: str, bible_name: str) -> AsyncIterator[str]:
    """Stream a proposed rewrite of one bible file (approval-gated).

    `bible_name` may be nested (`characters/kael.md`); the shared guard is the
    same one the PUT route uses, so sweep and save accept exactly the same
    paths and nothing outside bible/*.md."""
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
    async for delta in _post_chat(payload):
        yield delta

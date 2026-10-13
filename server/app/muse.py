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
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import httpx

from . import archive as ar_mod
from . import db
from .config import (
    ARCHIVE_ROOT,
    MUSE_AGENT_MODEL,
    MUSE_CHAT_MODEL,
    MUSE_FALLBACK_MODEL,
    MUSE_MAX_TOOL_ROUNDS,
    MUSE_MODEL,
    MUSE_NUM_PREDICT,
    MUSE_REWRITE_MODEL,
    MUSE_STYLE_PROSE_CHAPTERS,
    MUSE_UPSTREAM_TIMEOUT,
    MUSECONTEXT_MAX_TOKENS,
    OLLAMA_BASE,
)

# Module-level client — patchable from tests.
_client = httpx.AsyncClient(timeout=MUSE_UPSTREAM_TIMEOUT)

# Muse-side data lives inside the archive under `.katha/muse/`. Already
# git-ignored because archive/ is git-ignored.
_MUSE_ROOT = ARCHIVE_ROOT / ".katha" / "muse"


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


# --- upstream call --------------------------------------------------------

async def _post_chat(payload: dict) -> AsyncIterator[str]:
    """POST to Ollama /api/chat with stream=True; yield visible-only deltas."""
    payload = {**payload, "stream": True}
    url = f"{OLLAMA_BASE.rstrip('/')}/api/chat"
    async with _client.stream("POST", url, json=payload) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = obj.get("message", {}).get("content", "")
            visible = strip_think(content)
            if visible:
                yield visible


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


class _ToolCtx:
    __slots__ = ("series_dir", "book_dir")

    def __init__(self, series_dir: Path, book_dir: Path):
        self.series_dir = series_dir
        self.book_dir = book_dir


def _tool_ctx(chapter_id: str | None) -> _ToolCtx | None:
    parsed = _parse_chapter_id(chapter_id) if chapter_id else None
    if not parsed:
        return None
    series_slug, book_slug, _cid = parsed
    bdir = _resolve_bdir(series_slug, book_slug)
    if bdir is None:
        return None
    return _ToolCtx(bdir.parent, bdir)


_SNAPSHOT_RE = re.compile(r"ch-\d{2}\.\d+\.md")


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
    cd = ctx.book_dir / "chapters"
    if cd.is_dir():
        for f in sorted(cd.glob("ch-*.md")):
            if _SNAPSHOT_RE.fullmatch(f.name):
                continue
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
    try:
        hits = [h for h in db.search(q, limit=12) if h.get("book_id") == ctx.book_dir.name]
    except Exception:
        return "(no results)"
    if not hits:
        return "(no results)"
    return "\n".join(
        f"{h.get('kind')} {h.get('doc_id')} — {h.get('title')}: {h.get('snippet', '')}"
        for h in hits[:6]
    )


def _run_tool(ctx: _ToolCtx, name: str, args: dict) -> str:
    args = args or {}
    if name == "list_story_files":
        return _list_story_files(ctx)
    if name == "read_story_file":
        return _read_story_file(ctx, str(args.get("path", "")))
    if name == "search_story":
        return _search_story(ctx, str(args.get("query", "")))
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
]

AGENT_SYSTEM = (
    "You are the Muse, a story-writing companion working inside the author's "
    "story archive. Use the provided tools to read the story files (chapters, "
    "bible, notes) whenever you need detail — never invent plot, characters, or "
    "facts you have not read. Discuss only this story. When you have what you "
    "need, answer the author directly and concisely."
)


async def _stream_turn(payload: dict, holder: dict) -> AsyncIterator[str]:
    """Stream one assistant turn. Yields visible text; collects any tool calls
    into holder['tool_calls']."""
    payload = {**payload, "stream": True}
    holder["tool_calls"] = []
    url = f"{OLLAMA_BASE.rstrip('/')}/api/chat"
    async with _client.stream("POST", url, json=payload) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = obj.get("message", {}) or {}
            for tc in msg.get("tool_calls") or []:
                holder["tool_calls"].append(tc)
            visible = strip_think(msg.get("content", "") or "")
            if visible:
                yield visible


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
        "options": {"num_predict": MUSE_NUM_PREDICT, "temperature": 0.8},
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
        for tc in calls:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            args = args or {}
            label = args.get("path") or args.get("query") or name
            yield Status(f"reading {label}…")
            result = _run_tool(ctx, name, args)
            payload["messages"].append({"role": "tool", "tool_name": name, "content": result})

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
    """Return the configured models + upstream base (for the UI)."""
    return {
        "default_model": MUSE_MODEL,
        "chat_model": MUSE_CHAT_MODEL,
        "agent_model": MUSE_AGENT_MODEL,
        "rewrite_model": MUSE_REWRITE_MODEL,
        "fallback_model": MUSE_FALLBACK_MODEL,
        "ollama_base": OLLAMA_BASE,
    }


# --- canon context (D18) --------------------------------------------------

def _resolve_bdir(series_slug: str, book_slug: str) -> Path | None:
    """Resolve a series+book slug to a book dir, matching by title if needed
    (same fallback as main.py:_resolve_book_path). None if not found."""
    sd = ARCHIVE_ROOT / series_slug
    if not sd.is_dir():
        return None
    bdir = sd / book_slug
    if bdir.is_dir():
        return bdir
    for b in sorted(sd.iterdir()):
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

    # Bible hits — rank against the user prompt (or the chapter text).
    query = (user_prompt or chapter_text)[:500]
    try:
        bible_hits = db.search(query, limit=4) if query.strip() else []
    except Exception:
        bible_hits = []
    bible_block = ""
    if bible_hits:
        blocks = []
        for h in bible_hits:
            if h.get("kind") != "bible":
                continue
            blocks.append(f"### {h.get('title') or h.get('doc_id')}\n{h.get('snippet', '')}")
        if blocks:
            bible_block = "## CANON (relevant bible entries)\n\n" + "\n\n".join(blocks)

    parts: list[str] = []
    if style_digest:
        parts.append("## STORY STYLE (the voice you've established)\n\n" + style_digest)
    parts.append("## CURRENT CHAPTER (what you're rewriting inside)\n\n" + chapter_text.strip())
    if bible_block:
        parts.append(bible_block)

    block = "\n\n---\n\n".join(parts)
    # Cap at ~6000 tokens = ~24000 chars. Truncate the middle if too long.
    char_cap = MUSECONTEXT_MAX_TOKENS * 4
    if len(block) > char_cap:
        # Keep the chapter (centerpiece) intact, trim style + bible.
        head = block.split("## CURRENT CHAPTER")[0]
        tail_idx = block.find("\n\n---\n\n", block.find("## CURRENT CHAPTER"))
        tail = block[tail_idx:] if tail_idx > -1 else ""
        chapter = chapter_text.strip()
        keep_chap = chapter[:char_cap - len(head) - len(tail) - 200]
        block = head + "## CURRENT CHAPTER\n\n" + keep_chap + "\n\n[…truncated…]\n\n" + tail
    return block


# --- thread persistence (D19) --------------------------------------------

def _thread_path(chapter_id: str) -> Path | None:
    parsed = _parse_chapter_id(chapter_id)
    if not parsed:
        return None
    _, _, cid = parsed
    return _MUSE_ROOT / f"{cid}.md"


def _persist_thread(chapter_id: str, user_messages: list[dict], assistant_text: str) -> None:
    """Append a Muse exchange to `archive/.katha/muse/<chapter>.md`.

    Best-effort — failures here MUST NOT break the stream. We swallow errors
    and log them; the user already has their reply.
    """
    try:
        path = _thread_path(chapter_id)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n## {ts}\n\n")
            for m in user_messages:
                f.write(f"**{m.get('role', 'user').upper()}**: {m.get('content', '')}\n\n")
            f.write(f"**ASSISTANT**: {assistant_text}\n\n---\n")
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
    chap_files = sorted(chapters_dir.glob("ch-*.md"))
    chap_files = [p for p in chap_files if re.fullmatch(r"ch-\d{2}\.md", p.name)]
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
        url = f"{OLLAMA_BASE.rstrip('/')}/api/chat"
        payload = {
            "model": MUSE_REWRITE_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_predict": 400, "temperature": 0.4},
        }
        # Async on purpose: this runs inside streaming generators. A sync
        # client here froze the whole event loop for up to the full timeout.
        r = await _client.post(url, json=payload)
        r.raise_for_status()
        obj = r.json()
        digest = strip_think(obj.get("message", {}).get("content", "")).strip()
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
    """Return the persisted thread for `chapter_id` (empty if none)."""
    path = _thread_path(chapter_id)
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


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
    cd = bdir / "chapters"
    if cd.is_dir():
        for f in sorted(cd.glob("ch-*.md")):
            if not re.fullmatch(r"ch-\d{2}\.md", f.name):
                continue
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
    """Stream a proposed rewrite of one bible file (approval-gated)."""
    bdir = _resolve_bdir(series, book_id)
    if bdir is None:
        yield "Book not found."
        return
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.md", bible_name or ""):
        yield "Invalid bible file name."
        return
    target = bdir / "bible" / bible_name
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

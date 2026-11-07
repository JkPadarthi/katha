"""Katha Archive API — FastAPI entry point (2.0.0)."""

from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import archive as ar
from . import db
from . import epub
from . import stats
from .config import ARCHIVE_ROOT, CORS_ORIGINS, DAILY_GOAL, VERSION, WEB_DIR
from .schemas import (
    BibleOut,
    BibleUpdate,
    BookCreate,
    BooksTreeOut,
    ChapterCreate,
    ChapterListOut,
    ChapterMeta,
    ChapterOut,
    ChapterUpdate,
    HealthOut,
    MuseChatRequest,
    MuseRewriteRequest,
    MuseSweepRequest,
    NoteOut,
    NotesOut,
    NotesUpdate,
    RevisionContentOut,
    RevisionOut,
    SearchHit,
    SearchOut,
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Migrate any legacy archive layout (e.g. a flat characters.md), then
    rebuild the search index from disk."""
    # A fresh checkout has no archive/ (it is gitignored) — create it so the
    # app boots even before seed.py has run.
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    ar.migrate_archive()
    reindex_search()
    yield


app = FastAPI(title="Katha Archive", version=VERSION, lifespan=lifespan)

# Browser origins allowed to call the API (KATHA_CORS_ORIGINS env). Never
# wildcard: with no auth, * lets any visited webpage rewrite the archive.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def reindex_search():
    """Rebuild the FTS index from the md archive (source of truth)."""
    db.clear_search_index()
    for kind, series, book_id, doc_id, title, body in ar.iter_searchable_docs():
        db.index_doc(kind, series, book_id, doc_id, title, body)


# ---------- helpers ----------

def _resolve_book_path(series: str, book_id: str) -> Path:
    """Match a series+book_id to a real dir; book_id may be a slug, id, or title."""
    # Traversal guard: the series becomes a path segment — only slugs pass.
    if not ar.is_slug(series):
        raise HTTPException(404, "series not found")
    sd = ARCHIVE_ROOT / series
    if not sd.is_dir():
        raise HTTPException(404, "series not found")
    # Fast path: a slug that names the directory. Any non-slug input (a real
    # title like "The First Flame") is matched below by iterating entries —
    # never joined onto the path.
    if ar.is_slug(book_id):
        bdir = sd / book_id
        if bdir.is_dir():
            return bdir
    for b in sorted(sd.iterdir()):
        if not b.is_dir() or b.name.startswith("."):
            continue
        meta = ar._read_book_json(b)
        if (b.name == book_id or meta.get("id") == book_id
                or meta.get("title") == book_id):
            return b
    raise HTTPException(404, "book not found")


@app.get("/api/health", response_model=HealthOut, tags=["meta"])
def health():
    return HealthOut(status="ok", version=VERSION, db_ok=db.health())


@app.get("/api/books", response_model=list[BooksTreeOut], tags=["books"])
def books_tree():
    return ar.list_books()


@app.post("/api/books", response_model=dict, status_code=201, tags=["books"])
def create_book(payload: BookCreate):
    meta = ar.ensure_book(payload.series, payload.title)
    db.upsert_book(meta["id"], meta["series"], meta["title"])
    # Every book starts with the canonical bible shape: one file per main
    # character under characters/, one shared side-characters file, places,
    # and a timeline.
    bdir = ar.book_dir(payload.series, payload.title)
    ar.scaffold_bible(bdir)
    for name, content in ar.read_bible(bdir).items():
        db.index_doc("bible", meta["series"], bdir.name, name, Path(name).stem, content)
    # Series travels as its slug here — same form every other route expects.
    return _book_detail(meta["id"], meta["series"])


def _book_detail(book_id: str, series: str) -> dict:
    bdir = _resolve_book_path(series, book_id)
    chapters = ar.list_chapters(bdir)
    return {
        "id": book_id,
        "series": series,
        "title": _book_title(bdir),
        "chapter_count": len(chapters),
        "chapters": chapters,
    }


def _book_title(bdir: Path) -> str:
    return ar._read_book_json(bdir).get("title", bdir.name)


@app.get("/api/books/{series}/{book_id}/chapters", response_model=ChapterListOut,
         tags=["chapters"])
def list_chapters(series: str, book_id: str):
    bdir = _resolve_book_path(series, book_id)
    chapters = ar.list_chapters(bdir)
    metas = [ChapterMeta(**c) for c in chapters]
    for c in chapters:
        db.upsert_chapter({**c, "book_id": bdir.name})
    return ChapterListOut(book_id=bdir.name, chapters=metas)


@app.post("/api/books/{series}/{book_id}/chapters", response_model=ChapterOut,
          status_code=201, tags=["chapters"])
def new_chapter(series: str, book_id: str, payload: ChapterCreate):
    bdir = _resolve_book_path(series, book_id)
    meta = ar.create_chapter(bdir, payload.title, payload.content)
    db.upsert_chapter({**meta, "book_id": bdir.name})
    db.index_doc("chapter", series, bdir.name, meta["id"], payload.title, payload.content)
    chapter = ar.get_chapter(bdir, meta["id"])
    assert chapter is not None
    return ChapterOut(**ar._chapter_meta(bdir, meta["id"], payload.title, chapter),
                      content=payload.content)


@app.get("/api/books/{series}/{book_id}/chapters/{chapter_id}",
         response_model=ChapterOut, tags=["chapters"])
def read_chapter(series: str, book_id: str, chapter_id: str):
    bdir = _resolve_book_path(series, book_id)
    chapter = ar.get_chapter(bdir, chapter_id)
    if not chapter:
        raise HTTPException(404, "chapter not found")
    return ChapterOut(
        **ar._chapter_meta(bdir, chapter.stem, "", chapter),
        content=chapter.read_text(encoding="utf-8"),
    )


@app.put("/api/books/{series}/{book_id}/chapters/{chapter_id}",
         response_model=ChapterOut, tags=["chapters"])
def save_chapter(series: str, book_id: str, chapter_id: str, payload: ChapterUpdate):
    """Autosave: write md (source of truth) + snapshot a revision (D9)."""
    bdir = _resolve_book_path(series, book_id)
    chapter = ar.get_chapter(bdir, chapter_id)
    if not chapter:
        raise HTTPException(404, "chapter not found")
    existing_title = ar._chapter_title(chapter)
    title = (payload.title or "").strip() or existing_title
    prev_words = ar.body_words(chapter)
    new_text = f"# {title}\n\n{payload.content}".rstrip() + "\n"
    chapter.write_text(new_text, encoding="utf-8")
    rev = ar.write_revision(chapter, payload.content, title)
    words = ar._count_words(payload.content)
    stats.append_write(ar._mtime(chapter), series, bdir.name, chapter.stem,
                       words, words - prev_words)
    db.record_revision(bdir.name, chapter.stem, rev, ar._mtime(chapter), words)
    db.upsert_chapter({
        "id": chapter.stem,
        "book_id": bdir.name,
        "title": title,
        "path": chapter.relative_to(ARCHIVE_ROOT).as_posix(),
        "words": words,
        "revision": rev,
    })
    db.index_doc("chapter", series, bdir.name, chapter.stem, title, payload.content)
    return ChapterOut(
        id=chapter.stem, book_id=bdir.name, title=title,
        words=words, path=chapter.relative_to(ARCHIVE_ROOT).as_posix(),
        revision=rev, content=payload.content,
    )


@app.get("/api/books/{series}/{book_id}/chapters/{chapter_id}/revisions",
         response_model=list[RevisionOut], tags=["revisions"])
def list_revisions(series: str, book_id: str, chapter_id: str):
    bdir = _resolve_book_path(series, book_id)
    revs = ar.list_revisions(bdir, chapter_id)
    if revs is None:
        raise HTTPException(404, "chapter not found")
    return revs


@app.get("/api/books/{series}/{book_id}/chapters/{chapter_id}/revisions/{number}",
         response_model=RevisionContentOut, tags=["revisions"])
def read_revision(series: str, book_id: str, chapter_id: str, number: int):
    bdir = _resolve_book_path(series, book_id)
    rev = ar.get_revision(bdir, chapter_id, number)
    if rev is None:
        raise HTTPException(404, "revision not found")
    return rev


# ---------- reading-mode notes (1.0) --------------------------------------

def _notes_out(bdir: Path, chapter_id: str) -> NotesOut:
    notes = ar.read_notes(bdir, chapter_id) or []
    chap = ar.get_chapter(bdir, chapter_id)
    assert chap is not None
    return NotesOut(chapter_id=chap.stem, notes=[NoteOut(**n) for n in notes])


@app.get("/api/books/{series}/{book_id}/chapters/{chapter_id}/notes",
         response_model=NotesOut, tags=["notes"])
def get_notes(series: str, book_id: str, chapter_id: str):
    """Read a chapter's annotations (md sidecar; [] when none exist)."""
    bdir = _resolve_book_path(series, book_id)
    if ar.get_chapter(bdir, chapter_id) is None:
        raise HTTPException(404, "chapter not found")
    return _notes_out(bdir, chapter_id)


@app.put("/api/books/{series}/{book_id}/chapters/{chapter_id}/notes",
         response_model=NotesOut, tags=["notes"])
def put_notes(series: str, book_id: str, chapter_id: str, payload: NotesUpdate):
    """Replace a chapter's annotations — rewrites `ch-NN.notes.md` (md truth)."""
    bdir = _resolve_book_path(series, book_id)
    if ar.write_notes(bdir, chapter_id, [n.model_dump() for n in payload.notes]) is None:
        raise HTTPException(404, "chapter not found")
    return _notes_out(bdir, chapter_id)


@app.get("/api/books/{series}/{book_id}/bible", response_model=BibleOut,
         tags=["bible"])
def read_bible(series: str, book_id: str):
    bdir = _resolve_book_path(series, book_id)
    return BibleOut(book_id=bdir.name, files=ar.read_bible(bdir))


@app.put("/api/books/{series}/{book_id}/bible/{name:path}", response_model=BibleOut,
         tags=["bible"])
def save_bible(series: str, book_id: str, name: str, payload: BibleUpdate):
    """Write a bible file (md is the truth) and reindex it. `name` may be a
    nested path (e.g. characters/kael.md). Used by the editor + canon sweep."""
    bdir = _resolve_book_path(series, book_id)
    dest = ar.safe_bible_path(bdir, name)
    if dest is None:
        raise HTTPException(400, "invalid bible file name")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(payload.content, encoding="utf-8")
    db.index_doc("bible", series, bdir.name, name, Path(name).stem, payload.content)
    return BibleOut(book_id=bdir.name, files=ar.read_bible(bdir))


@app.post("/api/books/{series}/{book_id}/bible/scaffold", response_model=BibleOut,
          tags=["bible"])
def scaffold_bible(series: str, book_id: str):
    """Create the starter bible for an existing book (idempotent).

    characters/side-characters.md + places.md + timeline.md. Main characters
    are added one file each under characters/."""
    bdir = _resolve_book_path(series, book_id)
    ar.scaffold_bible(bdir)
    files = ar.read_bible(bdir)
    for name, content in files.items():
        db.index_doc("bible", series, bdir.name, name, Path(name).stem, content)
    return BibleOut(book_id=bdir.name, files=files)


@app.get("/api/search", response_model=SearchOut, tags=["search"])
def search(q: str = "", limit: int = 20):
    """Full-text search across chapters + bible (FTS5, 0.2.2)."""
    q = q.strip()
    if not q:
        return SearchOut(query=q, count=0, hits=[])
    hits = [SearchHit(**h) for h in db.search(q, limit)]
    return SearchOut(query=q, count=len(hits), hits=hits)


@app.post("/api/search/reindex", status_code=204, tags=["search"])
def reindex():
    """Rebuild the FTS index from the md archive (idempotent, cheap)."""
    reindex_search()


# ---------- writing rituals (1.0) -----------------------------------------

@app.get("/api/stats", tags=["stats"])
def get_stats(goal: int | None = None):
    """Writing-ritual summary: today's words, goal, streak, 14-day history."""
    return stats.summary(goal if goal and goal > 0 else DAILY_GOAL)


# ---------- delivery: EPUB export (1.0) -----------------------------------

@app.get("/api/books/{series}/{book_id}/export.epub", tags=["export"])
def export_epub(series: str, book_id: str):
    """Build and return a downloadable EPUB for the book (chapters + bible)."""
    bdir = _resolve_book_path(series, book_id)
    title = _book_title(bdir)
    data = epub.build_epub(ar._read_series_title(bdir.parent), title, bdir)
    filename = f"{ar.slugify(title)}.epub"
    return Response(
        content=data,
        media_type="application/epub+zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- Muse (0.3 Muse, D16/D17/D19) ----------------------------------

from . import muse as muse_mod  # noqa: E402  (after app init — needs config)


def _sse_escape(chunk: str) -> str:
    """Single-pass SSE escaping. Sequential .replace() calls collide when
    prose contains a literal backslash before 'n' — this maps each char
    independently so encode/decode always round-trip."""
    return "".join(
        "\\n" if ch == "\n" else ("\\\\" if ch == "\\" else ch)
        for ch in chunk
    )


async def _sse_from(async_iter) -> AsyncIterator[bytes]:
    """Wrap an async iterator of strings in SSE `data:` lines.

    Each chunk becomes one event: `data: <chunk>\\n\\n`. A `muse.Status` chunk
    becomes `data: [STATUS] <msg>` (progress, never prose). Stream ends with
    `data: [DONE]\\n\\n`; an upstream failure emits `data: [ERROR] …` first so
    the client can surface a real message instead of a truncated stream.
    """
    try:
        async for chunk in async_iter:
            if isinstance(chunk, muse_mod.Status):
                msg = " ".join(chunk.text.split())
                yield f"data: [STATUS] {_sse_escape(msg)}\n\n".encode("utf-8")
            else:
                yield f"data: {_sse_escape(chunk)}\n\n".encode("utf-8")
    except Exception as e:
        msg = " ".join(f"{type(e).__name__}: {e}".split())
        yield f"data: [ERROR] {msg}\n\n".encode("utf-8")
    yield b"data: [DONE]\n\n"


@app.get("/api/muse/models", tags=["muse"])
def muse_models():
    """Configured Muse models + Ollama base (for the UI display)."""
    return muse_mod.models_info()


@app.get("/api/muse/thread", tags=["muse"])
def muse_thread(chapter_id: str = ""):
    """The persisted chat thread for a chapter (`series/book/ch-NN`).

    Reopening a chapter restores its Muse conversation instead of the thread
    files being a write-only log."""
    return {"chapter_id": chapter_id, "messages": muse_mod.thread_messages(chapter_id)}


@app.post("/api/muse/chat", tags=["muse"])
async def muse_chat(payload: MuseChatRequest):
    """Stream a chat reply as SSE.

    Body:
        messages:    list of {role, content} — the full thread
        chapter_id:  optional, currently unused (canon context wired in 0.3.4)
        chip:        optional hint: 'rewrite' | 'continue' | 'scene' | 'canon'
    """
    gen = muse_mod.chat(
        messages=[m.model_dump() for m in payload.messages],
        chapter_id=payload.chapter_id,
        chip=payload.chip,
    )
    return StreamingResponse(
        _sse_from(gen),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/muse/rewrite", tags=["muse"])
async def muse_rewrite(payload: MuseRewriteRequest):
    """Stream a single rewrite proposal as SSE.

    Body:
        text:       the selection to rewrite
        style:      'novel' (default) | 'scene' | 'clean'
        chapter_id: optional
    """
    gen = muse_mod.rewrite(
        text=payload.text,
        style=payload.style,
        chapter_id=payload.chapter_id,
    )
    return StreamingResponse(
        _sse_from(gen),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/muse/sweep", tags=["muse"])
async def muse_sweep(payload: MuseSweepRequest):
    """Stream a canon sweep as SSE.

    Body:
        series, book_id: which book
        target:          'report' (whole-book continuity audit) |
                         'bible'  (proposed rewrite of one bible file)
        bible_name:      required when target='bible'
    """
    if payload.target == "bible":
        gen = muse_mod.sweep_bible(payload.series, payload.book_id, payload.bible_name or "")
    else:
        gen = muse_mod.sweep_report(payload.series, payload.book_id)
    return StreamingResponse(
        _sse_from(gen),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- static PWA client (same origin, one port) ---------------------

# Serve the built SPA at `/` so the app and the API share an origin — the
# service worker only installs in a secure context, and a single origin keeps
# the client's requests same-origin (no CORS, no base-URL config).
mimetypes.add_type("application/manifest+json", ".webmanifest")

if WEB_DIR.is_dir():
    _web_root = WEB_DIR.resolve()
    _assets = _web_root / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # Never shadow the API — unknown /api paths must 404, not return HTML.
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(404, "not found")
        # Serve a real file inside the built client, or fall through to the
        # shell. Resolve + containment check so `..%2f` cannot escape dist/.
        if full_path:
            try:
                candidate = (_web_root / full_path).resolve()
            except OSError:
                candidate = None
            if candidate is not None:
                try:
                    candidate.relative_to(_web_root)
                except ValueError:
                    raise HTTPException(404, "not found")
                if candidate.is_file():
                    return FileResponse(str(candidate))
        # SPA deep links fall through to the shell.
        return FileResponse(str(_web_root / "index.html"))

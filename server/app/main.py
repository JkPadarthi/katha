"""Katha Archive API — FastAPI entry point (0.3.1)."""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import archive as ar
from . import db
from .config import ARCHIVE_ROOT, VERSION
from .schemas import (
    BibleOut,
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
    RevisionContentOut,
    RevisionOut,
    SearchHit,
    SearchOut,
)

app = FastAPI(title="Katha Archive", version=VERSION)

# For dev: desktop (vite :5173) talking directly during 0.2 wiring (Tailscale in prod, D12).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    """Match a series+book_id to a real dir; book_id may be slug or title."""
    sd = ARCHIVE_ROOT / series
    if not sd.is_dir():
        raise HTTPException(404, "series not found")
    # book dirs keyed by slug
    bdir = sd / book_id
    if bdir.is_dir():
        return bdir
    for b in sorted(sd.iterdir()):
        meta = ar._read_book_json(b)
        if meta.get("id") == book_id or meta.get("title") == book_id:
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
    return _book_detail(meta["id"], payload.series)


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
    title = ar._chapter_title(chapter)
    new_text = f"# {title}\n\n{payload.content}".rstrip() + "\n"
    chapter.write_text(new_text, encoding="utf-8")
    rev = ar.write_revision(chapter, payload.content, title)
    words = ar._count_words(payload.content)
    db.record_revision(chapter.stem, rev, ar._mtime(chapter), words)
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


@app.get("/api/books/{series}/{book_id}/bible", response_model=BibleOut,
         tags=["bible"])
def read_bible(series: str, book_id: str):
    bdir = _resolve_book_path(series, book_id)
    return BibleOut(book_id=bdir.name, files=ar.read_bible(bdir))


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


# ---------- Muse (0.3 Muse, D16/D17/D19) ----------------------------------

from . import muse as muse_mod  # noqa: E402  (after app init — needs config)


async def _sse_from(async_iter) -> AsyncIterator[bytes]:
    """Wrap an async iterator of strings in SSE `data:` lines.

    Each chunk becomes one event: `data: <chunk>\n\n`. Stream ends with
    `data: [DONE]\n\n` so the client can detect EOF without a timeout.
    """
    async for chunk in async_iter:
        # SSE forbids raw newlines in `data:`. Newlines in the prose get
        # escaped to '\n' literals — the client un-escapes.
        safe = chunk.replace("\n", "\\n")
        yield f"data: {safe}\n\n".encode("utf-8")
    yield b"data: [DONE]\n\n"


@app.get("/api/muse/models", tags=["muse"])
def muse_models():
    """Configured Muse models + Ollama base (for the UI display)."""
    return muse_mod.models_info()


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

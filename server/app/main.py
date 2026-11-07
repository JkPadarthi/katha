"""Katha Archive API — FastAPI entry point (2.0.0)."""

from __future__ import annotations

import base64
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from urllib.parse import quote

from . import archive as ar
from . import auth
from . import db
from . import epub
from . import hunks as hunks_mod
from . import stats
from . import trash
from .config import (
    ARCHIVE_ROOT,
    COOKIE_NAME,
    CORS_ORIGINS,
    DAILY_GOAL,
    SESSION_SECONDS,
    VERSION,
    WEB_DIR,
)
from .schemas import (
    BibleOut,
    BibleUpdate,
    BookCreate,
    BookMetaIn,
    BooksTreeOut,
    ChapterCreate,
    ChapterListOut,
    ChapterMeta,
    ChapterOut,
    ChapterUpdate,
    CoverIn,
    HealthOut,
    LoginIn,
    MuseChatRequest,
    MuseRewriteRequest,
    MuseSweepRequest,
    NoteOut,
    ProposalAcceptIn,
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
    # Pre-2.4 Muse threads were named after the chapter alone, so different books
    # shared one conversation. Attribute each of them to its book once (2.4.1).
    adopted = muse_mod.migrate_legacy_threads()
    if any(adopted.values()):
        print(
            "muse threads: adopted {adopted}, set aside {set_aside}, kept {kept}".format(
                **{k: (v or []) for k, v in adopted.items()}
            )
        )
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


# ---------- the door (2.2, D32) ----------
# One password in front of EVERYTHING except the login page: the PWA shell, every
# /api route (including the Muse SSE streams) and the built client's assets. The
# manifest/icons/service worker stay public because a browser fetches them
# without credentials and they carry no story data; /api/health stays public
# because the container's own healthcheck calls it from inside, with no cookie —
# a 401 there would mark every deploy unhealthy and trip the CD rollback.

@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    if (not auth.enabled()
            or request.method == "OPTIONS"      # CORS preflight carries no cookie
            or auth.is_public(request.url.path)):
        return await call_next(request)
    if auth.valid_token(request.cookies.get(COOKIE_NAME, "")):
        return await call_next(request)
    # API/SSE callers get a real 401 so the client can show an error; page
    # requests are walked to the login screen with a same-origin `next`.
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "unauthorized — sign in"}, status_code=401)
    return RedirectResponse(
        f"/login?next={quote(request.url.path, safe='/')}", status_code=303
    )


@app.get("/login", include_in_schema=False)
def login_page():
    """The one public page — self-contained, because the SPA bundle (and its
    assets) are behind the lock."""
    return HTMLResponse(auth.LOGIN_HTML, headers={"Cache-Control": "no-store"})


@app.post("/api/auth/login", tags=["auth"])
def login(payload: LoginIn, request: Request, response: Response):
    """Exchange the password for a signed session cookie."""
    ip = request.client.host if request.client else "?"
    if auth.blocked(ip):
        raise HTTPException(429, "too many attempts — wait a few minutes")
    if not auth.verify(payload.password):
        auth.record_failure(ip)
        raise HTTPException(401, "that password didn't work")
    auth.clear_failures(ip)
    response.set_cookie(value=auth.issue_token(), **auth.cookie_kwargs(request))
    return {"ok": True, "session_days": SESSION_SECONDS // 86400}


@app.post("/api/auth/logout", tags=["auth"])
def logout(response: Response):
    """Drop the session. Public on purpose: logging out must never 401."""
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


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
    bdir = ar.book_dir(payload.series, payload.title)
    # 2.8: a book can be born with its author (the client prefills the field from
    # Settings, and a pen name per book must survive the round trip).
    if (payload.author or "").strip():
        meta = ar.set_book_author(bdir, payload.author)
    db.upsert_book(meta["id"], meta["series"], meta["title"])
    # Every book starts with the canonical bible shape: one file per main
    # character under characters/, one shared side-characters file, places,
    # and a timeline.
    ar.scaffold_bible(bdir)
    for name, content in ar.read_bible(bdir).items():
        db.index_doc("bible", meta["series"], bdir.name, name, Path(name).stem, content)
    # Series travels as its slug here — same form every other route expects.
    return _book_detail(meta["id"], meta["series"])


def _book_detail(book_id: str, series: str) -> dict:
    bdir = _resolve_book_path(series, book_id)
    chapters = ar.list_chapters(bdir)
    meta = ar._read_book_json(bdir)
    return {
        "id": book_id,
        "series": series,
        "title": _book_title(bdir),
        "chapter_count": len(chapters),
        "chapters": chapters,
        "author": meta.get("author", ""),
        "has_cover": ar.cover_path(bdir) is not None,
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
    try:
        meta = ar.create_chapter(bdir, payload.title, payload.content, payload.number)
    except FileExistsError as exc:
        raise HTTPException(409, f"{exc.args[0]} already exists in this book") from exc
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


def _write_chapter_text(series: str, bdir: Path, chapter: Path, title: str,
                        content: str) -> dict:
    """The one save path: md is the truth, a revision snapshot is taken (D9), and
    the index + writing stats are updated.

    Autosave and an accepted Muse proposal both come through here, deliberately — a
    revision the author accepts should look exactly like one they typed, including
    in the time machine this archive keeps for every save (2.9, D45).
    """
    prev_words = ar.body_words(chapter)
    new_text = f"# {title}\n\n{content}".rstrip() + "\n"
    chapter.write_text(new_text, encoding="utf-8")
    rev = ar.write_revision(chapter, content, title)
    words = ar._count_words(content)
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
    db.index_doc("chapter", series, bdir.name, chapter.stem, title, content)
    return {
        "id": chapter.stem,
        "book_id": bdir.name,
        "title": title,
        "words": words,
        "path": chapter.relative_to(ARCHIVE_ROOT).as_posix(),
        "revision": rev,
        "content": content,
    }


@app.put("/api/books/{series}/{book_id}/chapters/{chapter_id}",
         response_model=ChapterOut, tags=["chapters"])
def save_chapter(series: str, book_id: str, chapter_id: str, payload: ChapterUpdate):
    """Autosave: write md (source of truth) + snapshot a revision (D9)."""
    bdir = _resolve_book_path(series, book_id)
    chapter = ar.get_chapter(bdir, chapter_id)
    if not chapter:
        raise HTTPException(404, "chapter not found")
    title = (payload.title or "").strip() or ar._chapter_title(chapter)
    return ChapterOut(**_write_chapter_text(series, bdir, chapter, title,
                                            payload.content))


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


# ---------- whole-chapter proposals (2.9, D45) ----------------------------
# The Muse can read the story but never write it. When it has a full revision for
# the author, it parks it here and the app shows a diff; Accept runs the *same*
# save path as autosave, so the time machine keeps the revision either way.

@app.get("/api/muse/proposals", response_model=dict, tags=["muse"])
def list_proposals():
    """Pending revisions, newest first. Metadata only — the body is one GET away, and
    `hunk_count` is how many separate decisions are waiting (3.0, D48)."""
    out = []
    for p in muse_mod.list_proposals():
        try:
            bdir = _resolve_book_path(p["series"], p["book"])
            chapter = ar.get_chapter(bdir, p["chapter"])
            if chapter is not None:
                # The list carries metadata only — the body has to be read, or this counts
                # the hunks of a revision that isn't there (which is how it reported 1 for
                # an eleven-change revision).
                full = muse_mod.read_proposal(p["id"]) or p
                base = _proposal_base(p, bdir, chapter)
                p["hunk_count"] = len(hunks_mod.hunks(base, _proposal_full(full, chapter)))
        except Exception:      # a book on its way to the trash must not break the list
            pass
        out.append(p)
    return {"proposals": out}


@app.get("/api/muse/proposals/{proposal_id}", response_model=dict, tags=["muse"])
def read_proposal(proposal_id: str):
    """A pending revision, cut into hunks so it can be reviewed one place at a time."""
    p = muse_mod.read_proposal(proposal_id)
    if p is None:
        raise HTTPException(404, "no such proposal")
    bdir = _resolve_book_path(p["series"], p["book"])
    chapter = ar.get_chapter(bdir, p["chapter"])
    if chapter is None:
        raise HTTPException(404, "that chapter is not in this book any more")
    base = _proposal_base(p, bdir, chapter)
    p["base_content"] = base
    p["current_revision"] = ar._read_revision_marker(chapter)
    # A revision is written against the chapter the Muse *read*. If the author has saved
    # since, accepting would quietly overwrite prose the Muse never saw — so the review
    # says so, and the accept route refuses (3.0.1).
    p["stale"] = int(p.get("base_revision") or 0) != p["current_revision"]
    p["hunks"] = hunks_mod.hunks(base, _proposal_full(p, chapter))
    return p


def _proposal_base(p: dict, bdir: Path, chapter: Path) -> str:
    """The file text the revision was written against.

    If the chapter has moved on since the Muse read it, the snapshot from that moment is the
    honest base — diffing against today's file would blame the author's own later edits on
    the Muse.
    """
    rev = int(p.get("base_revision") or 0)
    current = ar._read_revision_marker(chapter)
    if rev and rev < current:
        snap = ar.get_revision(bdir, p["chapter"], rev)
        if snap and snap.get("content"):
            return snap["content"]
    return chapter.read_text(encoding="utf-8")


def _proposal_full(p: dict, chapter: Path) -> str:
    """The Muse's revision, in the same shape as the chapter file.

    A revision that arrives without a heading is not "a chapter with the title deleted" —
    it is a revision of the prose under the author's existing title. Restoring the heading
    before diffing means the author is never asked to decide a phantom 'deleted the heading'
    hunk, while a revision that *does* rename the chapter shows up as a real one (3.0, D48).
    """
    text = p.get("content") or ""
    if text.lstrip().startswith("# "):
        return text
    return f"# {ar._chapter_title(chapter)}\n\n{text}"


@app.post("/api/muse/proposals/{proposal_id}/accept", response_model=ChapterOut,
          tags=["muse"])
def accept_proposal(proposal_id: str, body: ProposalAcceptIn | None = None):
    """Apply a proposed revision — all of it, or just the hunks the author ticked.

    Either way this is a normal save (revision snapshot and all), so a partial accept is as
    undoable as any edit. Hunks left unticked stay pending: the proposal keeps its content
    and is re-pointed at the revision that was just written.
    """
    p = muse_mod.read_proposal(proposal_id)
    if p is None:
        raise HTTPException(404, "no such proposal")
    bdir = _resolve_book_path(p["series"], p["book"])
    chapter = ar.get_chapter(bdir, p["chapter"])
    if chapter is None:
        raise HTTPException(404, "that chapter is not in this book any more")
    current_rev = ar._read_revision_marker(chapter)
    base_rev = int(p.get("base_revision") or 0)
    if base_rev != current_rev:
        # Not a conflict to be clever about: the Muse read one text, the author has since
        # saved another, and merging them silently is how a writer loses a paragraph. The
        # author's newer prose wins by default, and the Muse can revise it properly.
        raise HTTPException(409, (
            "the chapter has been saved since this revision was written "
            f"(this revision is based on revision {base_rev}, the chapter is at "
            f"{current_rev}) — ask the Muse to revise the current chapter, or discard "
            "this revision"
        ))
    base = _proposal_base(p, bdir, chapter)
    proposal_text = _proposal_full(p, chapter)
    groups = hunks_mod.hunks(base, proposal_text)
    total = len(groups)
    wanted = None if body is None or body.hunks is None else body.hunks
    try:
        taken = hunks_mod.validate_ids(groups, wanted)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if not taken:
        # Rejecting every hunk is a legitimate answer, and it must not burn a revision.
        return ChapterOut(
            **ar._chapter_meta(bdir, chapter.stem, "", chapter),
            content=chapter.read_text(encoding="utf-8"),
        )

    applied = hunks_mod.merge(base, proposal_text, taken)
    # The Muse is asked for the whole chapter *with* its heading; the save path writes its
    # own heading, so take the one it sent and drop the duplicate.
    text, title = muse_mod.split_heading(applied, ar._chapter_title(chapter))
    out = _write_chapter_text(p["series"], bdir, chapter, title, text)
    if len(taken) >= total:
        muse_mod.delete_proposal(proposal_id)
    else:
        muse_mod.rebase_proposal(proposal_id, out["revision"])
    return ChapterOut(**out)


@app.delete("/api/muse/proposals/{proposal_id}", response_model=dict, tags=["muse"])
def discard_proposal(proposal_id: str):
    """Throw a revision away. The chapter is untouched — it never was."""
    removed = muse_mod.delete_proposal(proposal_id)
    if not removed:
        raise HTTPException(404, "no such proposal")
    return {"ok": True, "removed": proposal_id}


# ---------- the book's face: author + cover (2.8, D43) ---------------------

def _book_face(bdir: Path) -> dict:
    """The two things a shelf knows about a book, in one shape for the client."""
    meta = ar._read_book_json(bdir)
    return {
        "id": bdir.name,
        "title": meta.get("title", bdir.name),
        "author": meta.get("author", ""),
        "has_cover": ar.cover_path(bdir) is not None,
        "cover_w": meta.get("cover_w"),
        "cover_h": meta.get("cover_h"),
    }


@app.put("/api/books/{series}/{book_id}/meta", response_model=dict, tags=["books"])
def update_book_meta(series: str, book_id: str, payload: BookMetaIn):
    """Set the author (empty string clears it). The title is not editable here —
    it is the directory name, so renaming is a move, not a field write."""
    bdir = _resolve_book_path(series, book_id)
    ar.set_book_author(bdir, payload.author)
    return _book_face(bdir)


@app.get("/api/books/{series}/{book_id}/cover", tags=["books"])
def get_cover(series: str, book_id: str):
    """The stored cover, for the UI preview. Behind the lock like everything else;
    the EPUB embeds its own copy, so no reader ever needs this route."""
    bdir = _resolve_book_path(series, book_id)
    p = ar.cover_path(bdir)
    if p is None:
        raise HTTPException(404, "this book has no cover")
    media = "image/png" if p.suffix.lower() == ".png" else (
        "image/webp" if p.suffix.lower() == ".webp" else "image/jpeg")
    return Response(content=p.read_bytes(), media_type=media,
                    headers={"Cache-Control": "no-cache"})


@app.put("/api/books/{series}/{book_id}/cover", response_model=dict, tags=["books"])
def put_cover(series: str, book_id: str, payload: CoverIn):
    """Store a cover. The bytes are base64 in a JSON body (no multipart dep) and
    are sniffed + normalised — see `archive.normalise_cover`."""
    bdir = _resolve_book_path(series, book_id)
    try:
        raw = base64.b64decode(payload.data, validate=True)
    except Exception:  # noqa: BLE001 - every decode failure is the same 400
        raise HTTPException(400, "cover data must be valid base64")
    try:
        info = ar.write_cover(bdir, raw)
    except ValueError as exc:
        # The message is written for the author to read, not for a log.
        raise HTTPException(400, str(exc))
    return {**_book_face(bdir), **info}


@app.delete("/api/books/{series}/{book_id}/cover", response_model=dict, tags=["books"])
def remove_cover(series: str, book_id: str):
    bdir = _resolve_book_path(series, book_id)
    removed = ar.delete_cover(bdir)
    return {**_book_face(bdir), "removed": removed}


# ---------- delivery: EPUB export (1.0) -----------------------------------

@app.get("/api/books/{series}/{book_id}/export.epub", tags=["export"])
def export_epub(series: str, book_id: str):
    """Build and return a downloadable EPUB for the book (chapters + bible).

    2.8: the book's author rides in the metadata, and its cover — when one has
    been uploaded — becomes a real cover page. The cover lives *inside* the book
    directory, so no extra lookup is needed here.
    """
    bdir = _resolve_book_path(series, book_id)
    title = _book_title(bdir)
    cover_file = ar.cover_path(bdir)
    data = epub.build_epub(
        ar._read_series_title(bdir.parent), title, bdir,
        author=ar._read_book_json(bdir).get("author", ""),
        cover=cover_file.read_bytes() if cover_file else None,
    )
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
            elif isinstance(chunk, muse_mod.Proposal):
                # A whole-chapter revision is waiting for the author (2.9, D45).
                # The id, not the chapter: the client fetches it to show the diff.
                yield f"data: [PROPOSAL] {_sse_escape(chunk.proposal_id)}\n\n".encode("utf-8")
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


# ---------- trash: delete + revive (2.3, D33) ------------------------------
# Deletion is a MOVE, never an unlink: the files land under
# archive/.katha/trash/<stamp>-<kind>-<slug>/ with a manifest, and restore puts
# every one of them back where it came from. The app forgets (index rows + search
# docs dropped) so the rail never shows a ghost — but the prose survives.

def _reindex_book_meta(bdir: Path) -> None:
    """Re-assert a book's index rows from disk (after a restore)."""
    meta = ar._read_book_json(bdir)
    db.upsert_book(bdir.name, bdir.parent.name, meta.get("title") or bdir.name)
    for c in ar.list_chapters(bdir):
        db.upsert_chapter({
            "id": c["id"], "book_id": bdir.name, "title": c.get("title") or c["id"],
            "path": c.get("path") or "", "words": c.get("words") or 0,
            "revision": c.get("revision") or 0,
        })


def _chapter_impact(bdir: Path, chapter_id: str) -> dict:
    """Exactly what a chapter delete would take — the confirm dialog's numbers."""
    paths = trash.chapter_paths(bdir, chapter_id)
    files, size = trash.size_of(paths)
    chapter = ar.get_chapter(bdir, chapter_id)
    return {
        "chapter_id": chapter_id,
        "title": ar._chapter_title(chapter) if chapter else chapter_id,
        "words": ar.body_words(chapter) if chapter else 0,
        "revisions": len(ar.list_revisions(bdir, chapter_id)),
        "notes": len(ar.read_notes(bdir, chapter_id) or []),
        "threads": trash.count_threads(bdir.name, chapter_id),
        "files": files,
        "bytes": size,
    }


def _book_impact(bdir: Path) -> dict:
    """Everything a book delete would take, chapter by chapter."""
    chapters = ar.list_chapters(bdir)
    files, size = trash.size_of([bdir])
    try:
        bible_files = len(list(ar._iter_bible_files(bdir / "bible")))
    except Exception:
        bible_files = 0
    return {
        "book_id": bdir.name,
        "title": ar._read_book_json(bdir).get("title") or bdir.name,
        "chapters": len(chapters),
        "revisions": sum(len(ar.list_revisions(bdir, c["id"])) for c in chapters),
        "notes": sum(len(ar.read_notes(bdir, c["id"]) or []) for c in chapters),
        "threads": sum(trash.count_threads(bdir.name, c["id"]) for c in chapters),
        "words": sum(int(c.get("words") or 0) for c in chapters),
        "bible_files": bible_files,
        "files": files,
        "bytes": size,
    }


def _bible_impact(bdir: Path, name: str) -> dict:
    """What a bible delete would take: exactly one file.

    `ar.safe_bible_path()` is the guard, and it only ever resolves `.md` *files*
    — a folder name resolves to nothing, so the bible tree is deleted file by
    file. That is deliberate: the same guard the editor writes through stays a
    security boundary, and there is no path shape that takes the whole bible.
    """
    paths = trash.bible_paths(bdir, name)
    files, size = trash.size_of(paths)
    p = ar.safe_bible_path(bdir, name)
    words = ar.body_words(p) if (p is not None and p.is_file()) else 0
    return {"path": name, "files": files, "bytes": size, "words": words}


def _series_impact(series: str) -> dict:
    """Everything a series delete would take, summed over its books."""
    sd = ARCHIVE_ROOT / series
    books = trash.series_books(series)
    files, size = trash.size_of([sd])
    totals = {"chapters": 0, "revisions": 0, "notes": 0, "threads": 0,
              "words": 0, "bible_files": 0}
    for b in books:
        impact = _book_impact(b)
        for key in totals:
            totals[key] += impact[key]
    totals.update({
        "series": series,
        "title": ar._read_series_title(sd) if sd.is_dir() else series,
        "books": len(books),
        "files": files,
        "bytes": size,
    })
    return totals


@app.get("/api/books/{series}/{book_id}/impact", tags=["trash"])
def book_impact(series: str, book_id: str):
    return _book_impact(_resolve_book_path(series, book_id))


@app.get("/api/books/{series}/{book_id}/chapters/{chapter_id}/impact", tags=["trash"])
def chapter_impact(series: str, book_id: str, chapter_id: str):
    bdir = _resolve_book_path(series, book_id)
    if not ar.is_chapter_id(chapter_id) or ar.get_chapter(bdir, chapter_id) is None:
        raise HTTPException(404, "chapter not found")
    return _chapter_impact(bdir, chapter_id)


@app.delete("/api/books/{series}/{book_id}/chapters/{chapter_id}", tags=["trash"])
def delete_chapter(series: str, book_id: str, chapter_id: str):
    """Move one chapter (and its revisions, notes, thread) to the trash."""
    bdir = _resolve_book_path(series, book_id)
    if not ar.is_chapter_id(chapter_id) or ar.get_chapter(bdir, chapter_id) is None:
        raise HTTPException(404, "chapter not found")
    impact = _chapter_impact(bdir, chapter_id)
    manifest = trash.move_to_trash(
        trash.chapter_paths(bdir, chapter_id),
        kind="chapter", label=impact["title"], series=bdir.parent.name,
        book_id=bdir.name, chapter_id=chapter_id, words=impact["words"],
    )
    db.delete_chapter_index(bdir.name, chapter_id)
    reindex_search()
    manifest["impact"] = impact
    return manifest


@app.delete("/api/books/{series}/{book_id}", tags=["trash"])
def delete_book(series: str, book_id: str):
    """Move a whole book (chapters, bible, notes, threads) to the trash.

    When it is the last book in its series, `series.json` goes too — otherwise
    the rail is left with a series that contains no books.
    """
    bdir = _resolve_book_path(series, book_id)
    impact = _book_impact(bdir)
    paths = [bdir]
    if trash.is_last_book(series, bdir.name):
        paths.append(trash.series_json_path(series))
    manifest = trash.move_to_trash(
        paths, kind="book", label=impact["title"], series=bdir.parent.name,
        book_id=bdir.name, words=impact["words"],
    )
    db.delete_book_index(bdir.name)
    reindex_search()
    # Pending revisions for this book die with it: a proposal about a chapter that is
    # in the trash is a banner nobody can act on (2.9.1).
    muse_mod.delete_proposals_for(book=bdir.name)
    manifest["impact"] = impact
    return manifest


@app.get("/api/books/{series}/{book_id}/bible/{name:path}/impact", tags=["trash"])
def bible_impact(series: str, book_id: str, name: str):
    bdir = _resolve_book_path(series, book_id)
    if not trash.bible_paths(bdir, name):
        raise HTTPException(404, "bible file not found")
    return _bible_impact(bdir, name)


@app.delete("/api/books/{series}/{book_id}/bible/{name:path}", tags=["trash"])
def delete_bible(series: str, book_id: str, name: str):
    """Move a bible file — or a whole bible folder — to the trash.

    The path goes through `ar.safe_bible_path()`, the same guard the editor
    writes through, so the model-free client can't escape the archive with it.
    """
    bdir = _resolve_book_path(series, book_id)
    paths = trash.bible_paths(bdir, name)
    if not paths:
        raise HTTPException(404, "bible file not found")
    impact = _bible_impact(bdir, name)
    manifest = trash.move_to_trash(
        paths, kind="bible", label=name, series=series, book_id=bdir.name,
    )
    reindex_search()
    manifest["impact"] = impact
    return manifest


@app.get("/api/series/{series}/impact", tags=["trash"])
def series_impact(series: str):
    if not ar.is_slug(series) or not (ARCHIVE_ROOT / series).is_dir():
        raise HTTPException(404, "series not found")
    return _series_impact(series)


@app.delete("/api/series/{series}", tags=["trash"])
def delete_series(series: str):
    """Move an entire series to the trash: every book, the bible, series.json
    and the books' own Muse threads."""
    sd = ARCHIVE_ROOT / series
    if not ar.is_slug(series) or not sd.is_dir():
        raise HTTPException(404, "series not found")
    books = trash.series_books(series)
    impact = _series_impact(series)
    manifest = trash.move_to_trash(
        trash.series_paths(series), kind="series", label=impact["title"],
        series=series, book_id="", words=impact["words"],
    )
    for b in books:
        db.delete_book_index(b.name)
    reindex_search()
    muse_mod.delete_proposals_for(series=series)
    manifest["impact"] = impact
    return manifest


@app.delete("/api/trash/{entry_id}", tags=["trash"])
def purge_trash_entry(entry_id: str):
    """Erase ONE trash entry for real. There is no way back from this."""
    data = trash.purge(entry_id)
    if data is None:
        raise HTTPException(404, "no such trash entry")
    return data


@app.delete("/api/trash", tags=["trash"])
def purge_trash():
    """Empty the trash for real."""
    return trash.purge_all()


@app.get("/api/trash", tags=["trash"])
def trash_list():
    """Everything that can be brought back, newest first."""
    return {"entries": trash.list_trash()}


@app.post("/api/trash/{entry_id}/restore", tags=["trash"])
def trash_restore(entry_id: str):
    """Put a trashed chapter/book back where it came from.

    409 when the entry is gone, or when something now occupies its path (a
    chapter id can be reused after a delete — clobbering the new chapter to
    resurrect the old one would be the worst possible outcome).
    """
    data = trash.restore(entry_id)
    if data is None:
        raise HTTPException(409, "cannot restore: the entry is gone, or its path is occupied again")
    reindex_search()
    # Re-assert index rows from disk: one book for a chapter/book/bible restore,
    # every book for a restored series.
    base = ARCHIVE_ROOT / (data.get("series") or "")
    book_id = data.get("book_id") or ""
    if book_id and (base / book_id).is_dir():
        _reindex_book_meta(base / book_id)
    elif base.is_dir():
        for b in sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")):
            _reindex_book_meta(b)
    return data


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

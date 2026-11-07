"""Pydantic schemas for the Katha Archive API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str
    version: str
    db_ok: bool


class BookOut(BaseModel):
    id: str
    series: str
    title: str
    chapter_count: int = 0
    author: str = ""
    has_cover: bool = False


class BooksTreeOut(BaseModel):
    """Series → books tree (the rail)."""
    series: str
    title: str = ""
    books: list[BookOut]


class ChapterMeta(BaseModel):
    id: str
    book_id: str
    title: str
    words: int = 0
    path: str | None = None          # relative md path
    revision: int = 0                # current revision number
    updated_at: str | None = None    # last write, used to resume where the author left off


class ChapterOut(ChapterMeta):
    content: str = ""


class ChapterListOut(BaseModel):
    book_id: str
    chapters: list[ChapterMeta]


class RevisionOut(BaseModel):
    number: int
    created_at: str
    words: int = 0


class RevisionContentOut(RevisionOut):
    content: str = ""


class ChapterCreate(BaseModel):
    title: str = Field(min_length=1)
    content: str = ""
    # 0 = a prologue (opt-in per book, never scaffolded). None → next free number.
    number: int | None = Field(default=None, ge=0, le=999)


class ChapterUpdate(BaseModel):
    content: str
    title: str | None = None         # empty/None → keep the existing heading


class BookCreate(BaseModel):
    series: str = Field(min_length=1)
    title: str = Field(min_length=1)
    author: str = ""                  # 2.8: prefilled from Settings by the client


class BookMetaIn(BaseModel):
    """Editable per-book metadata (2.8). Author only, on purpose: the title IS the
    directory name, so renaming a book is a move, not a field edit."""
    author: str = ""


class CoverIn(BaseModel):
    """A cover upload as base64 JSON (D43) — no multipart dependency needed."""
    data: str
    content_type: str = "image/jpeg"   # advisory; the bytes are sniffed anyway


class BibleOut(BaseModel):
    book_id: str
    files: dict[str, str]             # filename → content


class SearchHit(BaseModel):
    kind: str                          # "chapter" | "bible"
    series: str
    book_id: str
    doc_id: str
    title: str
    snippet: str


class SearchOut(BaseModel):
    query: str
    count: int
    hits: list[SearchHit]


# --- Muse (0.3) -----------------------------------------------------------

class MuseMessage(BaseModel):
    role: str
    content: str


class MuseChatRequest(BaseModel):
    messages: list[MuseMessage]
    chapter_id: str | None = None
    chip: str | None = None  # 'rewrite' | 'continue' | 'scene' | 'canon'


class MuseRewriteRequest(BaseModel):
    text: str
    style: str = "novel"      # 'novel' | 'scene' | 'clean'
    chapter_id: str | None = None


# --- canon sweep (0.4) ----------------------------------------------------

class ProposalAcceptIn(BaseModel):
    """Which hunks of a pending revision to write. Omitted = all of them (an IDE's
    "accept all"); an empty list is a legitimate "none of it" (3.0, D48)."""
    hunks: list[int] | None = None


class MuseSweepRequest(BaseModel):
    series: str
    book_id: str
    target: str = "report"    # 'report' | 'bible'
    bible_name: str | None = None


class BibleUpdate(BaseModel):
    content: str


# --- reading-mode notes (1.0) ---------------------------------------------

class NoteOut(BaseModel):
    quote: str = ""
    body: str = ""
    created_at: str = ""


class NotesOut(BaseModel):
    chapter_id: str
    notes: list[NoteOut]


class NoteIn(BaseModel):
    quote: str = ""
    body: str = ""
    created_at: str | None = None


class NotesUpdate(BaseModel):
    notes: list[NoteIn]


# --- the door (2.2) -------------------------------------------------------

class LoginIn(BaseModel):
    password: str

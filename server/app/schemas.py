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


class ChapterUpdate(BaseModel):
    content: str


class BookCreate(BaseModel):
    series: str = Field(min_length=1)
    title: str = Field(min_length=1)


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

"""SQLite index over the md archive (D5 — index ONLY, never the truth).

Tables:
    books    (id, series, title)
    chapters (id, book_id, title, path, words, revision)
    search_index (FTS5: kind, series, book_id, doc_id, title, body)  [0.2.2]
Revisions keep full snapshots as files (D9); this DB stores their metadata.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id      TEXT PRIMARY KEY,
    series  TEXT NOT NULL,
    title   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chapters (
    id        TEXT PRIMARY KEY,
    book_id   TEXT NOT NULL,
    title     TEXT NOT NULL,
    path      TEXT NOT NULL,
    words     INTEGER NOT NULL DEFAULT 0,
    revision  INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (book_id) REFERENCES books(id)
);
CREATE TABLE IF NOT EXISTS revisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id TEXT NOT NULL,
    number     INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    words      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id);
CREATE INDEX IF NOT EXISTS idx_revisions_chapter ON revisions(chapter_id);
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    kind, series, book_id, doc_id, title, body
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def health() -> bool:
    try:
        conn = connect()
        conn.execute("SELECT 1")
        conn.close()
        return True
    except Exception:
        return False


def upsert_book(book_id: str, series: str, title: str):
    conn = connect()
    conn.execute(
        "INSERT INTO books (id, series, title) VALUES (?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET series=excluded.series, title=excluded.title",
        (book_id, series, title),
    )
    conn.commit()
    conn.close()


def upsert_chapter(chapter: dict):
    conn = connect()
    conn.execute(
        "INSERT INTO chapters (id, book_id, title, path, words, revision) "
        "VALUES (:id,:book_id,:title,:path,:words,:revision) "
        "ON CONFLICT(id) DO UPDATE SET "
        "title=excluded.title, path=excluded.path, words=excluded.words, "
        "revision=excluded.revision",
        chapter,
    )
    conn.commit()
    conn.close()


def record_revision(chapter_id: str, number: int, created_at: str, words: int):
    conn = connect()
    conn.execute(
        "INSERT INTO revisions (chapter_id, number, created_at, words) VALUES (?,?,?,?)",
        (chapter_id, number, created_at, words),
    )
    conn.commit()
    conn.close()


def list_chapter_index(book_id: str) -> list[dict]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM chapters WHERE book_id=? ORDER BY id", (book_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_book_index(book_id: str):
    conn = connect()
    conn.execute("DELETE FROM chapters WHERE book_id=?", (book_id,))
    conn.execute("DELETE FROM books WHERE id=?", (book_id,))
    conn.commit()
    conn.close()


# ---------- FTS5 search (0.2.2) ----------

def index_doc(kind: str, series: str, book_id: str, doc_id: str,
               title: str, body: str):
    """Index (or replace) one searchable doc — chapter or bible entry."""
    conn = connect()
    conn.execute(
        "DELETE FROM search_index WHERE kind=? AND doc_id=? AND book_id=?",
        (kind, doc_id, book_id),
    )
    conn.execute(
        "INSERT INTO search_index (kind, series, book_id, doc_id, title, body) "
        "VALUES (?,?,?,?,?,?)",
        (kind, series, book_id, doc_id, title, body),
    )
    conn.commit()
    conn.close()


def search(query: str, limit: int = 20) -> list[dict]:
    """Full-text search across chapters + bible. Returns ranked hits with a
    snippet. The query is passed as a plain phrase to FTS5's MATCH (safe —
    parameterised, no SQL injection)."""
    conn = connect()
    # FTS5 MATCH with the raw phrase; escape is handled by parameter binding.
    rows = conn.execute(
        "SELECT kind, series, book_id, doc_id, title, "
        "       snippet(search_index, 5, '<mark>', '</mark>', '…', 24) AS snippet "
        "FROM search_index "
        "WHERE search_index MATCH ? "
        "ORDER BY rank LIMIT ?",
        (query, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_search_index():
    conn = connect()
    conn.execute("DELETE FROM search_index")
    conn.commit()
    conn.close()

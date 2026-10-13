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
    book_id   TEXT NOT NULL,
    id        TEXT NOT NULL,
    title     TEXT NOT NULL,
    path      TEXT NOT NULL,
    words     INTEGER NOT NULL DEFAULT 0,
    revision  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (book_id, id),
    FOREIGN KEY (book_id) REFERENCES books(id)
);
CREATE TABLE IF NOT EXISTS revisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id    TEXT NOT NULL DEFAULT '',
    chapter_id TEXT NOT NULL,
    number     INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    words      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (book_id, chapter_id, number)
);
CREATE INDEX IF NOT EXISTS idx_chapters_book ON chapters(book_id);
CREATE INDEX IF NOT EXISTS idx_revisions_chapter ON revisions(book_id, chapter_id);
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    kind, series, book_id, doc_id, title, body
);
"""

# SCHEMA_VERSION history:
#   0 → pre-0.3.8: chapters/revisions keyed by bare chapter id ('ch-01'),
#       so two books silently overwrote each other's index rows.
#   1 → composite keys above.
#
# The DB is an index ONLY (D5) — every table is rebuilt from the md archive
# by normal API traffic and /api/search/reindex. On version mismatch we drop
# the derived tables and let them repopulate; md files are never touched.
SCHEMA_VERSION = 1


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < SCHEMA_VERSION:
        for table in ("revisions", "chapters", "books", "search_index"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
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
        "INSERT INTO chapters (book_id, id, title, path, words, revision) "
        "VALUES (:book_id,:id,:title,:path,:words,:revision) "
        "ON CONFLICT(book_id, id) DO UPDATE SET "
        "title=excluded.title, path=excluded.path, words=excluded.words, "
        "revision=excluded.revision",
        chapter,
    )
    conn.commit()
    conn.close()


def record_revision(book_id: str, chapter_id: str, number: int,
                    created_at: str, words: int):
    conn = connect()
    conn.execute(
        "INSERT INTO revisions (book_id, chapter_id, number, created_at, words) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(book_id, chapter_id, number) DO UPDATE SET "
        "created_at=excluded.created_at, words=excluded.words",
        (book_id, chapter_id, number, created_at, words),
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
    snippet. Malformed FTS5 syntax (unbalanced quotes, dangling operators)
    degrades to an empty result — never a 500."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT kind, series, book_id, doc_id, title, "
            "       snippet(search_index, 5, '<mark>', '</mark>', '…', 24) AS snippet "
            "FROM search_index "
            "WHERE search_index MATCH ? "
            "ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        # FTS5 MATCH syntax error (e.g. q='"unbalanced') — treat as no hits.
        return []
    finally:
        conn.close()
    return [dict(r) for r in rows]


def clear_search_index():
    conn = connect()
    conn.execute("DELETE FROM search_index")
    conn.commit()
    conn.close()

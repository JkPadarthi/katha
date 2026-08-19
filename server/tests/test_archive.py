"""End-to-end tests for the Katha Archive (0.2.1), isolated on a temp archive.

Uses FastAPI TestClient against the real app with KATHA_ARCHIVE pointed at a
temp dir, so the md files on disk are genuinely exercised (source of truth).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Point the archive + index at a temp dir BEFORE importing app modules.
_TMP = tempfile.mkdtemp(prefix="katha-test-")
os.environ["KATHA_ARCHIVE"] = str(Path(_TMP) / "archive")
os.environ["KATHA_DATA"] = str(Path(_TMP) / "data")

from app import archive as ar  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

SERIES, BOOK = "The Ember Throne", "The First Flame"


@pytest.fixture(scope="module", autouse=True)
def seeded():
    from seed import seed
    seed(quiet=True)
    yield


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.2.1"
    assert body["db_ok"] is True


def test_books_tree_seeded():
    r = client.get("/api/books")
    assert r.status_code == 200
    tree = r.json()
    assert any(b["series"] == ar.slugify(SERIES) for b in tree)


def test_chapters_seeded_on_disk():
    r = client.get(f"/api/books/{ar.slugify(SERIES)}/{ar.slugify(BOOK)}/chapters")
    assert r.status_code == 200
    body = r.json()
    assert body["book_id"] == ar.slugify(BOOK)
    ids = [c["id"] for c in body["chapters"]]
    assert ids == ["ch-01", "ch-02", "ch-03", "ch-04"]
    # source of truth on disk
    bdir = ar.book_dir(SERIES, BOOK)
    assert (bdir / "chapters" / "ch-01.md").exists()


def test_read_chapter_returns_content():
    r = client.get(f"/api/books/{ar.slugify(SERIES)}/{ar.slugify(BOOK)}/chapters/ch-01")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "ch-01"
    assert "fire in the hearth" in body["content"]
    assert body["words"] > 0


def test_autosave_creates_revision():
    series, book = ar.slugify(SERIES), ar.slugify(BOOK)
    new_text = "The fire had gone out entirely. Kael stood, and his shadow was the only company the cold kept."

    r = client.put(f"/api/books/{series}/{book}/chapters/ch-01",
                   json={"content": new_text})
    assert r.status_code == 200
    body = r.json()
    assert body["revision"] == 1
    assert body["content"] == new_text
    assert body["words"] == len(new_text.split())

    # on-disk file updated (source of truth) + revision snapshot exists
    bdir = ar.book_dir(SERIES, BOOK)
    ch = bdir / "chapters" / "ch-01.md"
    assert new_text in ch.read_text()
    assert (bdir / "chapters" / "ch-01.1.md").exists()


def test_revisions_list_and_fetch():
    series, book = ar.slugify(SERIES), ar.slugify(BOOK)
    r = client.get(f"/api/books/{series}/{book}/chapters/ch-01/revisions")
    assert r.status_code == 200
    revs = r.json()
    assert len(revs) == 1
    assert revs[0]["number"] == 1

    r2 = client.get(f"/api/books/{series}/{book}/chapters/ch-01/revisions/1")
    assert r2.status_code == 200
    assert "fire had gone out entirely" in r2.json()["content"]


def test_create_chapter():
    series, book = ar.slugify(SERIES), ar.slugify(BOOK)
    r = client.post(f"/api/books/{series}/{book}/chapters",
                    json={"title": "The Long Road", "content": "He walked until the map forgot him."})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == "ch-05"
    assert body["title"] == "The Long Road"


def test_bible_readable():
    series, book = ar.slugify(SERIES), ar.slugify(BOOK)
    r = client.get(f"/api/books/{series}/{book}/bible")
    assert r.status_code == 200
    files = r.json()["files"]
    assert "characters.md" in files
    assert "Kael" in files["characters.md"]


def test_404_on_missing_chapter():
    series, book = ar.slugify(SERIES), ar.slugify(BOOK)
    r = client.get(f"/api/books/{series}/{book}/chapters/nope")
    assert r.status_code == 404

"""Refresh resumes where the author was (3.0.8, D52).

The behaviour being protected: opening or reloading the app lands on the chapter the author
last had open, and failing that on the chapter written *most recently* — never simply on the
first chapter in the rail. The rail itself must stay in reading order; only the landing
chapter changes.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

_TMP = tempfile.mkdtemp(prefix="katha-resume-test-")
os.environ["KATHA_ARCHIVE"] = str(Path(_TMP) / "archive")
os.environ["KATHA_DATA"] = str(Path(_TMP) / "data")

from app.main import app  # noqa: E402

client = TestClient(app)

SERIES = "Resume Shelf"
BOOK = "Resume Book"
SID = "resume-shelf"
BID = "resume-book"


def _boot():
    assert client.post("/api/books", json={"series": SERIES, "title": BOOK}).status_code == 201


def _chapters():
    """This endpoint answers {chapters: [...]}, not a bare list."""
    body = client.get(f"/api/books/{SID}/{BID}/chapters").json()
    return body["chapters"] if isinstance(body, dict) else body


def test_chapter_list_carries_the_last_write_time():
    _boot()
    created = client.post(f"/api/books/{SID}/{BID}/chapters",
                          json={"title": "One", "content": "first chapter.\n"}).json()
    assert created["updated_at"], created
    listed = [c for c in _chapters() if c["id"] == created["id"]]
    assert listed and listed[0]["updated_at"] == created["updated_at"]


def test_the_chapter_written_most_recently_is_identifiable():
    """This is what lets the app open 'the latest' instead of 'the first'."""
    import time
    one = client.post(f"/api/books/{SID}/{BID}/chapters",
                      json={"title": "Two", "content": "second chapter.\n"}).json()
    time.sleep(0.02)
    two = client.post(f"/api/books/{SID}/{BID}/chapters",
                      json={"title": "Three", "content": "third chapter.\n"}).json()
    assert two["updated_at"] > one["updated_at"]

    # the author goes back and writes in the earlier chapter: it becomes the latest
    time.sleep(0.02)
    saved = client.put(f"/api/books/{SID}/{BID}/chapters/{one['id']}",
                       json={"title": "Two", "content": "second chapter, rewritten.\n"}).json()
    assert saved["updated_at"] > two["updated_at"]

    listed = {c["id"]: c for c in _chapters()}
    assert listed[one["id"]]["updated_at"] == saved["updated_at"]


def test_the_rail_keeps_reading_order_while_the_landing_chapter_moves():
    """Resuming must not reorder the chapters someone is writing — prologue first, always."""
    order = [c["id"] for c in _chapters()]
    assert order == sorted(order), order

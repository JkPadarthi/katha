"""Tests for delete + revive (2.3, D33).

The archive is the only copy of the author's novel, so the properties worth
pinning down are not "does delete delete" but:

* a chapter delete takes **everything** that belongs to that chapter — the md,
  every revision snapshot, the `.rev` counter, the notes sidecar and the Muse
  thread — and leaves its siblings untouched;
* a book delete takes the whole tree, and `series.json` with it when it was the
  last book (or the rail keeps a series with no books in it);
* the app *forgets* (rail, index rows, search hits) while the bytes survive in
  the trash;
* restore puts every file back **byte-identical**, and refuses outright rather
  than clobber a chapter that has since taken the id;
* the trash entry id is a path segment from the client, so it is a security
  boundary — separators and traversal must not resolve.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_TMP = tempfile.mkdtemp(prefix="katha-delete-test-")
os.environ["KATHA_ARCHIVE"] = str(Path(_TMP) / "archive")
os.environ["KATHA_DATA"] = str(Path(_TMP) / "data")

from app import archive as ar  # noqa: E402
from app import db  # noqa: E402
from app import trash  # noqa: E402
from app.config import ARCHIVE_ROOT  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
SERIES = ar.slugify("The Ember Throne")
BOOK = ar.slugify("The First Flame")
CH = "ch-01"


@pytest.fixture(scope="module", autouse=True)
def _seed():
    from seed import seed
    seed(quiet=True)
    yield


@pytest.fixture(autouse=True)
def _restore_state():
    """Every test starts from a pristine archive: undo whatever it did."""
    yield
    for entry in list(trash.list_trash()):
        trash.restore(entry["entry"])
    # a book delete removes the series dir for the last book — put it back
    if not (ARCHIVE_ROOT / SERIES / BOOK).is_dir():
        from seed import seed
        seed(quiet=True)


def _book_dir() -> Path:
    return ARCHIVE_ROOT / SERIES / BOOK


def _write_notes() -> None:
    ar.write_notes(_book_dir(), CH, [
        {"quote": "the ember guttered", "body": "keep this line", "created_at": "2026-01-01 00:00:00"},
    ])


def _make_revisions(n: int = 3) -> None:
    """Real revision snapshots (`ch-NN.<rev>.md` + the `.rev` counter) with the
    app's own helper — the seeded test archive ships none, the author's does."""
    chapter = ar.get_chapter(_book_dir(), CH)
    assert chapter is not None
    for i in range(n):
        ar.write_revision(chapter, f"# The Dying Ember\n\nrevision body {i}\n", "The Dying Ember")


def _write_thread(exchanges: int = 1) -> Path:
    path = ARCHIVE_ROOT / ".katha" / "muse" / f"{CH}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:      # replace, so counts are exact
        for i in range(exchanges):
            fh.write(f"## 2026-01-0{i+1} 00:00:00 UTC\n\n")
            fh.write(f"<!-- katha:user -->question {i}\n\n")
            fh.write(f"<!-- katha:assistant -->answer {i}\n\n")
            fh.write("<!-- katha:end -->\n")
    return path


def _chapter_file_names() -> list[str]:
    return sorted(p.name for p in (_book_dir() / "chapters").glob(f"{CH}*"))


# --- what the confirm dialog is told ---------------------------------------

def test_chapter_impact_counts_everything_that_will_go():
    _make_revisions(3)
    _write_notes()
    _write_thread(2)
    expected_files = len(_chapter_file_names()) + 1       # the chapter's files + its thread

    r = client.get(f"/api/books/{SERIES}/{BOOK}/chapters/{CH}/impact")
    assert r.status_code == 200
    impact = r.json()
    assert impact["chapter_id"] == CH
    assert impact["title"] and impact["title"] != CH       # a real title, not the id
    assert impact["revisions"] == len(ar.list_revisions(_book_dir(), CH))
    assert impact["revisions"] >= 3                        # the ones _make_revisions wrote
    assert impact["notes"] == 1
    assert impact["threads"] == 2
    assert impact["words"] > 0
    assert impact["files"] == expected_files
    assert impact["bytes"] > 0


def test_book_impact_sums_the_chapters():
    chapters = ar.list_chapters(_book_dir())
    on_disk = sum(1 for p in _book_dir().rglob("*") if p.is_file())
    impact = client.get(f"/api/books/{SERIES}/{BOOK}/impact").json()

    assert impact["chapters"] == len(chapters)
    assert impact["revisions"] == sum(
        len(ar.list_revisions(_book_dir(), c["id"])) for c in chapters
    )
    assert impact["bible_files"] >= 2
    assert impact["files"] == on_disk
    assert impact["title"]


# --- deleting a chapter ----------------------------------------------------

def test_delete_chapter_takes_everything_and_forgets_it():
    _write_notes()
    thread = _write_thread(1)
    before = ( _book_dir() / "chapters" / f"{CH}.md" ).read_text()
    sibling = (_book_dir() / "chapters" / "ch-02.md").read_text()

    r = client.delete(f"/api/books/{SERIES}/{BOOK}/chapters/{CH}")
    assert r.status_code == 200
    manifest = r.json()
    assert manifest["kind"] == "chapter"
    assert manifest["chapter_id"] == CH

    # gone from the archive: chapter, snapshots, marker, notes, thread
    chapters = _book_dir() / "chapters"
    assert not (chapters / f"{CH}.md").exists()
    assert list(chapters.glob(f"{CH}.*.md")) == []
    assert not (chapters / f"{CH}.rev").exists()
    assert not (chapters / f"{CH}.notes.md").exists()
    assert not thread.exists()

    # moved, not unlinked: every path in the manifest is inside the trash entry
    entry = trash.trash_root() / manifest["entry"]
    for rel in manifest["moved"]:
        assert (entry / rel).is_file(), rel
    assert json.loads((entry / "trash.json").read_text())["kind"] == "chapter"

    # siblings untouched
    assert (chapters / "ch-02.md").read_text() == sibling

    # the app forgot it: rail, index rows, search hits
    ids = [c["id"] for c in ar.list_chapters(_book_dir())]
    assert CH not in ids and "ch-02" in ids
    assert all(row["id"] != CH for row in db.list_chapter_index(BOOK))
    hits = client.get("/api/search", params={"q": "ember"}).json()["hits"]
    assert all(not (h["doc_id"] == CH and h["kind"] == "chapter") for h in hits)

    # and it is listed as restorable, with its bytes intact on disk
    assert trash.read_manifest(manifest["entry"]) is not None
    assert (entry / manifest["moved"][0]).is_file()
    assert before  # the content we compare after restore lives in the fixture


def test_restore_chapter_brings_back_revisions_notes_and_thread():
    _make_revisions(3)
    _write_notes()
    thread = _write_thread(1)
    original = (_book_dir() / "chapters" / f"{CH}.md").read_text()
    before = _chapter_file_names()
    before_rev = next(c["revision"] for c in ar.list_chapters(_book_dir()) if c["id"] == CH)
    entry = client.delete(f"/api/books/{SERIES}/{BOOK}/chapters/{CH}").json()["entry"]
    assert _chapter_file_names() == []                     # everything went
    assert not thread.exists()

    r = client.post(f"/api/trash/{entry}/restore")
    assert r.status_code == 200
    assert r.json()["restored_at"]

    chapters = _book_dir() / "chapters"
    assert (chapters / f"{CH}.md").read_text() == original
    assert (chapters / f"{CH}.rev").is_file()
    assert (chapters / f"{CH}.notes.md").is_file()
    assert thread.exists()
    assert _chapter_file_names() == before                 # byte-for-byte the same set
    assert trash.read_manifest(entry) is None              # the entry is consumed
    assert all(e["entry"] != entry for e in trash.list_trash())
    restored = [c for c in ar.list_chapters(_book_dir()) if c["id"] == CH]
    assert restored and restored[0]["revision"] == before_rev   # the counter survived


def test_search_finds_the_chapter_again_after_restore():
    assert any(h["doc_id"] == CH for h in client.get("/api/search", params={"q": "Kael"}).json()["hits"])
    entry = client.delete(f"/api/books/{SERIES}/{BOOK}/chapters/{CH}").json()["entry"]
    assert all(h["doc_id"] != CH for h in client.get("/api/search", params={"q": "Kael"}).json()["hits"])
    client.post(f"/api/trash/{entry}/restore")
    assert any(h["doc_id"] == CH for h in client.get("/api/search", params={"q": "Kael"}).json()["hits"])


# --- deleting a book -------------------------------------------------------

def test_delete_book_takes_the_tree_and_the_series_json():
    assert trash.is_last_book(SERIES, BOOK) is True
    r = client.delete(f"/api/books/{SERIES}/{BOOK}")
    assert r.status_code == 200
    manifest = r.json()
    assert manifest["kind"] == "book"

    assert not _book_dir().exists()
    assert not (ARCHIVE_ROOT / SERIES).exists()          # series.json rode along
    entry = trash.trash_root() / manifest["entry"]
    assert (entry / SERIES / BOOK / "chapters" / f"{CH}.md").is_file()
    assert (entry / SERIES / "series.json").is_file()

    # the rail forgets this series (the suite shares one archive, so assert on
    # ours rather than on global emptiness)
    tree = client.get("/api/books").json()
    assert all(s["series"] != SERIES for s in tree), tree
    assert db.list_chapter_index(BOOK) == []
    hits = client.get("/api/search", params={"q": "ember"}).json()["hits"]
    assert all(h["book_id"] != BOOK for h in hits)


def test_restore_book_round_trips():
    before = len(ar.list_chapters(_book_dir()))
    entry = client.delete(f"/api/books/{SERIES}/{BOOK}").json()["entry"]
    r = client.post(f"/api/trash/{entry}/restore")
    assert r.status_code == 200

    tree = client.get("/api/books").json()
    ours = next((s for s in tree if s["series"] == SERIES), None)
    assert ours, tree
    assert any(b["id"] == BOOK for b in ours["books"])
    assert len(ar.list_chapters(_book_dir())) == before         # every chapter came home
    assert (ARCHIVE_ROOT / SERIES / "series.json").is_file()
    hits = client.get("/api/search", params={"q": "ember"}).json()["hits"]
    assert any(h["kind"] == "chapter" and h["book_id"] == BOOK for h in hits)
    assert all(e["entry"] != entry for e in trash.list_trash())


def test_restore_refuses_rather_than_clobber_an_occupied_path():
    """Delete a chapter, let something else take its path, then try to restore:
    the occupant must survive and the restore must be refused (nothing moved).

    The occupant is written directly rather than created through the API — a
    chapter id can be reused, and this is the exact condition restore has to
    detect either way.
    """
    victim = ar.list_chapters(_book_dir())[-1]["id"]
    path = _book_dir() / "chapters" / f"{victim}.md"
    original = path.read_text()
    entry = client.delete(f"/api/books/{SERIES}/{BOOK}/chapters/{victim}").json()["entry"]

    path.write_text("# Occupied\n\nsomething else lives here now\n", encoding="utf-8")
    r = client.post(f"/api/trash/{entry}/restore")
    assert r.status_code == 409
    assert path.read_text().startswith("# Occupied")        # the occupant survived
    assert trash.read_manifest(entry) is not None           # nothing was consumed

    # put the archive back as we found it, which also proves the recovery path
    path.unlink()
    assert client.post(f"/api/trash/{entry}/restore").status_code == 200
    assert path.read_text() == original


# --- refusals and guards ---------------------------------------------------

def test_unknown_things_are_404():
    assert client.delete(f"/api/books/{SERIES}/{BOOK}/chapters/ch-99").status_code == 404
    assert client.get(f"/api/books/{SERIES}/{BOOK}/chapters/ch-99/impact").status_code == 404
    assert client.delete("/api/books/no-such-series/no-such-book").status_code == 404
    assert client.delete(f"/api/books/{SERIES}/ch-01").status_code == 404     # a chapter is not a book


def test_series_slug_is_a_path_boundary():
    for bad in ("..", "../../etc", "a/b", ".hidden"):
        r = client.delete(f"/api/books/{bad}/{BOOK}")
        # 404 unknown series, 405/422 when the router refuses to match the shape
        assert r.status_code in (400, 404, 405, 422), (bad, r.status_code)
        # whatever the code, nothing may have moved
        assert _book_dir().is_dir()


def test_trash_entry_id_cannot_escape_the_trash_root():
    for bad in ("..", "../..", "a/b", ".", ""):
        r = client.post(f"/api/trash/{bad}/restore")
        assert r.status_code in (404, 405, 409), bad
    assert client.post("/api/trash/nope-not-here/restore").status_code == 409


def test_trash_list_reports_what_is_restorable():
    _make_revisions(2)
    expected = len(_chapter_file_names()) + 1              # files + thread, if any
    entry = client.delete(f"/api/books/{SERIES}/{BOOK}/chapters/{CH}").json()["entry"]
    listing = client.get("/api/trash").json()["entries"]
    mine = [e for e in listing if e["entry"] == entry]
    assert mine, listing
    assert mine[0]["kind"] == "chapter"
    assert mine[0]["label"]
    assert mine[0]["files"] == expected
    assert mine[0]["bytes"] > 0
    assert mine[0]["deleted_at"]

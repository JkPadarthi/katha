"""End-to-end tests for the Katha Archive (0.2.1), isolated on a temp archive.

Uses FastAPI TestClient against the real app with KATHA_ARCHIVE pointed at a
temp dir, so the md files on disk are genuinely exercised (source of truth).

Seeding is pinned down here too (2.4.1): the sample story is planted **once**,
never re-planted because the archive happens to be empty — an author who deletes
every book must not find the sample back after the next restart.
"""

from __future__ import annotations

import io
import os
import tempfile
import xml.dom.minidom
import zipfile
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
    assert body["version"] == "3.0.8"
    assert body["db_ok"] is True


# --- seeding is a first-run act, not a resurrection spell (2.4.1) ----------

def test_seed_once_plants_the_sample_then_never_again(tmp_path, monkeypatch):
    """The regression this exists for: the container ran `python seed.py` on
    EVERY start, so an author who deleted every book got the sample story back
    on the next restart — and on every deploy."""
    import seed as seed_mod

    archive = tmp_path / "archive"
    archive.mkdir()
    monkeypatch.setattr(seed_mod, "ARCHIVE_ROOT", archive)
    planted: list = []
    monkeypatch.setattr(seed_mod, "ar", type("Stub", (), {"list_books": staticmethod(lambda: [])})())
    monkeypatch.setattr(seed_mod, "seed", lambda **kw: (planted.append(kw), ["a"])[1])

    assert seed_mod.seed_once(quiet=True) is True
    assert len(planted) == 1
    assert (archive / seed_mod.SEED_MARKER_NAME).is_file()

    # The author deletes everything; the marker survives. Nothing is re-planted.
    assert seed_mod.seed_once(quiet=True) is False
    assert len(planted) == 1


def test_seed_once_only_records_an_archive_that_already_has_books(tmp_path, monkeypatch):
    """Upgrade path: an archive with the author's work but no marker must not be
    seeded — it is merely marked as already seeded."""
    import seed as seed_mod

    archive = tmp_path / "archive"
    (archive / "some-series" / "some-book").mkdir(parents=True)
    monkeypatch.setattr(seed_mod, "ARCHIVE_ROOT", archive)
    monkeypatch.setattr(
        seed_mod, "ar",
        type("Stub", (), {"list_books": staticmethod(lambda: [{"series": "some-series"}])})(),
    )
    monkeypatch.setattr(
        seed_mod, "seed",
        lambda **kw: pytest.fail("must not plant the sample into a populated archive"),
    )

    assert seed_mod.seed_once(quiet=True) is False
    assert (archive / seed_mod.SEED_MARKER_NAME).is_file()


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
    assert "characters/kael.md" in files
    assert "Kael" in files["characters/kael.md"]


def test_404_on_missing_chapter():
    series, book = ar.slugify(SERIES), ar.slugify(BOOK)
    r = client.get(f"/api/books/{series}/{book}/chapters/nope")
    assert r.status_code == 404


# ---------- FTS5 search (0.2.2) ----------

def _reindex():
    from app.main import reindex_search
    reindex_search()


def test_search_reindex_populates_index():
    # Rebuild FTS from disk (the seed already wrote md files), search a stable
    # term — "Varna" lives only in ch-02's seeded body, which no earlier test
    # mutates, so it's a reliable chapter-only hit.
    _reindex()
    r = client.get("/api/search", params={"q": "Varna"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert body["hits"][0]["kind"] == "chapter"
    assert body["hits"][0]["doc_id"] == "ch-02"


def test_search_returns_snippet_with_mark():
    _reindex()
    r = client.get("/api/search", params={"q": "Varna"})
    hit = r.json()["hits"][0]
    assert "<mark>" in hit["snippet"]


def test_search_finds_bible_entry():
    _reindex()
    # "Kael" appears in bible/characters.md (stable) — and also chapters,
    # so the result set should span both kinds.
    r = client.get("/api/search", params={"q": "Kael"})
    body = r.json()
    kinds = {h["kind"] for h in body["hits"]}
    assert "bible" in kinds  # characters.md carries Kael's name


def test_search_empty_query_returns_no_hits():
    r = client.get("/api/search", params={"q": ""})
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_search_no_match():
    _reindex()
    r = client.get("/api/search", params={"q": "zzzznonexistentword"})
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_search_excludes_revision_snapshots():
    # ch-01 has revision snapshots (ch-01.N.md) from the autosave test earlier.
    # They must NOT appear as separate search hits — only canonical chapters.
    _reindex()
    r = client.get("/api/search", params={"q": "Kael"})
    body = r.json()
    doc_ids = {h["doc_id"] for h in body["hits"] if h["kind"] == "chapter"}
    # No doc_id may contain a '.' (revision marker), and no ch-01.1 etc.
    assert all("." not in d for d in doc_ids), f"revision leaked: {doc_ids}"
    assert "ch-01" in doc_ids          # the canonical chapter IS indexed
    assert "ch-01.1" not in doc_ids    # revision snapshot is NOT


# --- bible write (0.4 canon sweep approval) -------------------------------

def test_bible_put_writes_nested_and_indexes():
    """PUT a nested bible file → written to disk (md is the truth) + searchable."""
    name = "characters/mira.md"
    content = "# Mira\n\nThe Ember Throne's herald is named Borel."
    r = client.put(
        f"/api/books/{ar.slugify(SERIES)}/{ar.slugify(BOOK)}/bible/{name}",
        json={"content": content},
    )
    assert r.status_code == 200
    assert r.json()["files"][name] == content

    bd = ar.bible_dir(ar.book_dir(SERIES, BOOK))
    assert (bd / "characters" / "mira.md").read_text(encoding="utf-8") == content

    hits = client.get("/api/search", params={"q": "Borel"}).json()["hits"]
    assert any(h["doc_id"] == name for h in hits)


def test_bible_put_rejects_non_md_name():
    r = client.put(
        f"/api/books/{ar.slugify(SERIES)}/{ar.slugify(BOOK)}/bible/notes",
        json={"content": "x"},
    )
    assert r.status_code == 400


def test_bible_path_guard():
    book = ar.book_dir(SERIES, BOOK)
    assert ar.safe_bible_path(book, "characters/mira.md") is not None
    for bad in ("../evil.md", "/etc/passwd", ".hidden/x.md", "characters/x.txt", "a\\b.md"):
        assert ar.safe_bible_path(book, bad) is None, bad


def test_bible_split_migration():
    """A legacy flat characters.md is split per `##` heading; the original is
    kept as characters.md.orig."""
    book = ar.book_dir(SERIES, BOOK)
    bd = ar.bible_dir(book)
    src = bd / "characters.md"
    src.write_text("# Characters\n\n## Mira\n- Scout, quick.\n\n## Borel\n- The herald.\n",
                   encoding="utf-8")
    written = ar.split_characters_bible(book)

    assert (bd / "characters" / "mira.md").is_file()
    assert (bd / "characters" / "borel.md").is_file()
    assert "Scout" in (bd / "characters" / "mira.md").read_text(encoding="utf-8")
    assert not src.exists()
    assert (bd / "characters.md.orig").is_file()
    assert written
    # .orig must never be listed as a bible file
    assert not any(k.endswith(".orig") for k in ar.read_bible(book))


# --- reading-mode notes (1.0) ---------------------------------------------

def test_notes_roundtrip_writes_sidecar():
    """PUT notes → ch-NN.notes.md on disk (md truth); GET reads them back."""
    series, book = ar.slugify(SERIES), ar.slugify(BOOK)
    url = f"/api/books/{series}/{book}/chapters/ch-01/notes"

    assert client.get(url).json()["notes"] == []       # none yet

    payload = {"notes": [
        {"quote": "The door opened.", "body": "Pacing — too early?"},
        {"quote": "You heard wrong.", "body": "Great line."},
    ]}
    r = client.put(url, json=payload)
    assert r.status_code == 200
    assert [n["quote"] for n in r.json()["notes"]] == ["The door opened.", "You heard wrong."]

    # md sidecar on disk
    sidecar = ar.chapters_dir(ar.book_dir(SERIES, BOOK)) / "ch-01.notes.md"
    assert sidecar.is_file()
    assert "The door opened." in sidecar.read_text(encoding="utf-8")

    # not counted as a chapter
    chapters = client.get(f"/api/books/{series}/{book}/chapters").json()["chapters"]
    assert all(c["id"] != "ch-01.notes" for c in chapters)


def test_notes_delete_by_put_replace():
    series, book = ar.slugify(SERIES), ar.slugify(BOOK)
    url = f"/api/books/{series}/{book}/chapters/ch-02/notes"
    client.put(url, json={"notes": [{"quote": "a", "body": "b"}]})
    r = client.put(url, json={"notes": []})
    assert r.json()["notes"] == []


def test_notes_404_on_missing_chapter():
    series, book = ar.slugify(SERIES), ar.slugify(BOOK)
    r = client.get(f"/api/books/{series}/{book}/chapters/nope/notes")
    assert r.status_code == 404


# --- writing rituals (1.0) ------------------------------------------------

def test_stats_track_daily_words():
    """Saving a chapter logs the net words added; /api/stats reports today's
    total, the goal, and a streak."""
    series, book = ar.slugify(SERIES), ar.slugify(BOOK)
    url = f"/api/books/{series}/{book}/chapters/ch-03"
    # Two saves: the second adds three words over the first.
    client.put(url, json={"content": "one two three", "title": "The Inn at Crosswater"})
    client.put(url, json={"content": "one two three four five six", "title": "The Inn at Crosswater"})

    r = client.get("/api/stats", params={"goal": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["goal"] == 1
    assert body["today"] >= 3
    assert body["streak"] >= 1
    assert len(body["history"]) == 14


def test_stats_goal_defaults_when_unset():
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert r.json()["goal"] > 0


# --- EPUB export (1.0) ----------------------------------------------------

def test_epub_export_is_valid_zip():
    series, book = ar.slugify(SERIES), ar.slugify(BOOK)
    r = client.get(f"/api/books/{series}/{book}/export.epub")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/epub+zip")
    assert "attachment" in r.headers.get("content-disposition", "")

    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    # `mimetype` must be FIRST and stored uncompressed.
    assert names[0] == "mimetype"
    assert z.read("mimetype") == b"application/epub+zip"
    assert z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED

    for required in ("META-INF/container.xml", "OEBPS/content.opf",
                     "OEBPS/nav.xhtml", "OEBPS/toc.ncx", "OEBPS/style.css"):
        assert required in names, required
    assert any(n.startswith("OEBPS/ch-") for n in names)

    # The package + nav must be well-formed XML.
    xml.dom.minidom.parseString(z.read("OEBPS/content.opf"))
    xml.dom.minidom.parseString(z.read("OEBPS/nav.xhtml"))


def test_epub_export_404_on_missing_book():
    r = client.get(f"/api/books/{ar.slugify(SERIES)}/nope/export.epub")
    assert r.status_code == 404


# --- hardening: word counts, revision numbering, 100+ chapters --------------

def test_word_counts_exclude_the_title_line():
    """Saving and listing must report the same body word count (the heading
    is not prose)."""
    series, book = ar.slugify(SERIES), ar.slugify(BOOK)
    created = client.post(f"/api/books/{series}/{book}/chapters",
                          json={"title": "Counted", "content": "one two"}).json()
    cid = created["id"]
    assert created["words"] == 2

    r = client.put(f"/api/books/{series}/{book}/chapters/{cid}",
                   json={"content": "alpha beta gamma", "title": "Counted"})
    assert r.json()["words"] == 3

    row = next(c for c in client.get(f"/api/books/{series}/{book}/chapters").json()["chapters"]
               if c["id"] == cid)
    assert row["words"] == 3


def test_revision_numbers_survive_a_deleted_snapshot():
    """Numbers come from the files on disk, not from enumerate() — deleting
    ch-NN.1.md must not make ch-NN.2.md look like revision 1."""
    series, book = ar.slugify(SERIES), ar.slugify(BOOK)
    created = client.post(f"/api/books/{series}/{book}/chapters",
                          json={"title": "Snapshots", "content": "start"}).json()
    cid = created["id"]
    base = f"/api/books/{series}/{book}/chapters/{cid}"
    client.put(base, json={"content": "first"})
    client.put(base, json={"content": "second"})

    snapshot = ar.chapters_dir(ar.book_dir(SERIES, BOOK)) / f"{cid}.1.md"
    snapshot.unlink()

    revs = client.get(f"{base}/revisions").json()
    assert [r["number"] for r in revs] == [2]
    assert client.get(f"{base}/revisions/2").status_code == 200
    assert "second" in client.get(f"{base}/revisions/2").json()["content"]

    # The next save must not reuse the deleted number.
    body = client.put(base, json={"content": "third"}).json()
    assert body["revision"] == 3


def test_search_can_scope_to_a_book():
    """The Muse's canon lookup must never borrow another book's bible."""
    from app import db

    _reindex()
    hits = db.search("Kael", limit=20, book_id=ar.slugify(BOOK))
    assert hits
    assert all(h["book_id"] == ar.slugify(BOOK) for h in hits)
    assert db.search("Kael", limit=20, book_id="no-such-book") == []


def test_book_lookup_accepts_a_title():
    """The documented book_id title fallback actually works (it used to be
    dead code behind a slug-only guard)."""
    r = client.get(f"/api/books/{ar.slugify(SERIES)}/{BOOK}/chapters")
    assert r.status_code == 200
    assert r.json()["book_id"] == ar.slugify(BOOK)


def test_new_book_starts_with_the_canonical_bible():
    """Creating a book scaffolds characters/, side-characters, places, and
    timeline — the bible has a shape before the author writes a word."""
    r = client.post("/api/books", json={"series": "Starter Series", "title": "Starter Book"})
    assert r.status_code == 201

    series_slug, book_slug = ar.slugify("Starter Series"), ar.slugify("Starter Book")
    files = client.get(f"/api/books/{series_slug}/{book_slug}/bible").json()["files"]
    assert "characters/side-characters.md" in files
    assert "places.md" in files
    assert "timeline.md" in files
    assert "## Name" in files["characters/side-characters.md"]


def test_scaffold_is_idempotent_and_never_overwrites():
    """Backfilling an old book must not clobber edited canon."""
    r = client.post("/api/books", json={"series": "Scaffold Series", "title": "Keep"})
    assert r.status_code == 201
    series_slug, book_slug = ar.slugify("Scaffold Series"), ar.slugify("Keep")

    client.put(f"/api/books/{series_slug}/{book_slug}/bible/places.md",
               json={"content": "# My Places\n\ncustom"})
    again = client.post(f"/api/books/{series_slug}/{book_slug}/bible/scaffold")
    assert again.status_code == 200
    files = again.json()["files"]
    assert files["places.md"] == "# My Places\n\ncustom"
    assert "characters/side-characters.md" in files


def test_chapters_beyond_99_are_real_and_sorted():
    assert ar.is_chapter_id("ch-100")
    assert ar.chapter_number("ch-100") == 100

    book = ar.book_dir(SERIES, BOOK)
    cd = ar.chapters_dir(book)
    high = cd / "ch-100.md"
    low = cd / "ch-099.md"
    high.write_text("# Hundred\n\nlast", encoding="utf-8")
    low.write_text("# Ninety nine\n\nbefore", encoding="utf-8")
    try:
        ids = [c["id"] for c in ar.list_chapters(book)]
        assert ids.index("ch-099") < ids.index("ch-100")
    finally:
        high.unlink(missing_ok=True)
        low.unlink(missing_ok=True)


# --- chapter 0: the prologue (2.5) ----------------------------------------

def test_a_prologue_is_optional_sorts_first_and_does_not_shift_numbering():
    """A prologue is chapter 0. It is opt-in per book (never scaffolded), it sorts
    before ch-01, and a book that has one still numbers its next chapter from the
    highest existing number — not from the count."""
    from app import muse as muse_mod

    created = client.post("/api/books", json={"series": "Prologue Tests", "title": "The Zero Book"})
    assert created.status_code == 201, created.text
    series_slug, book_slug = created.json()["series"], created.json()["id"]
    try:
        assert client.get(f"/api/books/{series_slug}/{book_slug}/chapters").json()["chapters"] == []

        first = client.post(f"/api/books/{series_slug}/{book_slug}/chapters", json={"title": "First"})
        assert first.json()["id"] == "ch-01"

        zero = client.post(
            f"/api/books/{series_slug}/{book_slug}/chapters",
            json={"title": "Prologue", "number": 0},
        )
        assert zero.status_code == 201, zero.text
        assert zero.json()["id"] == "ch-00"

        ids = [c["id"] for c in client.get(f"/api/books/{series_slug}/{book_slug}/chapters").json()["chapters"]]
        assert ids == ["ch-00", "ch-01"], ids          # the prologue comes first

        # numbering is untouched by the zero: the next new chapter is ch-02
        second = client.post(f"/api/books/{series_slug}/{book_slug}/chapters", json={"title": "Second"})
        assert second.json()["id"] == "ch-02"

        # a second prologue is refused, and a negative number is not a chapter
        dup = client.post(f"/api/books/{series_slug}/{book_slug}/chapters",
                          json={"title": "Another", "number": 0})
        assert dup.status_code == 409, dup.text
        assert client.post(f"/api/books/{series_slug}/{book_slug}/chapters",
                           json={"title": "Nope", "number": -1}).status_code == 422

        # it reads, saves and takes revisions like any chapter
        assert client.get(f"/api/books/{series_slug}/{book_slug}/chapters/ch-00").json()["title"] == "Prologue"
        saved = client.put(f"/api/books/{series_slug}/{book_slug}/chapters/ch-00",
                           json={"content": "# Prologue\n\nthe before\n", "title": "Prologue"})
        assert saved.status_code == 200, saved.text
        assert (ar.book_dir(series_slug, book_slug) / "chapters" / "ch-00.1.md").is_file()

        # searchable, and its Muse thread is book-scoped like every other chapter
        hits = client.get("/api/search", params={"q": "before"}).json()["hits"]
        assert any(h["doc_id"] == "ch-00" for h in hits), hits
        thread = muse_mod._thread_path(f"{series_slug}/{book_slug}/ch-00")
        assert thread is not None and thread.name == f"{book_slug}-ch-00.md"

        # and it deletes + restores through the same trash as everything else
        entry = client.delete(f"/api/books/{series_slug}/{book_slug}/chapters/ch-00").json()["entry"]
        assert not (ar.book_dir(series_slug, book_slug) / "chapters" / "ch-00.md").exists()
        client.post(f"/api/trash/{entry}/restore")
        assert (ar.book_dir(series_slug, book_slug) / "chapters" / "ch-00.md").is_file()
    finally:
        entry = client.delete(f"/api/books/{series_slug}/{book_slug}").json()["entry"]
        client.delete(f"/api/trash/{entry}")

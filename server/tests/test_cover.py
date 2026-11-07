"""Cover + author (2.8, D43) — the book's face, and what the EPUB does with it.

The rules the net has to hold:

1. **Upload is normalised, not trusted.** The bytes are sniffed (never the
   filename or the declared content-type), EXIF-oriented, downscaled to fit
   1600×2560 without ever upscaling, flattened to RGB and re-encoded as JPEG — so
   an 8 MB phone photo can't end up inside an EPUB.
2. **The EPUB wiring is exact**, because half of it silently shows nothing: image
   item with `properties="cover-image"`, `cover.xhtml` FIRST in the spine, the
   legacy `<meta name="cover">`, and a `guide` reference.
3. **No cover is a state, not an error** — no cover page, no invented artwork —
   and the author still lands in `<dc:creator>`.
4. **The cover travels with the book**: delete → trash → restore keeps the same
   bytes, because it lives inside the book directory.

Every assertion is scoped to this module's own series/book: all test modules
share the first-imported temp archive (config reads KATHA_ARCHIVE at import).
"""

from __future__ import annotations

import base64
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

_TMP = tempfile.mkdtemp(prefix="katha-cover-test-")
os.environ["KATHA_ARCHIVE"] = str(Path(_TMP) / "archive")
os.environ["KATHA_DATA"] = str(Path(_TMP) / "data")

from app import archive as ar  # noqa: E402
from app import auth as auth_mod  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

SERIES = "Cover Shelf"
BOOK = "Covered Book"
SID = ar.slugify(SERIES)
BID = ar.slugify(BOOK)


@pytest.fixture(scope="module", autouse=True)
def _make_book():
    r = client.post("/api/books", json={"series": SERIES, "title": BOOK})
    assert r.status_code == 201
    yield


# --- helpers --------------------------------------------------------------

def _png(w: int, h: int, color=(180, 40, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def _upload(data: bytes, series: str = SID, book: str = BID):
    return client.put(
        f"/api/books/{series}/{book}/cover",
        json={"data": base64.b64encode(data).decode(), "content_type": "image/png"},
    )


def _bdir() -> Path:
    return ar.book_dir(SERIES, BOOK)


def _book_json() -> dict:
    return json.loads((_bdir() / "book.json").read_text())


def _stored_cover() -> Path:
    """The stored cover file, asserted to exist (keeps the tests None-safe)."""
    p = ar.cover_path(_bdir())
    assert p is not None, "expected a stored cover"
    return p


def _clear_cover() -> None:
    client.delete(f"/api/books/{SID}/{BID}/cover")


# --- 1. upload: trusted bytes, normalised image ----------------------------

def test_a_big_upload_is_downscaled_to_a_fitting_jpeg():
    """3000×4800 in → 1600×2560 JPEG out, and book.json records the truth."""
    r = _upload(_png(3000, 4800))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["cover_w"], body["cover_h"]) == (1600, 2560)
    assert body["has_cover"] is True

    stored = ar.cover_path(_bdir())
    assert stored is not None and stored.name == "cover.jpg"
    assert stored.read_bytes()[:2] == b"\xff\xd8"          # a real JPEG
    meta = _book_json()
    assert (meta["cover_w"], meta["cover_h"]) == (1600, 2560)

    got = client.get(f"/api/books/{SID}/{BID}/cover")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/jpeg"


def test_a_small_cover_is_kept_at_its_own_size():
    """Never upscaled: a 400×640 cover stays 400×640."""
    r = _upload(_png(400, 640))
    assert r.status_code == 200, r.text
    assert (r.json()["cover_w"], r.json()["cover_h"]) == (400, 640)

    with Image.open(_stored_cover()) as img:
        assert img.size == (400, 640)
        assert img.format == "JPEG"


def test_a_transparent_png_is_flattened_onto_white():
    """Alpha can't survive a JPEG; it must be flattened deliberately, not mangled."""
    buf = io.BytesIO()
    Image.new("RGBA", (500, 800), (255, 0, 0, 0)).save(buf, "PNG")   # fully transparent
    r = _upload(buf.getvalue())
    assert r.status_code == 200, r.text
    with Image.open(_stored_cover()) as img:
        assert img.mode == "RGB"
        assert img.getpixel((10, 10)) == (255, 255, 255)


def test_an_upload_that_is_not_an_image_is_refused():
    r = _upload(b"this is definitely not an image")
    assert r.status_code == 400
    assert "image" in r.json()["detail"].lower()


def test_an_oversize_upload_is_refused_before_it_is_decoded():
    """The size guard runs first, so a huge blob never reaches the decoder."""
    r = _upload(b"x" * (ar.COVER_MAX_BYTES + 1))
    assert r.status_code == 400
    assert "larger than" in r.json()["detail"]


def test_the_cover_can_be_removed():
    _upload(_png(600, 960))
    r = client.delete(f"/api/books/{SID}/{BID}/cover")
    assert r.status_code == 200 and r.json()["has_cover"] is False
    assert ar.cover_path(_bdir()) is None
    assert "cover" not in _book_json()
    assert client.get(f"/api/books/{SID}/{BID}/cover").status_code == 404


# --- 2. the author --------------------------------------------------------

def test_the_author_round_trips_and_can_be_cleared():
    r = client.put(f"/api/books/{SID}/{BID}/meta", json={"author": "  J. K. Padarthi  "})
    assert r.status_code == 200
    assert r.json()["author"] == "J. K. Padarthi"          # trimmed
    assert _book_json()["author"] == "J. K. Padarthi"

    tree = client.get("/api/books").json()
    mine = next(b for s in tree for b in s["books"] if b["id"] == BID)
    assert mine["author"] == "J. K. Padarthi"              # the rail needs no 2nd call

    assert client.put(f"/api/books/{SID}/{BID}/meta",
                      json={"author": ""}).json()["author"] == ""
    assert "author" not in _book_json()


def test_a_book_can_be_created_with_its_author():
    r = client.post("/api/books", json={"series": "Pen Names", "title": "Written As Someone",
                                        "author": "A. N. Other"})
    assert r.status_code == 201
    assert r.json()["author"] == "A. N. Other"
    tree = client.get("/api/books").json()
    shelf = next(s for s in tree if s["series"] == ar.slugify("Pen Names"))
    assert shelf["books"][0]["author"] == "A. N. Other"


# --- 3. the EPUB -----------------------------------------------------------

def _epub() -> zipfile.ZipFile:
    r = client.get(f"/api/books/{SID}/{BID}/export.epub")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/epub+zip"
    return zipfile.ZipFile(io.BytesIO(r.content))


def test_epub_with_a_cover_leads_with_the_cover_page():
    _upload(_png(800, 1280))
    client.put(f"/api/books/{SID}/{BID}/meta", json={"author": "J. K. Padarthi"})

    z = _epub()
    names = z.namelist()
    assert names[0] == "mimetype"                  # readers reject it otherwise
    assert "OEBPS/cover.jpg" in names
    assert "OEBPS/cover.xhtml" in names

    opf = z.read("OEBPS/content.opf").decode("utf-8")
    assert 'id="cover-image"' in opf and 'properties="cover-image"' in opf
    assert '<meta name="cover" content="cover-image"/>' in opf   # Kindle still reads this
    assert "<dc:creator>J. K. Padarthi</dc:creator>" in opf
    assert '<reference type="cover" href="cover.xhtml"/>' in opf

    spine = opf.split("<spine")[1].split("</spine>")[0]
    first = spine.split("<itemref")[1]
    assert 'idref="cover"' in first                # else the book opens at chapter one

    cover_page = z.read("OEBPS/cover.xhtml").decode("utf-8")
    assert 'src="cover.jpg"' in cover_page
    assert z.read("OEBPS/cover.jpg")[:2] == b"\xff\xd8"


def test_epub_without_a_cover_invents_nothing():
    _clear_cover()
    client.put(f"/api/books/{SID}/{BID}/meta", json={"author": "J. K. Padarthi"})

    z = _epub()
    names = z.namelist()
    assert "OEBPS/cover.jpg" not in names
    assert "OEBPS/cover.xhtml" not in names

    opf = z.read("OEBPS/content.opf").decode("utf-8")
    assert 'properties="cover-image"' not in opf
    assert '<meta name="cover"' not in opf
    assert "<reference type=\"cover\"" not in opf
    # …but the author is still metadata worth having.
    assert "<dc:creator>J. K. Padarthi</dc:creator>" in opf

    spine = opf.split("<spine")[1].split("</spine>")[0]
    assert 'idref="cover"' not in spine


def test_epub_without_an_author_has_no_creator_element():
    """An empty author must not produce `<dc:creator></dc:creator>`."""
    client.put(f"/api/books/{SID}/{BID}/meta", json={"author": ""})
    opf = _epub().read("OEBPS/content.opf").decode("utf-8")
    assert "<dc:creator>" not in opf


# --- 4. the cover travels with the book -----------------------------------

def test_a_deleted_and_restored_book_keeps_its_cover():
    _upload(_png(600, 960, (12, 34, 56)))
    before = _stored_cover().read_bytes()

    manifest = client.delete(f"/api/books/{SID}/{BID}").json()
    assert not _bdir().exists()

    r = client.post(f"/api/trash/{manifest['entry']}/restore")
    assert r.status_code == 200

    after = ar.cover_path(_bdir())
    assert after is not None
    assert after.read_bytes() == before
    assert _book_json().get("cover") == "cover.jpg"


# --- 5. the lock ----------------------------------------------------------

def test_the_cover_routes_are_behind_the_lock(monkeypatch: pytest.MonkeyPatch):
    """The cover is part of the book, so every route over it is private — only
    the login page, the mark, the manifest and /api/health are public."""
    monkeypatch.setattr(auth_mod, "PASSWORD", "s3cret-not-real")
    assert client.get(f"/api/books/{SID}/{BID}/cover").status_code == 401
    assert client.put(f"/api/books/{SID}/{BID}/cover",
                      json={"data": "eA=="}).status_code == 401
    assert client.delete(f"/api/books/{SID}/{BID}/cover").status_code == 401
    assert client.put(f"/api/books/{SID}/{BID}/meta",
                      json={"author": "x"}).status_code == 401
    assert client.get(f"/api/books/{SID}/{BID}/export.epub").status_code == 401

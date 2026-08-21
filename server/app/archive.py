"""Archive layer — the .md files on disk ARE the archive (D6).

Layout under ARCHIVE_ROOT:
    <series>/<book>/
        book.json            <- meta only (title, order, status)
        chapters/ch-01.md    <- one md per chapter (grain: one-md-per-chapter, 0.2)
        bible/<name>.md      <- characters, places, timeline
        notes.md             <- author scratch
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .config import ARCHIVE_ROOT

_SERIES_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    return _SERIES_RE.sub("-", name.lower()).strip("-")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArchiveError(Exception):
    pass


# ---------- path helpers ----------

def book_dir(series: str, book_title: str) -> Path:
    return ARCHIVE_ROOT / slugify(series) / slugify(book_title)


def chapters_dir(book: Path) -> Path:
    return book / "chapters"


def bible_dir(book: Path) -> Path:
    return book / "bible"


def book_json_path(book: Path) -> Path:
    return book / "book.json"


def _is_hidden(p: Path) -> bool:
    """True if the path's name starts with `.` (Unix dotfile convention).

    Used by the archive walkers to skip Muse persistence (`archive/.katha/`)
    and any other dotfile-prefixed directory the user (or the Muse) creates.
    """
    return p.name.startswith(".")


def list_books() -> list[dict]:
    """Scan the archive root → series → books tree (rail source)."""
    tree: dict[str, list[dict]] = {}
    for series_dir in sorted(ARCHIVE_ROOT.iterdir()):
        if not series_dir.is_dir() or _is_hidden(series_dir):
            continue
        books = []
        for b in sorted(series_dir.iterdir()):
            if not b.is_dir() or _is_hidden(b):
                continue
            meta = _read_book_json(b)
            chapters = list_chapters(b)
            words = sum(c["words"] for c in chapters)
            books.append({
                "id": meta["id"],
                "series": meta.get("series", series_dir.name),
                "title": meta.get("title", b.name),
                "chapter_count": len(chapters),
                "words": words,
            })
        tree[series_dir.name] = books
    # flatten into list of {series, title, books}
    return [{"series": s, "title": _read_series_title(ARCHIVE_ROOT / s), "books": b}
            for s, b in tree.items()]


def _read_book_json(book: Path) -> dict:
    p = book_json_path(book)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    return {"id": book.name, "title": book.name}


def _read_series_title(series_dir: Path) -> str:
    p = series_dir / "series.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get("title", series_dir.name)
        except json.JSONDecodeError:
            pass
    return series_dir.name


def ensure_book(series: str, book_title: str) -> dict:
    bdir = book_dir(series, book_title)
    bdir.mkdir(parents=True, exist_ok=True)
    # Write series.json (human title) once — mirrors book.json at the series level.
    sp = bdir.parent / "series.json"
    if not sp.exists():
        sp.write_text(json.dumps({"title": series}, indent=2), encoding="utf-8")
    (bdir / "chapters").mkdir(exist_ok=True)
    (bdir / "bible").mkdir(exist_ok=True)
    meta = {
        "id": slugify(book_title),
        "series": slugify(series),
        "title": book_title,
        "created_at": _now(),
    }
    p = book_json_path(bdir)
    if not p.exists():
        p.write_text(json.dumps(meta, indent=2))
        return meta
    return _read_book_json(bdir)


# ---------- chapters ----------

def list_chapters(book: Path) -> list[dict]:
    cd = chapters_dir(book)
    out = []
    if not cd.exists():
        return out
    # IMPORTANT: match ONLY canonical chapter files ch-NN.md. Revision
    # snapshots live as ch-NN.<rev>.md (D9 time machine) — those must NOT be
    # counted as chapters. The regex excludes any name with a second segment.
    for f in sorted(cd.glob("ch-*.md")):
        if not re.fullmatch(r"ch-\d{2}\.md", f.name):
            continue  # revision snapshot (ch-01.1.md) or marker — skip
        m = f.stem  # ch-01
        title = _chapter_title(f)
        out.append({
            "id": m,
            "book_id": book.name,
            "title": title,
            "words": _count_words(f.read_text()),
            "path": f.relative_to(ARCHIVE_ROOT).as_posix(),
            "revision": _read_revision_marker(f),
        })
    return out


def get_chapter(book: Path, chapter_id: str) -> Path | None:
    # chapter_id may be 'ch-01' or an int slug; resolve against disk
    cd = chapters_dir(book)
    if not cd.exists():
        return None
    # allow '1' -> 'ch-01'
    if chapter_id.isdigit():
        chapter_id = f"ch-{int(chapter_id):02d}"
    cand = cd / f"{chapter_id}.md"
    return cand if cand.exists() else None


def create_chapter(book: Path, title: str, content: str = "") -> dict:
    cd = chapters_dir(book)
    cd.mkdir(parents=True, exist_ok=True)
    nums = [
        int(f.stem.split("-")[-1])
        for f in cd.glob("ch-*.md")
        if f.stem.split("-")[-1].isdigit()
    ]
    next_n = (max(nums) + 1) if nums else 1
    cid = f"ch-{next_n:02d}"
    path = cd / f"{cid}.md"
    path.write_text(f"# {title}\n\n{content}".rstrip() + "\n", encoding="utf-8")
    return _chapter_meta(book, cid, title, path)


def _chapter_meta(book: Path, cid: str, title: str, path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return {
        "id": cid,
        "book_id": book.name,
        "title": _chapter_title(path) or title,
        "words": _count_words(text),
        "path": path.relative_to(ARCHIVE_ROOT).as_posix(),
        "revision": _read_revision_marker(path),
    }


def _chapter_title(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _count_words(text: str) -> int:
    return len(re.findall(r"\S+", text) or [])


# ---------- revisions (D9 time machine) ----------

def _revision_marker_path(chapter: Path) -> Path:
    return chapter.with_suffix(".rev")


def _read_revision_marker(chapter: Path) -> int:
    p = _revision_marker_path(chapter)
    if p.exists():
        try:
            return int(p.read_text().strip())
        except ValueError:
            pass
    return 0


def write_revision(chapter: Path, content: str, title: str):
    """Snapshot a full-copy revision next to the chapter (ch-01.md.1, .2, …)."""
    rev = _read_revision_marker(chapter) + 1
    snap = chapter.parent / f"{chapter.stem}.{rev}.md"
    snap.write_text(f"# {title}\n\n{content}".rstrip() + "\n", encoding="utf-8")
    _revision_marker_path(chapter).write_text(str(rev), encoding="utf-8")
    return rev


def list_revisions(book: Path, chapter_id: str):
    chapter = get_chapter(book, chapter_id)
    if not chapter:
        return None
    snaps = sorted(
        (chapter.parent / f"{chapter.stem}.{n}.md")
        for n in range(1, _read_revision_marker(chapter) + 1)
        if (chapter.parent / f"{chapter.stem}.{n}.md").exists()
    )
    return [{
        "number": i + 1,
        "created_at": _mtime(rev),
        "words": _count_words(rev.read_text()),
    } for i, rev in enumerate(snaps)]


def get_revision(book: Path, chapter_id: str, number: int):
    chapter = get_chapter(book, chapter_id)
    if not chapter:
        return None
    p = chapter.parent / f"{chapter.stem}.{number}.md"
    if not p.exists():
        return None
    return {
        "number": number,
        "created_at": _mtime(p),
        "content": p.read_text(encoding="utf-8"),
        "words": _count_words(p.read_text(encoding="utf-8")),
    }


def _mtime(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()


# ---------- bible ----------

def read_bible(book: Path) -> dict[str, str]:
    bd = bible_dir(book)
    out = {}
    if bd.exists():
        for f in sorted(bd.glob("*.md")):
            out[f.name] = f.read_text(encoding="utf-8")
    return out


# ---------- searchable docs (0.2.2) ----------

def iter_searchable_docs():
    """Yield every searchable doc as (kind, series, book_id, doc_id, title, body).

    Walks the archive on disk — the md files are the truth, this just reads
    them so the FTS index can be rebuilt from scratch (reindex)."""
    for series_dir in sorted(ARCHIVE_ROOT.iterdir()):
        if not series_dir.is_dir() or _is_hidden(series_dir):
            continue
        series_slug = series_dir.name
        for b in sorted(series_dir.iterdir()):
            if not b.is_dir() or _is_hidden(b):
                continue
            book_id = b.name
            cd = b / "chapters"
            if cd.exists():
                for f in sorted(cd.glob("ch-*.md")):
                    # Only canonical ch-NN.md — skip revision snapshots (ch-NN.R.md).
                    if not re.fullmatch(r"ch-\d{2}\.md", f.name):
                        continue
                    yield ("chapter", series_slug, book_id, f.stem,
                           _chapter_title(f), f.read_text(encoding="utf-8"))
            bd = b / "bible"
            if bd.exists():
                for f in sorted(bd.glob("*.md")):
                    yield ("bible", series_slug, book_id, f.name,
                           f.stem, f.read_text(encoding="utf-8"))

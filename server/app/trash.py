"""Trash — deletion that can be undone (2.3, D33).

The archive is the only copy of the author's novel, so **delete never means
`rm`**. A chapter or a book is *moved* into
`archive/.katha/trash/<stamp>-<kind>-<slug>/`, beside a `trash.json` manifest
that records what it was, where it came from, and every path that moved. The app
then treats it as gone: index rows and search docs are dropped, the rail forgets
it.

Why `.katha/`: that directory is already git-ignored, hidden from
`list_books()` and never walked by the search indexer — so nothing in the trash
can leak back into the UI (no phantom series, no "ch-01" appearing twice), while
a misclick stays recoverable for as long as the author wants. Nothing ages out
on its own: an archive of markdown weighs nothing, and a surprise deletion is
exactly the thing this is here to prevent.

The manifest is the contract for restore: `moved` is a list of archive-relative
paths, so restoring puts every file back where it was — chapter, revision
snapshots, `.rev` counter, notes sidecar and the chapter's Muse thread alike.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

from . import archive as ar
from .config import ARCHIVE_ROOT

MANIFEST = "trash.json"
_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,120}")


def trash_root() -> Path:
    root = ARCHIVE_ROOT / ".katha" / "trash"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _stamp() -> str:
    # UTC, sortable, filename-safe — reads like 20261107-145530.
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def _rel(path: Path) -> str:
    """Archive-relative posix path (the only form a manifest stores)."""
    try:
        return path.resolve().relative_to(ARCHIVE_ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return path.name


def _entry_id(kind: str, label: str) -> str:
    slug = ar.slugify(label or "") or kind
    root = trash_root()
    candidate = f"{_stamp()}-{kind}-{slug}"
    n = 1
    while (root / candidate).exists():
        n += 1
        candidate = f"{_stamp()}-{kind}-{slug}-{n}"
    return candidate


def move_to_trash(
    paths: list[Path],
    *,
    kind: str,
    label: str,
    series: str,
    book_id: str,
    chapter_id: str | None = None,
    words: int = 0,
) -> dict:
    """Move every existing path into a fresh trash entry; write the manifest.

    Returns the manifest (the API hands it straight back to the client).
    """
    entry_id = _entry_id(kind, label)
    entry = trash_root() / entry_id
    entry.mkdir(parents=True)

    moved: list[str] = []
    for src in paths:
        if not src or not src.exists():
            continue
        rel = _rel(src)
        dest = entry / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved.append(rel)

    # A book that was the only one in its series leaves an empty series dir
    # behind; an empty dir is not a series (list_books would still list it).
    if kind == "book":
        series_dir = ARCHIVE_ROOT / series
        try:
            if series_dir.is_dir() and not any(series_dir.iterdir()):
                series_dir.rmdir()
        except OSError:
            pass

    manifest = {
        "entry": entry_id,
        "kind": kind,
        "label": label,
        "deleted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "series": series,
        "book_id": book_id,
        "chapter_id": chapter_id,
        "words": words,
        "moved": moved,
        "restored_at": None,
    }
    (entry / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def entry_dir(entry_id: str) -> Path | None:
    """Resolve a trash entry id to its directory, or None.

    The id is a path segment chosen by the client, so this is a security
    boundary: single segment, no dots-only, no separators, and the resolved
    path must stay inside the trash root.
    """
    if not entry_id or not _ID_RE.fullmatch(entry_id) or set(entry_id) <= {"."}:
        return None
    root = trash_root().resolve()
    candidate = (root / entry_id).resolve()
    if candidate.parent != root or not candidate.is_dir():
        return None
    return candidate


def read_manifest(entry_id: str) -> dict | None:
    d = entry_dir(entry_id)
    if d is None:
        return None
    path = d / MANIFEST
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_trash() -> list[dict]:
    """Every restorable entry, newest first, with size numbers for the UI."""
    out: list[dict] = []
    for d in sorted(trash_root().iterdir()):
        if not d.is_dir():
            continue
        data = read_manifest(d.name)
        if data is None:
            continue
        files = [p for p in d.rglob("*") if p.is_file() and p.name != MANIFEST]
        data["files"] = len(files)
        data["bytes"] = sum(p.stat().st_size for p in files)
        out.append(data)
    out.sort(key=lambda m: (m.get("deleted_at") or "", m.get("entry") or ""), reverse=True)
    return out


def restore(entry_id: str) -> dict | None:
    """Move an entry's files back to their original archive-relative paths.

    Refuses (returns None, moving nothing) if *any* destination is occupied: a
    chapter id can be reused after a delete, and overwriting the new chapter to
    resurrect the old one would be the worst possible outcome.
    """
    data = read_manifest(entry_id)
    if data is None:
        return None
    d = entry_dir(entry_id)
    if d is None:
        return None

    moves: list[tuple[Path, Path]] = []
    for rel in data.get("moved") or []:
        src = d / rel
        if not src.exists():
            continue
        dest = ARCHIVE_ROOT / rel
        moves.append((src, dest))

    if not moves:
        return None
    if any(dest.exists() for _, dest in moves):
        return None

    for src, dest in moves:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))

    # Clean up: the manifest, then the entry tree if it is now empty.
    (d / MANIFEST).unlink(missing_ok=True)
    shutil.rmtree(d, ignore_errors=True)

    data["restored_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return data


# --- "what exactly will go?" (the confirm dialog reads these) ----------------

def count_threads(book_id: str, chapter_id: str) -> int:
    """Exchanges in a chapter's book-scoped Muse thread
    (one `<!-- katha:user -->` each). Counts only what a delete would move."""
    path = ARCHIVE_ROOT / ".katha" / "muse" / f"{book_id}-{chapter_id}.md"
    if not path.is_file():
        return 0
    try:
        return path.read_text(encoding="utf-8").count("<!-- katha:user -->")
    except OSError:
        return 0


def thread_path_for(book_id: str, chapter_id: str) -> Path:
    """Where a chapter's Muse thread lives (book-scoped, 2.4)."""
    return ARCHIVE_ROOT / ".katha" / "muse" / f"{book_id}-{chapter_id}.md"


def chapter_paths(book: Path, chapter_id: str) -> list[Path]:
    """Every file that belongs to one chapter and must move together.

    The Muse thread is the *book-scoped* name (`<book>-<chapter>.md`, 2.4). The
    legacy chapter-only files are deliberately left alone: their names are shared
    across books, so moving one could steal another book's conversation.
    """
    chapters = book / "chapters"
    out = [p for p in chapters.glob(f"{chapter_id}*") if p.is_file()]
    thread = thread_path_for(book.name, chapter_id)
    if thread.is_file():
        out.append(thread)
    return sorted(out)


def book_thread_paths(book: Path) -> list[Path]:
    """Book-scoped Muse threads for every chapter of `book`."""
    chapters = book / "chapters"
    if not chapters.is_dir():
        return []
    out = []
    for f in ar.chapter_files(chapters):
        p = thread_path_for(book.name, f.stem)
        if p.is_file():
            out.append(p)
    return out


def bible_paths(book: Path, name: str) -> list[Path]:
    """The bible file — or whole bible folder — at a *validated* relative path.

    `ar.safe_bible_path()` is the same guard the editor writes through, so a
    path that escapes the archive, hides in a dot-dir, or isn't markdown simply
    resolves to nothing.
    """
    p = ar.safe_bible_path(book, name)
    return [p] if p is not None and p.exists() else []


def series_paths(series: str) -> list[Path]:
    """A whole series: its directory (books + series.json) and every book-scoped
    Muse thread belonging to it."""
    sd = ARCHIVE_ROOT / series
    out: list[Path] = [sd]
    if sd.is_dir():
        for b in sorted(p for p in sd.iterdir() if p.is_dir() and not p.name.startswith(".")):
            out.extend(book_thread_paths(b))
    return out


def series_books(series: str) -> list[Path]:
    sd = ARCHIVE_ROOT / series
    if not sd.is_dir():
        return []
    return [p for p in sorted(sd.iterdir()) if p.is_dir() and not p.name.startswith(".")]


def series_json_path(series: str) -> Path:
    return ARCHIVE_ROOT / series / "series.json"


def is_last_book(series: str, book_id: str) -> bool:
    """True when `book_id` is the only real book left in its series.

    Matters because `series.json` lives *beside* the book, not inside it: trash
    the last book and leave the json, and the rail gets a series with no books.
    So the json rides along — and restore puts it back.
    """
    sd = ARCHIVE_ROOT / series
    if not sd.is_dir():
        return False
    others = [
        p for p in sd.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name != book_id
    ]
    return not others


def purge(entry_id: str) -> dict | None:
    """Erase ONE trash entry for real. Returns what was freed, or None if the
    entry is unknown.

    The only place in Katha that destroys anything (D36): delete moves, and this
    is the deliberate second step someone has to ask for, per entry or wholesale.
    """
    path = entry_dir(entry_id)
    data = read_manifest(entry_id)
    if path is None or data is None or not path.exists():
        return None
    files, size = size_of([path])
    shutil.rmtree(path)
    return {
        "entry": entry_id,
        "kind": data.get("kind"),
        "label": data.get("label"),
        "series": data.get("series"),
        "book_id": data.get("book_id"),
        "files": files,
        "bytes": size,
    }


def purge_all() -> dict:
    """Empty the trash: erase every entry, report the total freed."""
    entries = list_trash()
    freed = 0
    files = 0
    for e in entries:
        got = purge(e["entry"])
        if got:
            freed += got["bytes"]
            files += got["files"]
    return {"purged": len(entries), "files": files, "bytes": freed}


def size_of(paths: list[Path]) -> tuple[int, int]:
    """(files, bytes) for a list of files or directories."""
    files = 0
    size = 0
    for p in paths:
        if p is None or not p.exists():
            continue
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    files += 1
                    size += f.stat().st_size
        else:
            files += 1
            size += p.stat().st_size
    return files, size

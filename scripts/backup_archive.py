#!/usr/bin/env python3
"""Nightly snapshot of the Katha archive — the only copy of the author's novels.

The archive is plain Markdown (``series/book/chapters/*.md`` + ``bible/``) and the
sqlite file beside it is a rebuildable *index*, not truth. So this job snapshots
both, the same way the other services on this host do it: a dated tarball plus a
consistent SQLite copy, keeping the last N, all on the box.

Two things it does NOT pretend to be:

* **Not off-box.** The snapshots land in ``$KATHA_BACKUP_DIR`` on the same SD
  card as the live archive. It protects against a bad edit, a bad deploy and a
  corrupted index — not against the card dying. Adding an rclone/gdrive leg later
  is a few lines; until then this is a fast local safety net, deliberately.
* **Not a git history.** ``archive/`` is git-ignored by convention, so nothing
  else in the pipeline versions the prose.

Run by ``katha-archive-backup.timer`` (daily 03:30, on the deploy host). Prints a
summary and exits non-zero on failure so systemd records it.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sqlite3
import sys
import tarfile
import time

KEEP = int(os.getenv("KATHA_BACKUP_KEEP", "14"))
ARCHIVE = pathlib.Path(os.getenv("KATHA_ARCHIVE_DIR", pathlib.Path.home() / "katha" / "archive"))
INDEX = pathlib.Path(os.getenv("KATHA_INDEX_DIR", pathlib.Path.home() / "katha" / "index"))
DB = INDEX / "katha.db"
DEST = pathlib.Path(os.getenv("KATHA_BACKUP_DIR", pathlib.Path.home() / "katha" / "backups"))

STAMP = time.strftime("%Y-%m-%d_%H%M%S")


def prune(pattern: str) -> int:
    """Keep the newest KEEP files matching *pattern*; return how many were dropped."""
    files = sorted(DEST.glob(pattern))
    dropped = 0
    for old in files[:-KEEP] if len(files) > KEEP else []:
        old.unlink(missing_ok=True)
        dropped += 1
    return dropped


def main() -> int:
    if not ARCHIVE.is_dir():
        print(f"FAIL: archive dir missing: {ARCHIVE}", file=sys.stderr)
        return 1
    md = [p for p in ARCHIVE.rglob("*") if p.is_file()]
    if not md:
        print(f"FAIL: archive is empty: {ARCHIVE} — refusing to snapshot nothing", file=sys.stderr)
        return 1

    DEST.mkdir(parents=True, exist_ok=True)

    # 1. the prose, as it sits on disk
    tar_path = DEST / f"archive-{STAMP}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(ARCHIVE, arcname="archive")

    # 2. the index, via SQLite's backup API so a running server can't hand us a
    #    torn file (same trick as wedding-cards/scripts/backup_db.py)
    db_path = db_note = None
    if DB.is_file():
        db_path = DEST / f"katha-{STAMP}.db"
        src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(db_path)
            try:
                src.backup(dst)
                ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                dst.close()
        finally:
            src.close()
        if ok != "ok":
            print(f"FAIL: index integrity_check said {ok!r}", file=sys.stderr)
            return 1
        db_note = f"db integrity=ok ({db_path.stat().st_size} B)"
    else:
        db_note = "no index yet (rebuildable — skipped)"

    pruned = prune("archive-*.tar.gz") + prune("katha-*.db")

    print(f"archive snapshot: {len(md)} files -> {tar_path.name} ({tar_path.stat().st_size} B)")
    print(f"index snapshot:   {db_note}")
    print(f"kept last {KEEP}, pruned {pruned} (in {DEST})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

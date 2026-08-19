"""Katha Archive — FastAPI + SQLite (index-only) over an md archive.

Design (D6, D9, D14):
- The archive IS the files: series/book/chapters/ch-XX.md, bible/, book.json.
- SQLite holds an INDEX only (chapters, revisions meta). Never the truth.
- Every content save writes the .md file AND records a full-snapshot revision.
"""

from __future__ import annotations

import os
from pathlib import Path

# Root of the md archive (source of truth). Overridable for tests/deploy.
ARCHIVE_ROOT = Path(os.environ.get("KATHA_ARCHIVE", Path(__file__).resolve().parent.parent / "archive"))

# SQLite index location (overridable for tests; in prod this is a volume).
DATA_DIR = Path(os.environ.get("KATHA_DATA", Path(__file__).resolve().parent.parent / "data"))
DB_PATH = DATA_DIR / "katha.db"

# Version stamp for the health check heartbeat (D13/D14).
VERSION = "0.2.1"

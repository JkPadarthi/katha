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
VERSION = "0.3.1"

# --- Muse upstream (0.3 Muse, D16/D19) ----------------------------------------
# Friend's jenga box — direct Ollama, trusted LAN. No key needed.
OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://100.77.183.77:11434")
MUSE_MODEL = os.environ.get("MUSE_MODEL", "deepseek-r1:14b")
MUSE_FALLBACK_MODEL = os.environ.get("MUSE_FALLBACK_MODEL", "gemma4:26b")
# Chat uses a faster non-thinking model — deepseek-r1 burns 5–30s on internal
# reasoning per reply, which feels broken for chat. Rewrite keeps the thinking
# model because the planning genuinely improves output.
MUSE_CHAT_MODEL = os.environ.get("MUSE_CHAT_MODEL", "gemma4:12b")
MUSE_REWRITE_MODEL = os.environ.get("MUSE_REWRITE_MODEL", "deepseek-r1:14b")
# Token budgets. We're well under deepseek-r1's 131K context; cap conservatively.
MUSECONTEXT_MAX_TOKENS = int(os.environ.get("MUSECONTEXT_MAX_TOKENS", "6000"))
MUSE_NUM_PREDICT = int(os.environ.get("MUSE_NUM_PREDICT", "4096"))
MUSE_STYLE_PROSE_CHAPTERS = int(os.environ.get("MUSE_STYLE_PROSE_CHAPTERS", "3"))
# HTTP timeout for the upstream Ollama call. Streaming responses can take long.
MUSE_UPSTREAM_TIMEOUT = float(os.environ.get("MUSE_UPSTREAM_TIMEOUT", "300"))

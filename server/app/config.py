"""Katha Archive — FastAPI + SQLite (index-only) over an md archive.

Design (D6, D9, D14):
- The archive IS the files: series/book/chapters/ch-XX.md, bible/, book.json.
- SQLite holds an INDEX only (chapters, revisions meta). Never the truth.
- Every content save writes the .md file AND records a full-snapshot revision.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

# Root of the md archive (source of truth). Overridable for tests/deploy.
ARCHIVE_ROOT = Path(os.environ.get("KATHA_ARCHIVE", Path(__file__).resolve().parent.parent / "archive"))

# SQLite index location (overridable for tests; in prod this is a volume).
DATA_DIR = Path(os.environ.get("KATHA_DATA", Path(__file__).resolve().parent.parent / "data"))
DB_PATH = DATA_DIR / "katha.db"

# Built PWA client, served by this same server at `/` — one origin, one port
# (required for service-worker install over Tailscale). Absent in bare-API
# dev; the static mount is skipped when the directory doesn't exist.
WEB_DIR = Path(os.environ.get(
    "KATHA_WEB_DIR",
    Path(__file__).resolve().parent.parent.parent / "desktop" / "dist",
))

# Version stamp for the health check heartbeat (D13/D14).
VERSION = "2.9.2"

# --- Muse upstream (0.3 Muse, D16/D19; dialect switch 2.1, D20-D23) -----------
# Which wire dialect the Muse talks. "ollama" is the LAN box (unchanged
# default); "openai" is any OpenAI-compatible /chat/completions gateway;
# "anthropic" is a Messages-shape gateway (POST {base}/messages, x-api-key) —
# some providers serve Claude models ONLY that way, and say so per model in
# `GET /models` under `supported_endpoints`.
MUSE_API = os.environ.get("KATHA_MUSE_API", "ollama").strip().lower()
# Base URL for the keyed dialects, INCLUDING any version segment —
# e.g. https://openrouter.ai/api/v1 or https://api.commandcode.ai/provider/v1.
# Ignored in ollama mode.
MUSE_API_BASE = os.environ.get("KATHA_MUSE_API_BASE", "").strip()
# Key/token for the keyed dialects (Bearer for openai, x-api-key for anthropic).
# Sent as a header only: never logged, never returned by any endpoint, never
# echoed in an error message.
MUSE_API_KEY = os.environ.get("KATHA_MUSE_API_KEY", "").strip()

# Friend's jenga box — direct Ollama, trusted LAN. No key needed.
# UNTOUCHED by the dialect switch: when the box comes back, KATHA_MUSE_API=ollama
# is all it takes.
OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://100.77.183.77:11434")
# Rewrite, canon sweep, and the style digest all use the thinking model —
# the planning genuinely improves prose output. Defaults are per dialect (an
# explicit env value always wins, so the ollama names are what 2.0.1 used); a
# keyed dialect must never come up with an empty model name.
_AGENT_DEFAULT = {"openai": "deepseek/deepseek-v4-flash",
                  "anthropic": "claude-sonnet-5-5"}.get(MUSE_API, "gemma4:12b")
_REWRITE_DEFAULT = {"openai": "deepseek/deepseek-v4-flash",
                    "anthropic": "claude-sonnet-5-5"}.get(MUSE_API, "deepseek-r1:14b")

MUSE_REWRITE_MODEL = (os.environ.get("MUSE_REWRITE_MODEL") or _REWRITE_DEFAULT)
# Agentic chat: the model drives tool calls to fetch story files on demand.
# Must be a tool-capable model (gemma4/qwen3/llama3.1/…); deepseek-r1 is not.
# MUSE_CHAT_MODEL is kept as a legacy alias for the same setting.
MUSE_AGENT_MODEL = (
    os.environ.get("MUSE_AGENT_MODEL")
    or os.environ.get("MUSE_CHAT_MODEL")
    or _AGENT_DEFAULT
)
# Upper bound on tool-call rounds in a single agentic reply (latency guard).
MUSE_MAX_TOOL_ROUNDS = int(os.environ.get("KATHA_MUSE_MAX_TOOL_ROUNDS", "6"))
# Token budgets. We're well under deepseek-r1's 131K context; cap conservatively.
MUSECONTEXT_MAX_TOKENS = int(os.environ.get("MUSECONTEXT_MAX_TOKENS", "6000"))
MUSE_NUM_PREDICT = int(os.environ.get("MUSE_NUM_PREDICT", "4096"))
# The agentic chat is the one call that may have to write a WHOLE CHAPTER into a tool
# argument, so it gets its own, much larger, output ceiling: 4096 tokens cannot hold a
# 5,000-word chapter, and a truncated tool call used to look like an empty handover
# (2.9.1, D46). Only *generated* tokens cost anything — the ceiling is just a bound.
# The gateway accepts at least 64k; 32k covers a chapter of roughly 20k words.
MUSE_AGENT_MAX_TOKENS = int(os.environ.get("MUSE_AGENT_MAX_TOKENS", "32000"))
MUSE_STYLE_PROSE_CHAPTERS = int(os.environ.get("MUSE_STYLE_PROSE_CHAPTERS", "3"))
# HTTP timeout for the upstream call. Streaming responses can take long, but the
# CONNECT step gets its own short budget: a blackholed/dead host must fail in
# seconds and surface as an SSE `[ERROR]`, not freeze the Muse for 300s (D23).
MUSE_UPSTREAM_TIMEOUT = float(os.environ.get("MUSE_UPSTREAM_TIMEOUT", "300"))
MUSE_UPSTREAM_CONNECT_TIMEOUT = float(os.environ.get("MUSE_UPSTREAM_CONNECT_TIMEOUT", "10"))

# --- The door (2.2, D32 — supersedes D12's "Tailscale is the boundary") -------
# One password in front of everything except the login page. EMPTY = no lock, so
# dev/tailnet installs boot exactly like 2.0.x and the test suite stays open by
# default. The password is hashed at boot (scrypt) — never compared in plaintext.
PASSWORD = os.environ.get("KATHA_PASSWORD", "")
# Cookie signing key. Unset ⇒ derived from the password, which means one secret
# to manage and rotating the password invalidates every existing session.
SECRET_KEY = os.environ.get("KATHA_SECRET_KEY", "")
# How long a session lasts before the password is asked again (30 days).
SESSION_SECONDS = int(os.environ.get("KATHA_SESSION_SECONDS", str(30 * 24 * 3600)))
COOKIE_NAME = os.environ.get("KATHA_COOKIE_NAME", "katha_session")
# "auto" (default) sets Secure on the cookie only when the login arrived over
# TLS; "1" forces it (use behind a TLS-terminating proxy); "0" never.
COOKIE_SECURE = os.environ.get("KATHA_COOKIE_SECURE", "auto").strip().lower()

# Allowed browser origins (comma-separated env). The old wildcard let ANY
# website the author visits read/rewrite the archive cross-origin. "null"
# covers the packaged Electron renderer loading file://.
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "KATHA_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,null",
    ).split(",")
    if o.strip()
]

# Daily word goal for the writing-ritual streak (1.0). The client may override
# per-request; this is the default when it doesn't.
DAILY_GOAL = int(os.environ.get("KATHA_DAILY_GOAL", "500"))

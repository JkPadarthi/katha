"""Settings the author changes in the app, not in an env file (3.2, D62).

The Muse's connection (dialect, address, key, models) and the lock's password used
to be environment-only: changing either meant SSH, an editor and a container
restart. They can now be changed from Settings, and this module is where they live.

* **Where**: `KATHA_DATA/settings.json` — the index directory, which is outside the
  checkout on the deploy host (D25) and is *not* in the nightly backup (that takes
  the Markdown and a copy of the SQLite file, nothing else), so the API key is not
  copied into a tarball. Written atomically, mode 0600.
* **What**: the password only as a scrypt hash with its own random salt — never the
  password itself; the API key as given (it has to be sent upstream), never returned
  by any endpoint.
* **Precedence**: a value set here wins over the environment; a value never set
  here falls back to the environment, so an install that never opens these settings
  behaves exactly as before.

`apply()` pushes the effective values into the module globals the rest of the app
already reads at call time (`upstream.MUSE_API…`, `muse.MUSE_AGENT_MODEL…`,
`auth.PASSWORD_HASH`) — the same globals the test suite monkeypatches, so nothing
downstream had to learn about this file.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
from pathlib import Path

from . import config

DIALECTS = ("ollama", "openai", "messages")
_ALIASES = {"anthropic": "messages"}

# scrypt parameters for the stored password (same cost as auth.hash_password).
_N, _R, _P = 2 ** 14, 8, 1


def path() -> Path:
    return config.DATA_DIR / "settings.json"


def load() -> dict:
    p = path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save(data: dict) -> None:
    """Atomic, owner-only write: a crash mid-write must not leave half a key."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".settings-", suffix=".json")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.chmod(p, 0o600)


# --- the password ------------------------------------------------------------

def hash_password(password: str, salt: bytes | None = None) -> dict:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=64)
    return {"salt": salt.hex(), "hash": digest.hex()}


def check_password(password: str, stored: dict) -> bool:
    try:
        salt = bytes.fromhex(stored["salt"])
        want = bytes.fromhex(stored["hash"])
    except (KeyError, ValueError, TypeError):
        return False
    got = hashlib.scrypt((password or "").encode(), salt=salt, n=_N, r=_R, p=_P, dklen=64)
    return hmac.compare_digest(got, want)


# --- the Muse's connection -----------------------------------------------------

def normalize_dialect(api: str) -> str:
    api = (api or "").strip().lower()
    return _ALIASES.get(api, api)


def default_models(api: str) -> tuple[str, str]:
    """(agent, rewrite) defaults for a dialect — the same table config.py uses."""
    api = normalize_dialect(api)
    if api == "openai":
        return "deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-flash"
    if api == "messages":
        return "claude-sonnet-5-5", "claude-sonnet-5-5"
    return "gemma4:12b", "deepseek-r1:14b"


def effective_muse(data: dict | None = None) -> dict:
    """The connection the Muse actually uses: stored values over the environment."""
    data = load() if data is None else data
    m = data.get("muse") or {}
    api = normalize_dialect(m.get("api") or config.MUSE_API) or "ollama"
    if api == "ollama":
        base = m["base"] if "base" in m else config.OLLAMA_BASE
    else:
        base = m["base"] if "base" in m else config.MUSE_API_BASE
    key = m["key"] if "key" in m else config.MUSE_API_KEY
    if m.get("api"):
        # The dialect was chosen here, so env model names (written for the env's
        # dialect) don't apply: blank means this dialect's defaults.
        agent_d, rewrite_d = default_models(api)
        agent = m.get("agent_model") or agent_d
        rewrite = m.get("rewrite_model") or rewrite_d
    else:
        agent = m.get("agent_model") or config.MUSE_AGENT_MODEL
        rewrite = m.get("rewrite_model") or config.MUSE_REWRITE_MODEL
    return {
        "api": api,
        "base": (base or "").strip(),
        "key": key or "",
        "agent_model": agent,
        "rewrite_model": rewrite,
        "source": "app" if m else "environment",
    }


def key_hint(key: str) -> str:
    """Enough to recognise a key, not enough to use it."""
    if not key:
        return ""
    return "…" + key[-4:] if len(key) >= 12 else "set"


# --- pushing it live -----------------------------------------------------------

def apply(data: dict | None = None) -> None:
    """Make the stored settings the live ones, without a restart."""
    from . import auth
    from . import muse as muse_mod
    from . import upstream as up_mod

    data = load() if data is None else data

    eff = effective_muse(data)
    up_mod.MUSE_API = eff["api"]
    if eff["api"] == "ollama":
        up_mod.OLLAMA_BASE = eff["base"] or config.OLLAMA_BASE
        up_mod.MUSE_API_BASE = ""
    else:
        up_mod.MUSE_API_BASE = eff["base"]
    up_mod.MUSE_API_KEY = eff["key"]
    muse_mod.MUSE_AGENT_MODEL = eff["agent_model"]
    muse_mod.MUSE_REWRITE_MODEL = eff["rewrite_model"]
    muse_mod.MUSE_COMPLETE_MODEL = (os.environ.get("MUSE_COMPLETE_MODEL")
                                    or eff["agent_model"])

    pw = data.get("password") or {}
    if pw.get("disabled"):
        auth.PASSWORD_HASH = None
        auth.LOCK_DISABLED = True
    elif pw.get("hash"):
        auth.PASSWORD_HASH = pw
        auth.LOCK_DISABLED = False
    else:
        auth.PASSWORD_HASH = None
        auth.LOCK_DISABLED = False

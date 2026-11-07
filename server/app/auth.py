"""The lock on the door (2.2, D32 — supersedes D12).

Katha was tailnet-only by design: single author, no authentication, Tailscale was
the boundary. It now sits in front of the novels on a host that can be exposed
beyond the tailnet, so there is **one password** and everything except the login
page itself is behind it.

Shape:

* `KATHA_PASSWORD` (plaintext, env) is hashed **at boot** with scrypt — the house
  pattern from Recruit (`n=2**14, r=8, p=1`, salt = sha256 of the signing key).
  Nothing plaintext is ever compared against, and no user table exists.
* The password is **optional**: empty means no lock, so dev/tailnet installs and
  the existing test suite boot exactly like 2.0.x.
* Sessions are a signed cookie (`katha_session`), 30 days by default, carrying
  only an issued-at/expiry stamp and a nonce — no user data, nothing to steal
  from the client but the door key itself.
* The signing key is derived from the password when `KATHA_SECRET_KEY` is unset:
  one secret to manage, and rotating the password invalidates every session.
* Everything in here reads `PASSWORD` / `SECRET_KEY` from module attributes, so
  tests can flip the lock on and off per test without re-importing the app.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from .config import COOKIE_NAME, COOKIE_SECURE, SESSION_SECONDS
from .config import PASSWORD as _CFG_PASSWORD
from .config import SECRET_KEY as _CFG_SECRET_KEY

# Live values (monkeypatchable; config supplies the initial ones).
PASSWORD = _CFG_PASSWORD
SECRET_KEY = _CFG_SECRET_KEY

# --- paths that stay reachable without a session -------------------------------

# /api/health is public on purpose: the container's own healthcheck calls it from
# inside the container with no cookie, and a 401 there would make every deploy
# look unhealthy and trip the CD auto-rollback.
PUBLIC_PREFIXES = (
    "/login",
    "/api/auth/",
    "/api/health",
    "/sw.js",
    "/manifest.webmanifest",
    "/favicon",
    "/icon",
    "/apple-touch-icon",
)
# The mark itself is public too (EXACT, not a prefix): the login card shows it
# before anyone is signed in, and `/logo.svg/anything` must not inherit that.
PUBLIC_EXACT = {"/login", "/api/health", "/sw.js", "/manifest.webmanifest", "/logo.svg"}


def is_public(path: str) -> bool:
    """True when `path` may be served to an unauthenticated visitor."""
    if path in PUBLIC_EXACT:
        return True
    return any(path.startswith(p) for p in PUBLIC_PREFIXES)


# --- secret + hashing ---------------------------------------------------------

def enabled() -> bool:
    """The lock is only armed when a password is configured."""
    return bool(PASSWORD)


def signing_key() -> str:
    if SECRET_KEY:
        return SECRET_KEY
    # Derived: rotating the password silently invalidates every session.
    return hashlib.sha256(f"katha-auth-v1:{PASSWORD}".encode()).hexdigest()


def hash_password(password: str) -> str:
    """scrypt, same parameters as Recruit's house helper."""
    salt = hashlib.sha256(signing_key().encode()).digest()
    return hashlib.scrypt(
        (password or "").encode(), salt=salt, n=2**14, r=8, p=1, dklen=64
    ).hex()


def verify(password: str) -> bool:
    """Constant-time check. Always False when no password is configured."""
    if not enabled():
        return False
    return hmac.compare_digest(hash_password(password), hash_password(PASSWORD))


# --- brute-force throttle (in-process; single author, no shared store) ---------

MAX_FAILS = 8
WINDOW_S = 15 * 60
_FAILS: dict[str, list[float]] = {}


def blocked(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _FAILS.get(ip, []) if now - t < WINDOW_S]
    _FAILS[ip] = hits
    return len(hits) >= MAX_FAILS


def record_failure(ip: str) -> None:
    _FAILS.setdefault(ip, []).append(time.time())


def clear_failures(ip: str) -> None:
    _FAILS.pop(ip, None)


# --- session token ------------------------------------------------------------

def issue_token() -> str:
    now = int(time.time())
    payload = {"iat": now, "exp": now + SESSION_SECONDS, "n": secrets.token_urlsafe(8)}
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).rstrip(b"=")
    sig = hmac.new(signing_key().encode(), raw, hashlib.sha256).digest()
    return raw.decode() + "." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def valid_token(token: str | None) -> bool:
    """Signature + expiry. Any malformed input is simply not valid."""
    if not enabled() or not token or "." not in token:
        return False
    raw, sig = token.split(".", 1)
    expected = hmac.new(signing_key().encode(), raw.encode(), hashlib.sha256).digest()
    try:
        got = _b64d(sig)
    except Exception:
        return False
    if not hmac.compare_digest(got, expected):
        return False
    try:
        payload = json.loads(_b64d(raw))
    except Exception:
        return False
    try:
        return int(payload.get("exp", 0)) > time.time()
    except (TypeError, ValueError):
        return False


def cookie_kwargs(request) -> dict:
    """Cookie attributes for the login response.

    `Secure` is auto by default: set it when the login itself arrived over TLS
    (or when KATHA_COOKIE_SECURE=1 forces it). On the tailnet the app is served
    over plain http — Tailscale already encrypts the wire — and a Secure cookie
    there would simply never be sent back, locking the author out.
    """
    secure = COOKIE_SECURE in ("1", "true", "yes", "on")
    if COOKIE_SECURE == "auto":
        secure = request.url.scheme == "https" or request.headers.get(
            "x-forwarded-proto", ""
        ) == "https"
    return {
        "key": COOKIE_NAME,
        "httponly": True,   # no JS access: an XSS in the SPA can't exfiltrate it
        "samesite": "lax",
        "secure": secure,
        "max_age": SESSION_SECONDS,
        "path": "/",
    }


# --- the login page (self-contained, themed) ----------------------------------

# No build step and no SPA: this page must render before the app bundle is even
# reachable. It carries the same three token sets as desktop/src/index.css and
# follows the same rule as the app — the OS decides until the author chooses
# (`localStorage["katha.theme"]`, JSON-encoded, written by lib/settings.js).
LOGIN_HTML = """<!doctype html>
<html lang="en" data-theme="hermes">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0e0e12">
<title>Katha — locked</title>
<script>
  // Same contract as the app shell: stored choice wins, otherwise follow the OS.
  try {
    var pref = JSON.parse(localStorage.getItem('katha.theme') || 'null');
    var theme = (pref === 'paper' || pref === 'slate' || pref === 'hermes')
      ? pref
      : (window.matchMedia('(prefers-color-scheme: light)').matches ? 'paper' : 'hermes');
    document.documentElement.dataset.theme = theme;
  } catch (e) { /* storage unavailable — Hermes it is */ }
</script>
<style>
  /* Katha design tokens — kept in sync with desktop/src/index.css */
  html[data-theme="hermes"] {
    color-scheme: dark;
    --base:#0e0e12; --panel:#131318; --panel2:#1a1a22; --line:#26262e;
    --ink:#e8e6e0; --mute:#8f8f98; --accent:#ffbf00; --onaccent:#0e0e12;
    --err:#ff6b7d; --serif:"Georgia","Iowan Old Style","Times New Roman",serif;
  }
  html[data-theme="paper"] {
    color-scheme: light;
    --base:#f6f1e7; --panel:#efe7d8; --panel2:#e6dbc7; --line:#d9ccb2;
    --ink:#2a241c; --mute:#6e6353; --accent:#9a5b17; --onaccent:#fbf7ef;
    --err:#b23b3b; --serif:"Iowan Old Style","Palatino Linotype",Georgia,serif;
  }
  html[data-theme="slate"] {
    color-scheme: dark;
    --base:#0f1419; --panel:#151b22; --panel2:#1c242e; --line:#263240;
    --ink:#dbe4ee; --mute:#8494a6; --accent:#5aa2f0; --onaccent:#0b1220;
    --err:#f87171; --serif:"Georgia","Iowan Old Style",serif;
  }
  * { box-sizing: border-box; }
  body {
    margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
    background:var(--base); color:var(--ink);
    font-family:"Inter","Segoe UI",system-ui,sans-serif; font-size:13.5px;
    -webkit-tap-highlight-color:transparent;
  }
  .card {
    width:min(92vw,360px); background:var(--panel); border:1px solid var(--line);
    border-radius:10px; padding:26px 24px 22px;
    box-shadow:0 18px 50px rgba(0,0,0,.28);
  }
  .mark { display:flex; align-items:center; gap:10px; margin-bottom:2px; }
  .mark img { width:28px; height:28px; border-radius:7px; display:block; }
  .mark b { color:var(--accent); font-size:10px; }
  h1 { font-family:var(--serif); font-size:23px; font-weight:600; margin:0; letter-spacing:.4px; }
  p.hint { color:var(--mute); font-size:12px; margin:6px 0 20px; }
  label { display:block; font-size:11px; color:var(--mute); margin-bottom:6px; }
  input {
    width:100%; padding:9px 11px; border-radius:7px; font-size:13.5px;
    background:var(--panel2); color:var(--ink); border:1px solid var(--line);
    font-family:inherit; outline:none;
  }
  input:focus { border-color:var(--accent); }
  button {
    width:100%; margin-top:14px; padding:9px 12px; border-radius:7px; cursor:pointer;
    background:var(--accent); color:var(--onaccent); border:1px solid var(--accent);
    font-weight:600; font-size:13px; font-family:inherit;
  }
  button:disabled { opacity:.6; cursor:default; }
  .err { color:var(--err); font-size:12px; margin:12px 0 0; min-height:15px; }
  .foot { color:var(--mute); font-size:10.5px; margin-top:18px; text-align:center; opacity:.75; }
</style>
</head>
<body>
  <main class="card">
    <div class="mark"><img src="/logo.svg" alt="" width="28" height="28"><h1>Katha</h1></div>
    <p class="hint">The archive is locked. Enter the password to continue.</p>
    <form id="f" autocomplete="on">
      <label for="p">Password</label>
      <input id="p" name="password" type="password" autocomplete="current-password"
             autofocus spellcheck="false" required>
      <button id="b" type="submit">Open Katha</button>
    </form>
    <p class="err" id="e" role="alert"></p>
    <p class="foot">कथा — your stories never leave this machine</p>
  </main>
<script>
  var form = document.getElementById('f');
  var input = document.getElementById('p');
  var button = document.getElementById('b');
  var err = document.getElementById('e');

  // Only ever redirect to a same-origin path: `?next=` is attacker-supplied.
  function nextPath() {
    try {
      var raw = new URLSearchParams(location.search).get('next') || '/';
      if (raw.charAt(0) !== '/' || raw.charAt(1) === '/') return '/';
      return raw;
    } catch (e) { return '/'; }
  }

  form.addEventListener('submit', async function (ev) {
    ev.preventDefault();
    err.textContent = '';
    button.disabled = true;
    button.textContent = 'Unlocking…';
    try {
      var res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ password: input.value })
      });
      if (res.ok) { location.replace(nextPath()); return; }
      var detail = '';
      try { detail = (await res.json()).detail || ''; } catch (e) {}
      err.textContent = res.status === 429
        ? 'Too many attempts. Wait a few minutes.'
        : (detail || "That password didn't work.");
    } catch (e) {
      err.textContent = 'Could not reach the server.';
    }
    button.disabled = false;
    button.textContent = 'Open Katha';
    input.select();
  });
</script>
</body>
</html>
"""

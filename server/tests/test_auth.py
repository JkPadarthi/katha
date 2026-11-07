"""Tests for the door (2.2, D32).

The lock is **optional**: `KATHA_PASSWORD` unset means no gate at all, which is
how dev/tailnet installs and the rest of this suite keep booting like 2.0.x. So
these tests arm it per test by patching `app.auth.PASSWORD` — the middleware and
the token helpers read it live, which is exactly why no re-import or env juggling
is needed here.

What must hold when armed: the PWA shell, every API route (Muse SSE included) and
the built assets are behind it; the login page, the PWA manifest/icons/sw and
`/api/health` are not (a browser fetches manifest+icons without credentials, and
the container's own healthcheck calls /api/health with no cookie — a 401 there
would mark every deploy unhealthy and trip the CD rollback).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_TMP = tempfile.mkdtemp(prefix="katha-auth-test-")
os.environ["KATHA_ARCHIVE"] = str(Path(_TMP) / "archive")
os.environ["KATHA_DATA"] = str(Path(_TMP) / "data")

from app import auth  # noqa: E402
from app import muse as muse_mod  # noqa: E402
from app.config import WEB_DIR  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
PW = "correct-horse-battery-staple"
COOKIE = "katha_session"


@pytest.fixture
def locked(monkeypatch: pytest.MonkeyPatch):
    """Arm the lock; derived signing key (SECRET_KEY unset)."""
    monkeypatch.setattr(auth, "PASSWORD", PW)
    monkeypatch.setattr(auth, "SECRET_KEY", "")
    auth._FAILS.clear()
    yield
    auth._FAILS.clear()
    client.cookies.clear()


def _sign_in(password: str = PW):
    return client.post("/api/auth/login", json={"password": password})


def _mint(exp_offset: int) -> str:
    """A correctly-signed token with an arbitrary expiry (for expiry tests)."""
    now = int(time.time())
    payload = {"iat": now, "exp": now + exp_offset, "n": "test"}
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).rstrip(b"=")
    sig = hmac.new(auth.signing_key().encode(), raw, hashlib.sha256).digest()
    return raw.decode() + "." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()


# --- disarmed (the default) ------------------------------------------------

def test_no_password_means_no_gate():
    """Unset password ⇒ open, exactly like 2.0.x. This is the switch that keeps
    dev and CI usable and the rest of the suite passing."""
    assert auth.enabled() is False
    assert client.get("/api/books").status_code == 200
    assert client.get("/api/health").status_code == 200


# --- armed: what is locked -------------------------------------------------

def test_api_requires_a_session(locked):
    r = client.get("/api/books")
    assert r.status_code == 401
    assert r.json()["detail"]


def test_page_requests_are_walked_to_the_login_screen(locked):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")
    # deep links carry where to come back to
    r2 = client.get("/some/deep/link", follow_redirects=False)
    assert r2.headers["location"] == "/login?next=/some/deep/link"


def test_static_assets_are_locked(locked):
    """The built client is behind the door too — assets and the shell alike are
    redirected to the login page, never served. (The gate runs before routing, so
    even a path that doesn't exist can't be probed.)"""
    for path in ("/assets/index-abc123.js", "/index.html", "/"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 303, path
        assert r.headers["location"].startswith("/login"), path


def test_muse_sse_requires_a_session(locked):
    """Streaming endpoints must 401 as JSON, not hand back an empty stream."""
    r = client.post("/api/muse/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 401


def test_public_endpoints_stay_public(locked):
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200


# --- the login page itself -------------------------------------------------

def test_login_page_renders_and_follows_the_themes(locked):
    r = client.get("/login")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    html = r.text
    # all three theme token sets, exactly as desktop/src/index.css defines them
    for token in ("#0e0e12", "#ffbf00", "#f6f1e7", "#9a5b17", "#0f1419", "#5aa2f0"):
        assert token in html, token
    assert "katha.theme" in html            # same OS-follow rule as the app
    assert 'type="password"' in html
    assert "data-theme" in html


def test_login_page_never_leaks_the_password(locked):
    assert PW not in client.get("/login").text


# --- armed: getting in -----------------------------------------------------

def test_wrong_password_is_rejected_without_a_cookie(locked):
    r = _sign_in("nope")
    assert r.status_code == 401
    assert COOKIE not in r.cookies
    assert "nope" not in r.text and PW not in r.text


def test_login_sets_a_long_httponly_cookie_and_unlocks_the_api(locked):
    r = _sign_in()
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["session_days"] == 30
    raw = r.headers["set-cookie"]
    assert "HttpOnly" in raw and "SameSite=lax" in raw and "Max-Age=2592000" in raw

    # the cookie the client kept now opens the door — API and shell alike
    assert client.get("/api/books").status_code == 200
    assert client.get("/api/muse/models").status_code == 200
    # The shell itself only exists when this checkout has a built client: main.py
    # skips the static mount when dist/ is absent (CI runs pytest without a build,
    # so asserting this unconditionally is a false green locally and a false red
    # in CI — which is exactly how this test first failed).
    if WEB_DIR.is_dir():
        assert client.get("/").status_code == 200
    # the login screen stays reachable even with a session (e.g. to switch user)
    assert client.get("/login").status_code == 200


def test_tampered_cookie_is_rejected(locked):
    _sign_in()
    good = client.cookies.get(COOKIE)
    assert good
    client.cookies.set(COOKIE, good[:-2] + ("aa" if not good.endswith("aa") else "bb"))
    assert client.get("/api/books").status_code == 401


def test_expired_cookie_is_rejected(locked):
    client.cookies.set(COOKIE, _mint(-60))      # expired a minute ago
    assert client.get("/api/books").status_code == 401
    client.cookies.set(COOKIE, _mint(3600))     # still good
    assert client.get("/api/books").status_code == 200


def test_cookie_signed_with_another_key_is_rejected(locked, monkeypatch: pytest.MonkeyPatch):
    token = _mint(3600)
    monkeypatch.setattr(auth, "SECRET_KEY", "a-different-key")
    client.cookies.set(COOKIE, token)
    assert client.get("/api/books").status_code == 401


def test_logout_ends_the_session(locked):
    _sign_in()
    assert client.get("/api/books").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/books").status_code == 401


def test_authenticated_muse_stream_is_allowed_through(locked, monkeypatch: pytest.MonkeyPatch):
    """The gate must not break SSE: with a session, the Muse streams as usual."""
    import httpx

    ndjson = b'{"model": "m", "message": {"role": "assistant", "content": "hello"}, "done": true}\n'

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=ndjson)

    monkeypatch.setattr(
        muse_mod, "_client", httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    )
    # Same client for the login and the stream: a fresh TestClient would have an
    # empty cookie jar and 401 for the wrong reason.
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": PW}).status_code == 200
        with c.stream("POST", "/api/muse/chat",
                      json={"messages": [{"role": "user", "content": "hi"}]}) as r:
            assert r.status_code == 200
            body = "".join(r.iter_text())
    assert "hello" in body


def test_repeated_failures_are_throttled(locked):
    for _ in range(auth.MAX_FAILS):
        assert _sign_in("wrong").status_code == 401
    r = _sign_in("wrong")
    assert r.status_code == 429
    # and the throttle does not hand out a session
    assert COOKIE not in r.cookies


def test_the_mark_is_public_and_nothing_else_is():
    """The login card renders `/logo.svg` before anyone is signed in, so that one
    path is public. It is matched EXACTLY: a path that merely starts with it must
    not inherit the exemption."""
    assert auth.is_public("/logo.svg")
    assert auth.is_public("/icons/favicon-32.png")      # the PWA needs these too
    assert auth.is_public("/manifest.webmanifest")
    assert not auth.is_public("/logo.svg/anything")
    assert not auth.is_public("/api/books")
    assert not auth.is_public("/")

"""Settings changed in the app: the Muse's connection and the lock (3.2, D62).

What this net has to hold:

1. **The key never comes back.** No endpoint returns it — only whether one is set
   and its last four characters.
2. **Changes are live and durable.** A change takes effect on the next request
   (the module globals move) and survives a restart (the file is re-applied).
3. **The key follows its address.** Changing the base URL without re-entering the
   key clears it, so a key is never sent somewhere it wasn't given for.
4. **The current password guards both.** With the lock on, a wrong or missing
   current password is a 403 and nothing changes.
5. **A new password rotates every session** but keeps the device that changed it
   signed in; turning the lock off survives a restart even with KATHA_PASSWORD set.
6. **At rest**: the password only as a salted scrypt hash, the file owner-only.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

_TMP = tempfile.mkdtemp(prefix="katha-settings-test-")
os.environ["KATHA_ARCHIVE"] = str(Path(_TMP) / "archive")
os.environ["KATHA_DATA"] = str(Path(_TMP) / "data")

from app import auth  # noqa: E402
from app import muse as muse_mod  # noqa: E402
from app import settings_store as store  # noqa: E402
from app import upstream as up  # noqa: E402
from app.main import app  # noqa: E402

COOKIE = "katha_session"
PW = "correct-horse-battery-staple"
KEY = "sk-live-abcdefgh12345678WXYZ"

_GLOBALS = [
    (up, "MUSE_API"), (up, "MUSE_API_BASE"), (up, "MUSE_API_KEY"), (up, "OLLAMA_BASE"),
    (muse_mod, "MUSE_AGENT_MODEL"), (muse_mod, "MUSE_REWRITE_MODEL"),
    (muse_mod, "MUSE_COMPLETE_MODEL"),
    (auth, "PASSWORD"), (auth, "SECRET_KEY"), (auth, "PASSWORD_HASH"), (auth, "LOCK_DISABLED"),
]


@pytest.fixture(autouse=True)
def _isolated():
    """Every test starts unlocked with no settings file, and leaves nothing behind —
    apply() moves process-wide globals the rest of the suite relies on."""
    saved = [(m, n, getattr(m, n)) for m, n in _GLOBALS]
    store.path().unlink(missing_ok=True)
    auth.PASSWORD, auth.PASSWORD_HASH, auth.LOCK_DISABLED = "", None, False
    auth._FAILS.clear()
    yield
    store.path().unlink(missing_ok=True)
    for m, n, v in saved:
        setattr(m, n, v)
    auth._FAILS.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _lock_with_env_password(c: TestClient) -> None:
    auth.PASSWORD = PW
    r = c.post("/api/auth/login", json={"password": PW})
    assert r.status_code == 200


def _gateway(c: TestClient, **over) -> httpx.Response:
    body = {"api": "messages", "base": "https://gw.example.test/v1", "key": KEY,
            "agent_model": "", "rewrite_model": "", **over}
    return c.put("/api/settings/muse", json=body)


# --- 1. the key never comes back ------------------------------------------

def test_the_key_is_never_returned(client):
    r = _gateway(client)
    assert r.status_code == 200, r.text
    for resp in (r, client.get("/api/settings")):
        assert KEY not in resp.text
        m = resp.json()["muse"]
        assert m["key_set"] is True and m["key_hint"] == "…WXYZ"
        assert m["source"] == "app"


# --- 2. live and durable --------------------------------------------------

def test_a_change_is_live_without_a_restart(client):
    _gateway(client)
    assert up.MUSE_API == "messages" and up.MUSE_API_BASE == "https://gw.example.test/v1"
    assert up.MUSE_API_KEY == KEY
    # a dialect chosen here gets that dialect's model defaults, not the env's
    assert muse_mod.MUSE_AGENT_MODEL == "claude-sonnet-5-5"
    assert up.chat_url() == "https://gw.example.test/v1/messages"


def test_models_can_be_named(client):
    _gateway(client, agent_model="claude-opus-5-5", rewrite_model="claude-haiku-5-5")
    assert muse_mod.MUSE_AGENT_MODEL == "claude-opus-5-5"
    assert muse_mod.MUSE_REWRITE_MODEL == "claude-haiku-5-5"
    assert client.get("/api/settings").json()["muse"]["agent_model"] == "claude-opus-5-5"


def test_settings_survive_a_restart():
    with TestClient(app) as c:
        _gateway(c)
    up.MUSE_API, up.MUSE_API_KEY = "ollama", ""          # a fresh process
    with TestClient(app):                                 # lifespan re-applies
        assert up.MUSE_API == "messages" and up.MUSE_API_KEY == KEY


def test_ollama_mode_sets_the_lan_address(client):
    r = client.put("/api/settings/muse", json={"api": "ollama", "base": "http://10.0.0.5:11434"})
    assert r.status_code == 200
    assert up.MUSE_API == "ollama" and up.OLLAMA_BASE == "http://10.0.0.5:11434"
    assert up.chat_url() == "http://10.0.0.5:11434/api/chat"


def test_reset_goes_back_to_the_environment(client):
    _gateway(client)
    r = client.post("/api/settings/muse/reset", json={})
    assert r.status_code == 200
    assert r.json()["muse"]["source"] == "environment"
    assert up.MUSE_API == store.normalize_dialect(store.config.MUSE_API)


@pytest.mark.parametrize("body, needle", [
    ({"api": "smoke-signals"}, "unknown dialect"),
    ({"api": "openai", "base": "gw.example.test"}, "http:// or https://"),
    ({"api": "openai", "base": ""}, "needs its address"),
])
def test_bad_settings_are_refused_and_nothing_changes(client, body, needle):
    before = up.MUSE_API
    r = client.put("/api/settings/muse", json=body)
    assert r.status_code == 400 and needle in r.json()["detail"]
    assert up.MUSE_API == before and not store.path().exists()


# --- 3. the key follows its address ---------------------------------------

def test_changing_the_address_without_a_key_clears_the_key(client):
    _gateway(client)
    r = _gateway(client, base="https://elsewhere.example.test/v1", key=None)
    assert r.status_code == 200
    assert r.json()["muse"]["key_set"] is False and "cleared" in r.json()["note"]
    assert up.MUSE_API_KEY == ""


def test_same_address_without_a_key_keeps_it(client):
    _gateway(client)
    r = _gateway(client, key=None, agent_model="claude-opus-5-5")
    assert r.json()["muse"]["key_set"] is True and "note" not in r.json()
    assert up.MUSE_API_KEY == KEY


def test_an_empty_key_clears_it(client):
    _gateway(client)
    assert _gateway(client, key="").json()["muse"]["key_set"] is False


# --- 4. the current password guards both ----------------------------------

def test_muse_settings_need_the_current_password_when_locked(client):
    _lock_with_env_password(client)
    before = up.MUSE_API
    r = _gateway(client)                                       # none given
    assert r.status_code == 403
    r = _gateway(client, current_password="nope")
    assert r.status_code == 403 and up.MUSE_API == before
    assert _gateway(client, current_password=PW).status_code == 200


def test_the_settings_routes_are_behind_the_lock(client):
    auth.PASSWORD = PW
    client.cookies.clear()
    assert client.get("/api/settings").status_code == 401
    assert client.put("/api/settings/password", json={"new": "x" * 10}).status_code == 401


# --- 5. the password ------------------------------------------------------

def test_changing_the_password_rotates_sessions_but_keeps_this_one(client):
    _lock_with_env_password(client)
    old_cookie = client.cookies.get(COOKIE)
    r = client.put("/api/settings/password", json={"current": PW, "new": "a-new-passphrase"})
    assert r.status_code == 200, r.text
    assert r.json()["lock"] == {"enabled": True, "source": "app"}
    assert client.get("/api/books").status_code == 200, "this device stays signed in"

    other = TestClient(app)
    other.cookies.set(COOKIE, old_cookie)
    assert other.get("/api/books").status_code == 401, "every other session is out"
    assert other.post("/api/auth/login", json={"password": PW}).status_code == 401
    assert other.post("/api/auth/login", json={"password": "a-new-passphrase"}).status_code == 200


def test_a_wrong_current_password_changes_nothing(client):
    _lock_with_env_password(client)
    r = client.put("/api/settings/password", json={"current": "guess", "new": "a-new-passphrase"})
    assert r.status_code == 403
    assert auth.PASSWORD_HASH is None and auth.verify(PW)


def test_short_passwords_are_refused(client):
    r = client.put("/api/settings/password", json={"new": "short"})
    assert r.status_code == 400 and not auth.enabled()


def test_an_unlocked_install_can_set_a_password(client):
    r = client.put("/api/settings/password", json={"new": "first-passphrase"})
    assert r.status_code == 200 and auth.enabled()
    assert client.get("/api/books").status_code == 200, "the setter is signed in"


def test_turning_the_lock_off_survives_a_restart_with_the_env_password(client):
    _lock_with_env_password(client)
    r = client.put("/api/settings/password", json={"current": PW, "disable": True})
    assert r.status_code == 200 and r.json()["lock"]["enabled"] is False
    auth.LOCK_DISABLED = False                       # a fresh process…
    with TestClient(app) as c:                       # …re-applies the file
        assert not auth.enabled()
        assert c.get("/api/books").status_code == 200


def test_secret_key_does_not_let_old_sessions_survive_a_change(client):
    auth.SECRET_KEY = "pinned-secret"
    _lock_with_env_password(client)
    old_cookie = client.cookies.get(COOKIE)
    client.put("/api/settings/password", json={"current": PW, "new": "a-new-passphrase"})
    other = TestClient(app)
    other.cookies.set(COOKIE, old_cookie)
    assert other.get("/api/books").status_code == 401


# --- 6. at rest -----------------------------------------------------------

def test_the_password_is_stored_only_as_a_salted_hash_and_the_file_is_private(client):
    client.put("/api/settings/password", json={"new": "first-passphrase"})
    _gateway(client, current_password="first-passphrase")
    raw = store.path().read_text(encoding="utf-8")
    assert "first-passphrase" not in raw
    pw = json.loads(raw)["password"]
    assert set(pw) == {"salt", "hash", "epoch"} and len(pw["salt"]) == 32
    assert stat.S_IMODE(store.path().stat().st_mode) == 0o600
    # same password, different salt → different hash
    assert store.hash_password("first-passphrase")["hash"] != pw["hash"]


# --- the connection test --------------------------------------------------

def test_the_connection_test_reports_success_and_failure(client, monkeypatch):
    _gateway(client)

    def ok(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == KEY
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ready"}]})

    monkeypatch.setattr(muse_mod, "_client", httpx.AsyncClient(transport=httpx.MockTransport(ok)))
    r = client.post("/api/settings/muse/test").json()
    assert r == {"ok": True, "model": "claude-sonnet-5-5", "reply": "ready"}

    def bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": f"invalid key {KEY}"}})

    monkeypatch.setattr(muse_mod, "_client", httpx.AsyncClient(transport=httpx.MockTransport(bad)))
    r = client.post("/api/settings/muse/test").json()
    assert r["ok"] is False and "401" in r["detail"] and KEY not in json.dumps(r)


# --- 7. many providers (4.1): listing models, provider quirks -----------------

def _models_client(monkeypatch, seen):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": "gemma4:12b"}, {"name": "qwen3:8b"}]})
        return httpx.Response(200, json={"data": [{"id": "z-model"}, {"id": "a-model"}, {"id": "a-model"}]})
    monkeypatch.setattr(muse_mod, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_models_are_listed_for_the_form_as_typed(client, monkeypatch):
    seen = []
    _models_client(monkeypatch, seen)
    r = client.post("/api/settings/muse/models",
                    json={"api": "openai", "base": "https://openrouter.ai/api/v1/", "key": KEY})
    assert r.json() == {"ok": True, "models": ["a-model", "z-model"], "formats": {}}   # sorted, deduped
    req = seen[0]
    assert str(req.url) == "https://openrouter.ai/api/v1/models"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert req.headers["x-title"] == "Katha"
    # nothing was saved by listing
    assert client.get("/api/settings").json()["muse"]["source"] == "environment"


def test_anthropic_models_use_its_headers(client, monkeypatch):
    seen = []
    _models_client(monkeypatch, seen)
    client.post("/api/settings/muse/models",
                json={"api": "messages", "base": "https://api.anthropic.com/v1", "key": KEY})
    h = seen[0].headers
    assert h["x-api-key"] == KEY and h["anthropic-version"] == up.ANTHROPIC_VERSION
    assert "authorization" not in h


def test_ollama_models_come_from_tags(client, monkeypatch):
    seen = []
    _models_client(monkeypatch, seen)
    r = client.post("/api/settings/muse/models", json={"api": "ollama", "base": "http://10.0.0.5:11434"})
    assert r.json()["models"] == ["gemma4:12b", "qwen3:8b"]
    assert str(seen[0].url) == "http://10.0.0.5:11434/api/tags"


def test_the_stored_key_is_only_reused_at_its_own_address(client, monkeypatch):
    _gateway(client)
    seen = []
    _models_client(monkeypatch, seen)
    client.post("/api/settings/muse/models", json={"api": "messages", "base": "https://gw.example.test/v1"})
    client.post("/api/settings/muse/models", json={"api": "messages", "base": "https://elsewhere.test/v1"})
    home = [r for r in seen if r.url.host == "gw.example.test"]
    away = [r for r in seen if r.url.host == "elsewhere.test"]
    assert home and all(r.headers["x-api-key"] == KEY for r in home)
    assert away and all("x-api-key" not in r.headers for r in away)


def test_listing_models_needs_the_current_password_when_locked(client, monkeypatch):
    _lock_with_env_password(client)
    seen = []
    _models_client(monkeypatch, seen)
    r = client.post("/api/settings/muse/models", json={"api": "openai", "base": "https://x.test/v1", "key": KEY})
    assert r.status_code == 403 and not seen


def test_a_failed_listing_reports_without_the_key(client, monkeypatch):
    def handler(req):
        return httpx.Response(401, json={"error": f"bad key {KEY}"})
    monkeypatch.setattr(muse_mod, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    r = client.post("/api/settings/muse/models", json={"api": "openai", "base": "https://x.test/v1", "key": KEY})
    assert r.json()["ok"] is False and KEY not in r.text


def test_openai_itself_gets_its_own_parameter_names(monkeypatch):
    monkeypatch.setattr(up, "MUSE_API", "openai")
    payload = {"model": "o4-mini", "messages": [], "options": {"num_predict": 99, "temperature": 0.7}}
    monkeypatch.setattr(up, "MUSE_API_BASE", "https://api.openai.com/v1")
    body = up.to_openai_payload(payload)
    assert body["max_completion_tokens"] == 99 and "max_tokens" not in body
    assert "temperature" not in body                       # reasoning model: default only
    body = up.to_openai_payload({**payload, "model": "gpt-4.1"})
    assert body["temperature"] == 0.7
    # a gateway keeps the classic names
    monkeypatch.setattr(up, "MUSE_API_BASE", "https://openrouter.ai/api/v1")
    body = up.to_openai_payload(payload)
    assert body["max_tokens"] == 99 and body["temperature"] == 0.7


def test_a_gateway_that_names_endpoints_tells_each_models_format(client, monkeypatch):
    """Command Code / OpenCode publish `supported_endpoints` per model (D42): a Claude
    model only on /messages, others on /chat/completions."""
    def handler(req):
        return httpx.Response(200, json={"data": [
            {"id": "claude-sonnet-5-5", "supported_endpoints": ["/provider/v1/messages"]},
            {"id": "deepseek/deepseek-v4-flash", "supported_endpoints": ["/chat/completions", "/responses"]},
            {"id": "plain-model"}]})
    monkeypatch.setattr(muse_mod, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    r = client.post("/api/settings/muse/models",
                    json={"api": "openai", "base": "https://api.commandcode.ai/provider/v1", "key": KEY})
    assert r.json()["formats"] == {"claude-sonnet-5-5": "messages", "deepseek/deepseek-v4-flash": "openai"}


def test_a_refusal_carries_the_providers_own_words(client, monkeypatch):
    """A 400 tells the author nothing; the provider's message usually says exactly why."""
    def handler(req):
        return httpx.Response(400, json={"error": {"message": f"unsupported_model: claude-x must be called via /messages ({KEY})"}})
    monkeypatch.setattr(muse_mod, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    d = client.post("/api/settings/muse/models",
                    json={"api": "openai", "base": "https://x.test/v1", "key": KEY}).json()["detail"]
    assert "400" in d and "must be called via /messages" in d and KEY not in d

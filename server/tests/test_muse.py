"""Tests for the Muse proxy (0.3 Muse, D16/D17/D19).

The Muse server proxies chat + rewrite to a friend's Ollama box. We mock the
upstream via httpx.MockTransport so the tests are hermetic — no network, no
friend-box dependency.

Pattern (mirrors test_archive.py): temp archive + data dir, real FastAPI
TestClient, but the *upstream* Ollama is replaced by httpx.MockTransport.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

# Point archive/data at temp dirs BEFORE importing app modules.
_TMP = tempfile.mkdtemp(prefix="katha-muse-test-")
os.environ["KATHA_ARCHIVE"] = str(Path(_TMP) / "archive")
os.environ["KATHA_DATA"] = str(Path(_TMP) / "data")

from app.main import app  # noqa: E402
from app import archive as ar  # noqa: E402


# --- helpers --------------------------------------------------------------

def _ollama_chat_ndjson(*chunks: dict) -> bytes:
    """Build an Ollama /api/chat NDJSON stream (one JSON object per line)."""
    return "\n".join(json.dumps(c) for c in chunks).encode("utf-8") + b"\n"


def _patch_ollama(monkeypatch: pytest.MonkeyPatch, ndjson: bytes) -> None:
    """Replace httpx.AsyncClient inside app.muse with a MockTransport."""
    import httpx

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=ndjson, headers={"content-type": "application/x-ndjson"})

    transport = httpx.MockTransport(_handler)

    # app.muse keeps a module-level httpx.AsyncClient; swap its transport.
    from app import muse as muse_mod

    real_client = muse_mod._client  # type: ignore[attr-defined]
    mock_client = httpx.AsyncClient(transport=transport, timeout=real_client.timeout)
    monkeypatch.setattr(muse_mod, "_client", mock_client)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    from seed import seed
    seed(quiet=True)
    yield


# --- chat streaming -------------------------------------------------------

def test_muse_chat_streams_tokens(monkeypatch: pytest.MonkeyPatch):
    """`/api/muse/chat` yields SSE-formatted `data:` lines whose payload is the
    accumulated Ollama `message.content` so far — minus any <think>…</think>
    blocks (deepseek-r1 emits these)."""
    chunks = [
        {"model": "gemma4:12b", "message": {"role": "assistant", "content": "Hi"}, "done": False},
        {"model": "gemma4:12b", "message": {"role": "assistant", "content": " there"}, "done": False},
        {"model": "gemma4:12b", "message": {"role": "assistant", "content": "!"}, "done": True},
    ]
    _patch_ollama(monkeypatch, _ollama_chat_ndjson(*chunks))

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/muse/chat",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "chapter_id": None,
            },
        ) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]
            payload = _sse_payload(r)

    # The streamed tokens, when concatenated, reconstruct the visible reply.
    assert "Hi" in payload
    assert "there" in payload
    assert "!" in payload


def test_muse_chat_strips_think_blocks(monkeypatch: pytest.MonkeyPatch):
    """Reasoning models (deepseek-r1) emit <think>...</think> inside `content`.
    The proxy must strip these before pushing to the client — the user should
    not see raw chain-of-thought."""
    chunks = [
        {"model": "deepseek-r1:14b", "message": {"role": "assistant", "content": "<think>plan</think>The answer is 42."}, "done": True},
    ]
    _patch_ollama(monkeypatch, _ollama_chat_ndjson(*chunks))

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/muse/chat",
            json={"messages": [{"role": "user", "content": "what?"}], "chapter_id": None},
        ) as r:
            assert r.status_code == 200
            payload = _sse_payload(r)

    assert "<think>" not in payload
    assert "plan" not in payload
    assert "42" in payload


def test_muse_models_endpoint():
    """GET /api/muse/models returns the configured primary + fallback."""
    from app import config

    with TestClient(app) as client:
        r = client.get("/api/muse/models")

    assert r.status_code == 200
    body = r.json()
    assert body["chat_model"] == config.MUSE_CHAT_MODEL
    assert body["rewrite_model"] == config.MUSE_REWRITE_MODEL
    assert body["ollama_base"] == config.OLLAMA_BASE


# --- rewrite streaming ----------------------------------------------------

def _sse_payload(r) -> str:
    """Concatenate just the data payload (no `data: ` prefix, no [DONE]).

    SSE format is `data: <payload>` — the prefix is 6 chars (`data:` + 1 space).
    We don't strip the payload beyond that prefix because internal whitespace
    IS part of the prose (e.g. the space between sentences).
    """
    out = []
    for line in r.iter_lines():
        if not line.startswith("data:"):
            continue
        payload = line[6:] if len(line) > 5 and line[5] == ' ' else line[5:]
        if payload.strip() == "[DONE]":
            continue
        out.append(payload.replace("\\n", "\n").replace("\\\\", "\\"))
    return "".join(out)


def test_muse_rewrite_streams_single_proposal(monkeypatch: pytest.MonkeyPatch):
    """`/api/muse/rewrite` yields SSE tokens whose concatenation is the full
    rewrite proposal — stripped of any <think> blocks. The user types prose,
    the server returns a single streamed rewrite."""
    chunks = [
        {"model": "deepseek-r1:14b", "message": {"role": "assistant", "content": "<think>plan</think>"}, "done": False},
        {"model": "deepseek-r1:14b", "message": {"role": "assistant", "content": "The dog padded slowly"}, "done": False},
        {"model": "deepseek-r1:14b", "message": {"role": "assistant", "content": " across the sun-baked road."}, "done": True},
    ]
    _patch_ollama(monkeypatch, _ollama_chat_ndjson(*chunks))

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/muse/rewrite",
            json={
                "text": "The dog walked slowly across the dusty road.",
                "style": "clean",
                "chapter_id": None,
            },
        ) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]
            payload = _sse_payload(r)

    assert "The dog padded slowly across the sun-baked road." in payload
    assert "<think>" not in payload
    assert "plan" not in payload


def test_muse_rewrite_style_routes_through_correct_model(monkeypatch: pytest.MonkeyPatch):
    """The rewrite endpoint must use MUSE_REWRITE_MODEL (the thinking model),
    NOT MUSE_CHAT_MODEL. We assert this by capturing the upstream request URL
    payload via the mock transport."""
    captured: dict = {}

    import httpx

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        captured["body"] = _json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            content=_ollama_chat_ndjson({"model": captured["body"]["model"], "message": {"role": "assistant", "content": "ok"}, "done": True}),
        )

    transport = httpx.MockTransport(_handler)
    from app import muse as muse_mod
    real_client = muse_mod._client  # type: ignore[attr-defined]
    mock_client = httpx.AsyncClient(transport=transport, timeout=real_client.timeout)
    monkeypatch.setattr(muse_mod, "_client", mock_client)

    from app import config

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/muse/rewrite",
            json={"text": "Hello world.", "style": "novel"},
        ) as r:
            assert r.status_code == 200
            list(r.iter_lines())

    assert captured["body"]["model"] == config.MUSE_REWRITE_MODEL
    assert captured["body"]["model"] != config.MUSE_CHAT_MODEL


# --- canon context (D18) ---------------------------------------------------

def test_canon_context_includes_current_chapter(monkeypatch: pytest.MonkeyPatch):
    """When the rewrite carries a `chapter_id`, the system prompt must include
    the chapter's text so the Muse knows what it's rewriting in context."""
    captured: dict = {}

    import httpx

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        captured["body"] = _json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            content=_ollama_chat_ndjson({"model": "deepseek-r1:14b", "message": {"role": "assistant", "content": "rewritten"}, "done": True}),
        )

    transport = httpx.MockTransport(_handler)
    from app import muse as muse_mod
    real_client = muse_mod._client  # type: ignore[attr-defined]
    mock_client = httpx.AsyncClient(transport=transport, timeout=real_client.timeout)
    monkeypatch.setattr(muse_mod, "_client", mock_client)

    series_slug = ar.slugify("The Ember Throne")
    book_slug = ar.slugify("The First Flame")

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/muse/rewrite",
            json={"text": "Hello world.", "style": "novel", "chapter_id": f"{series_slug}/{book_slug}/ch-01"},
        ) as r:
            assert r.status_code == 200
            list(r.iter_lines())

    # The canon context is its own system message. There should be at least 2:
    # 1. the style prompt, 2. the canon-context block.
    sys_msgs = [m for m in captured["body"]["messages"] if m["role"] == "system"]
    canon_msg = next((m for m in sys_msgs if "CURRENT CHAPTER" in m["content"]), None)
    assert canon_msg is not None, f"no canon-context system message found; sys_msgs={[m['content'][:50] for m in sys_msgs]}"
    assert "CURRENT CHAPTER" in canon_msg["content"]
    # ch-01 contains "Ember" in the seeded prose — assert the chapter was loaded.
    assert "Ember" in canon_msg["content"]


def test_canon_context_omitted_when_no_chapter_id(monkeypatch: pytest.MonkeyPatch):
    """Without a `chapter_id`, the Muse call should NOT inject the canon
    context block — the request is just a free-form rewrite."""
    captured: dict = {}

    import httpx

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        captured["body"] = _json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            content=_ollama_chat_ndjson({"model": "deepseek-r1:14b", "message": {"role": "assistant", "content": "ok"}, "done": True}),
        )

    transport = httpx.MockTransport(_handler)
    from app import muse as muse_mod
    real_client = muse_mod._client  # type: ignore[attr-defined]
    mock_client = httpx.AsyncClient(transport=transport, timeout=real_client.timeout)
    monkeypatch.setattr(muse_mod, "_client", mock_client)

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/muse/rewrite",
            json={"text": "Plain rewrite.", "style": "novel"},
        ) as r:
            assert r.status_code == 200
            list(r.iter_lines())

    sys_msgs = [m for m in captured["body"]["messages"] if m["role"] == "system"]
    # The base system prompt still exists (style prompt), but it should NOT
    # contain the canon-context block.
    assert not any("CURRENT CHAPTER" in m["content"] for m in sys_msgs)


# --- style digest (D19) ---------------------------------------------------

def test_style_digest_is_cached_and_reused(tmp_path, monkeypatch):
    """First call for a book: model is asked for a digest. Second call: cached
    file is read — model is NOT asked again."""
    from app import muse as muse_mod
    from app.config import ARCHIVE_ROOT

    # Find the seeded book — Ember Throne / First Flame. Style digest path
    # lives at archive/.katha/muse/style-<book-slug>.md.
    series_slug = ar.slugify("The Ember Throne")
    book_slug = ar.slugify("The First Flame")
    digest_path = ARCHIVE_ROOT / ".katha" / "muse" / f"style-{book_slug}.md"

    # Pre-seed a digest to simulate "already learned". The Muse must NOT
    # call the model when this file exists.
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    digest_path.write_text("Established voice: third-person close, lyrical, short sentences.\n", encoding="utf-8")

    captured: dict = {}

    import httpx

    def _handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        captured["body"] = _json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            content=_ollama_chat_ndjson({"model": "deepseek-r1:14b", "message": {"role": "assistant", "content": "ok"}, "done": True}),
        )

    transport = httpx.MockTransport(_handler)
    real_client = muse_mod._client
    mock_client = httpx.AsyncClient(transport=transport, timeout=real_client.timeout)
    monkeypatch.setattr(muse_mod, "_client", mock_client)

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/muse/rewrite",
            json={"text": "x", "style": "novel", "chapter_id": f"{series_slug}/{book_slug}/ch-01"},
        ) as r:
            assert r.status_code == 200
            list(r.iter_lines())

    # The cached digest should appear in the canon-context system prompt.
    canon_msgs = [m for m in captured["body"]["messages"] if m["role"] == "system" and "CURRENT CHAPTER" in m["content"]]
    assert len(canon_msgs) == 1
    assert "Established voice" in canon_msgs[0]["content"]


# --- thread persistence (D19) --------------------------------------------

def test_thread_is_persisted_to_archive_dot_katha(tmp_path):
    """When a Muse call carries a chapter_id, the exchange must be appended to
    `archive/.katha/muse/<chapter-slug>.md`."""
    from app import muse as muse_mod
    from app.config import ARCHIVE_ROOT

    series_slug = ar.slugify("The Ember Throne")
    book_slug = ar.slugify("The First Flame")
    thread_path = ARCHIVE_ROOT / ".katha" / "muse" / "ch-01.md"

    # Clean any pre-existing file from earlier test runs.
    if thread_path.exists():
        thread_path.unlink()

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/muse/chat",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "chapter_id": f"{series_slug}/{book_slug}/ch-01",
            },
        ) as r:
            assert r.status_code == 200
            list(r.iter_lines())

    assert thread_path.exists()
    body = thread_path.read_text(encoding="utf-8")
    assert "hello" in body
    assert "ASSISTANT" in body


def test_style_digest_auto_generated_on_first_touch(monkeypatch: pytest.MonkeyPatch):
    """First call for a book with no cached digest: the Muse generates one
    via the rewrite model and writes it to disk."""
    from app import muse as muse_mod
    from app.config import ARCHIVE_ROOT

    series_slug = ar.slugify("The Ember Throne")
    book_slug = ar.slugify("The First Flame")
    digest_path = ARCHIVE_ROOT / ".katha" / "muse" / f"style-{book_slug}.md"

    # Clean any pre-existing digest from earlier test runs.
    if digest_path.exists():
        digest_path.unlink()

    # Patch the sync httpx.Client (style digest is sync to avoid event-loop conflict).
    import httpx as _httpx
    from unittest.mock import patch as _patch

    class _SyncClientOK(_httpx.Client):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
        def post(self, url, json=None, **kw):
            req = _httpx.Request("POST", url, json=json)
            return _httpx.Response(
                200,
                json={
                    "model": json["model"],
                    "message": {"role": "assistant", "content": "Auto-generated style fingerprint."},
                    "done": True,
                },
                request=req,
            )
        def __enter__(self): return self
        def __exit__(self, *a): self.close()

    with _patch("httpx.Client", _SyncClientOK):
        digest = muse_mod._load_style_summary(book_slug, ARCHIVE_ROOT / series_slug / book_slug)

    assert "Auto-generated" in digest
    assert digest_path.exists()
    assert "Auto-generated" in digest_path.read_text(encoding="utf-8")

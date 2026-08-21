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

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
            payload = "".join(line for line in r.iter_lines() if line.startswith("data:"))

    # The streamed tokens, when concatenated, reconstruct the visible reply.
    # Each `data:` line is a delta; the simplest invariant is "Hi there!"
    # appears in the concatenated payload.
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
            payload = "".join(line for line in r.iter_lines() if line.startswith("data:"))

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

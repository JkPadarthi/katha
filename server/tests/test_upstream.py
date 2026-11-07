"""Tests for the upstream dialect switch (2.1, D20–D23).

The Muse speaks one dialect internally (the Ollama shape) and `app/upstream.py`
translates on the wire. The regression net has to prove three things:

1. **ollama mode is untouched** — same URL, same NDJSON parsing, no auth header.
2. **openai mode is correct** — URL + bearer, payload conversion, SSE delta
   parsing, and tool-call fragment reassembly (the fiddly part).
3. **a dead upstream fails fast and loudly** — a short connect timeout plus the
   existing `[ERROR]` SSE event, instead of a 300s silent freeze.

Hermetic: `httpx.MockTransport` stands in for the upstream, and the module
globals are monkeypatched per test so both dialects are covered in one process.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

_TMP = tempfile.mkdtemp(prefix="katha-upstream-test-")
os.environ["KATHA_ARCHIVE"] = str(Path(_TMP) / "archive")
os.environ["KATHA_DATA"] = str(Path(_TMP) / "data")

from app import archive as ar  # noqa: E402
from app import muse as muse_mod  # noqa: E402
from app import upstream as up  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

SERIES = ar.slugify("The Ember Throne")
BOOK = ar.slugify("The First Flame")
CHAPTER_ID = f"{SERIES}/{BOOK}/ch-01"


@pytest.fixture(scope="module", autouse=True)
def _seed():
    from seed import seed
    seed(quiet=True)
    yield


@pytest.fixture(autouse=True)
def _reset_dialect(monkeypatch: pytest.MonkeyPatch):
    """Every test starts from the shipped ollama dialect."""
    monkeypatch.setattr(up, "MUSE_API", up.OLLAMA)
    monkeypatch.setattr(up, "MUSE_API_BASE", "")
    monkeypatch.setattr(up, "MUSE_API_KEY", "")
    yield


# --- helpers --------------------------------------------------------------

def _openai_mode(monkeypatch: pytest.MonkeyPatch, key: str = "sk-test-key-1234") -> None:
    monkeypatch.setattr(up, "MUSE_API", up.OPENAI)
    monkeypatch.setattr(up, "MUSE_API_BASE", "https://api.example.test/v1")
    monkeypatch.setattr(up, "MUSE_API_KEY", key)


def _sse(*payloads) -> bytes:
    """OpenAI-style SSE body: `data: <json>` events, `[DONE]` terminated."""
    out = b""
    for p in payloads:
        chunk = p if isinstance(p, str) else json.dumps(p)
        out += b"data: " + chunk.encode("utf-8") + b"\n\n"
    return out + b"data: [DONE]\n\n"


def _delta(**delta) -> dict:
    return {"choices": [{"index": 0, "delta": delta}]}


def _ndjson(*chunks: dict) -> bytes:
    return "\n".join(json.dumps(c) for c in chunks).encode("utf-8") + b"\n"


def _client_with(handler, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    """Build a MockTransport client AND install it as muse's client."""
    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(muse_mod, "_client", mock)
    return mock


def _collect(gen) -> list[dict]:
    async def _drain():
        return [e async for e in gen]

    return asyncio.run(_drain())


def _sse_text(body: str) -> str:
    """Reassemble prose from an SSE response the way the browser client does:
    strip the framing, unescape, and concatenate the data payloads."""
    out = []
    for line in body.split("\n"):
        if not line.startswith("data:"):
            continue
        payload = line[6:] if len(line) > 5 and line[5] == " " else line[5:]
        if payload.startswith(("[STATUS]", "[ERROR]")) or payload.strip() == "[DONE]":
            continue
        out.append(payload.replace("\\n", "\n").replace("\\\\", "\\"))
    return "".join(out)


# --- 1. ollama mode is untouched ------------------------------------------

def test_ollama_mode_unchanged_url_parsing_and_no_auth(monkeypatch: pytest.MonkeyPatch):
    """Default mode = the LAN box: `/api/chat`, NDJSON, no Authorization header."""
    seen: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, content=_ndjson(
            {"model": "gemma4:12b", "message": {"role": "assistant", "content": "hi"}, "done": True},
        ))

    mock = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    events = _collect(up.stream_events(
        {"model": "gemma4:12b", "messages": [{"role": "user", "content": "x"}],
         "options": {"num_predict": 10}}, mock))

    from app import config

    assert seen["url"] == f"{config.OLLAMA_BASE}/api/chat"
    assert "authorization" not in {k.lower() for k in seen["headers"]}
    # Ollama keeps its own options bag — no OpenAI-ification in this mode.
    assert seen["body"]["options"] == {"num_predict": 10}
    assert "max_tokens" not in seen["body"]
    assert events == [{"content": "hi"}]


# --- 2. openai mode: URL, auth, payload -----------------------------------

def test_openai_mode_uses_completions_url_and_bearer(monkeypatch: pytest.MonkeyPatch):
    _openai_mode(monkeypatch, key="sk-abc-123")
    seen: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, content=_sse(_delta(content="ok")))

    mock = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    _collect(up.stream_events({"model": "m", "messages": [], "stream": True}, mock))

    assert seen["url"] == "https://api.example.test/v1/chat/completions"
    assert seen["headers"]["authorization"] == "Bearer sk-abc-123"


def test_openai_payload_conversion(monkeypatch: pytest.MonkeyPatch):
    """`options` becomes max_tokens/temperature, tools pass through, and the
    Ollama-only `options` bag must NOT leak onto the wire."""
    _openai_mode(monkeypatch)
    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, content=_sse(_delta(content="ok")))

    mock = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    tools = [{"type": "function", "function": {"name": "read", "parameters": {}}}]
    _collect(up.stream_events({
        "model": "vendor/model-x",
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "options": {"num_predict": 4096, "temperature": 0.7},
        "tools": tools,
    }, mock))

    body = captured["body"]
    assert body["model"] == "vendor/model-x"
    assert body["max_tokens"] == 4096
    assert body["temperature"] == 0.7
    assert body["stream"] is True
    assert body["tools"] == tools
    assert "options" not in body
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_openai_tool_messages_carry_call_ids():
    """Assistant tool-call turns and their results must be paired by id."""
    out = up.to_openai_messages([
        {"role": "user", "content": "who is Kael?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_story_file", "arguments": {"path": "bible/characters/kael.md"}}},
        ]},
        {"role": "tool", "tool_name": "read_story_file", "content": "# Kael"},
        {"role": "user", "content": "and?"},
    ])

    call = out[1]["tool_calls"][0]
    assert call["type"] == "function"
    assert call["id"]
    # Arguments must be the JSON *string* OpenAI expects, not a dict.
    assert json.loads(call["function"]["arguments"]) == {"path": "bible/characters/kael.md"}
    assert out[2] == {"role": "tool", "tool_call_id": call["id"], "content": "# Kael"}
    assert out[3]["role"] == "user"


# --- 3. openai mode: streaming --------------------------------------------

def test_openai_content_deltas_stream_through(monkeypatch: pytest.MonkeyPatch):
    """Delta content accumulates; `reasoning_content` is never forwarded."""
    _openai_mode(monkeypatch)

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(
            _delta(reasoning_content="secret chain of thought"),
            _delta(content="The dog "),
            _delta(content="padded across the road."),
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ))

    mock = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    events = _collect(up.stream_events({"model": "m", "messages": [], "stream": True}, mock))

    assert "".join(e.get("content", "") for e in events) == "The dog padded across the road."
    assert "secret chain of thought" not in json.dumps(events)


def test_openai_reassembles_streamed_tool_call_fragments(monkeypatch: pytest.MonkeyPatch):
    """The id and name arrive once, the arguments in pieces — reassemble into
    the single complete, internal-shaped call the tool loop expects."""
    _openai_mode(monkeypatch)
    args = '{"path": "chapters/ch-03.md"}'

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(
            _delta(tool_calls=[{"index": 0, "id": "call_77", "type": "function",
                                "function": {"name": "read_story_file", "arguments": ""}}]),
            _delta(tool_calls=[{"index": 0, "function": {"arguments": args[:9]}}]),
            _delta(tool_calls=[{"index": 0, "function": {"arguments": args[9:]}}]),
        ))

    mock = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    events = _collect(up.stream_events({"model": "m", "messages": [], "stream": True}, mock))

    calls = [c for e in events for c in (e.get("tool_calls") or [])]
    assert len(calls) == 1
    assert calls[0]["id"] == "call_77"
    assert calls[0]["function"]["name"] == "read_story_file"
    assert json.loads(calls[0]["function"]["arguments"]) == {"path": "chapters/ch-03.md"}


def test_openai_complete_returns_internal_shape(monkeypatch: pytest.MonkeyPatch):
    """The style digest path is non-streaming and expects the Ollama shape."""
    _openai_mode(monkeypatch)
    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"choices": [{"message": {"content": "dry, close-third cadence."}}]})

    mock = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    out = asyncio.run(up.complete(
        {"model": "m", "messages": [{"role": "user", "content": "p"}],
         "options": {"num_predict": 400, "temperature": 0.4}}, mock))

    assert out == {"message": {"content": "dry, close-third cadence."}}
    assert captured["body"]["stream"] is False
    assert captured["body"]["max_tokens"] == 400


# --- 4. openai mode end-to-end through the API ----------------------------

def test_rewrite_streams_prose_in_openai_mode(monkeypatch: pytest.MonkeyPatch):
    """`/api/muse/rewrite` works unchanged on a cloud dialect — and still strips
    any inline <think> the gateway might return."""
    _openai_mode(monkeypatch)

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(
            _delta(content="<think>weighing verbs</think>The dog "),
            _delta(content="padded across the sun-baked road."),
        ))

    _client_with(_handler, monkeypatch)

    with TestClient(app) as c:
        with c.stream("POST", "/api/muse/rewrite",
                      json={"text": "The dog walked slowly.", "style": "clean"}) as r:
            assert r.status_code == 200
            body = "".join(r.iter_text())

    assert _sse_text(body) == "The dog padded across the sun-baked road."
    assert "<think>" not in body
    assert "[ERROR]" not in body


def test_agentic_chat_with_tools_in_openai_mode(monkeypatch: pytest.MonkeyPatch):
    """The agentic loop must survive translation: turn 1 returns a tool call,
    the server reads the file, turn 2 answers — and the echoed thread is valid
    OpenAI (assistant tool_calls + a tool result carrying tool_call_id)."""
    _openai_mode(monkeypatch)
    requests_seen: list[dict] = []
    state = {"turn": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8") or "{}")
        requests_seen.append(body)
        if not body.get("stream"):
            # style digest (first touch of this book) — answer, don't stream.
            return httpx.Response(200, json={"choices": [{"message": {"content": "terse, cold cadence."}}]})
        state["turn"] += 1
        if state["turn"] == 1:
            return httpx.Response(200, content=_sse(
                _delta(tool_calls=[{"index": 0, "id": "call_1", "type": "function",
                                    "function": {"name": "read_story_file",
                                                 "arguments": '{"path": "bible/characters/kael.md"}'}}]),
            ))
        return httpx.Response(200, content=_sse(_delta(content="Kael is the ember-bearer.")))

    _client_with(_handler, monkeypatch)

    with TestClient(app) as c:
        with c.stream("POST", "/api/muse/chat", json={
            "messages": [{"role": "user", "content": "who is the main character?"}],
            "chapter_id": CHAPTER_ID,
        }) as r:
            assert r.status_code == 200
            body = "".join(r.iter_text())

    assert "[ERROR]" not in body
    assert "Kael is the ember-bearer." in body
    assert "[STATUS] reading bible/characters/kael.md" in body

    turn2 = [b for b in requests_seen if b.get("stream")][-1]
    roles = [m["role"] for m in turn2["messages"]]
    assert "tool" in roles
    tool_msg = next(m for m in turn2["messages"] if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_1"
    assert "# Kael" in tool_msg["content"]
    echo = next(m for m in turn2["messages"] if m["role"] == "assistant" and m.get("tool_calls"))
    assert echo["tool_calls"][0]["id"] == "call_1"


# --- 5. a dead upstream must fail fast, not freeze ------------------------

def test_dead_upstream_reports_error_quickly(monkeypatch: pytest.MonkeyPatch):
    """Regression net for the 2.0.1 freeze: with the upstream unreachable the
    client got a 200 and *nothing* for 300s. Now: a short connect timeout, the
    `[ERROR]` SSE event, and a `[DONE]` terminator — a real message in the UI."""
    seen: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout") or {}
        raise httpx.ConnectTimeout("connect timed out", request=request)

    _client_with(_handler, monkeypatch)

    with TestClient(app) as c:
        with c.stream("POST", "/api/muse/rewrite",
                      json={"text": "The dog walked slowly.", "style": "clean"}) as r:
            assert r.status_code == 200
            body = "".join(r.iter_text())

    assert "[ERROR]" in body and "[DONE]" in body
    assert "ConnectTimeout" in body
    # The fast-fail guarantee: connecting gets its own short budget.
    assert seen["timeout"].get("connect") == pytest.approx(up.MUSE_UPSTREAM_CONNECT_TIMEOUT)
    assert up.MUSE_UPSTREAM_CONNECT_TIMEOUT < up.MUSE_UPSTREAM_TIMEOUT


def test_key_never_leaks_into_models_endpoint(monkeypatch: pytest.MonkeyPatch):
    """The Muse's models endpoint describes routing, never credentials or the
    upstream address."""
    _openai_mode(monkeypatch, key="sk-super-secret")
    body = client.get("/api/muse/models").text

    assert "sk-super-secret" not in body
    assert "api.example.test" not in body

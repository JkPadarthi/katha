"""Tests for the upstream dialect switch (2.1, D20–D23; messages 2.7, D42).

The Muse speaks one dialect internally (the Ollama shape) and `app/upstream.py`
translates on the wire. The regression net has to prove four things:

1. **ollama mode is untouched** — same URL, same NDJSON parsing, no auth header.
2. **openai mode is correct** — URL + bearer, payload conversion, SSE delta
   parsing, and tool-call fragment reassembly (the fiddly part).
3. **messages mode is correct** — `{gateway_base}/messages` + `x-api-key`, system
   hoisted to the top level, `max_tokens` never missing, tools flattened to
   `input_schema`, and tool results riding in *user* turns paired by id.
4. **a dead upstream fails fast and loudly** — a short connect timeout plus the
   existing `[ERROR]` SSE event, instead of a 300s silent freeze. A gateway that
   refuses the model must also surface its message, not stream nothing.

Hermetic: `httpx.MockTransport` stands in for the upstream, and the module
globals are monkeypatched per test so every dialect is covered in one process.
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


def _messages_mode(monkeypatch: pytest.MonkeyPatch, key: str = "sk-ant-abc") -> None:
    """Route the Muse at a gateway that serves Claude in the Messages shape.

    The base is a *gateway* (commandcode/OpenRouter-style) on purpose — the
    dialect is a wire shape, not a vendor address.
    """
    monkeypatch.setattr(up, "MUSE_API", up.MESSAGES)
    monkeypatch.setattr(up, "MUSE_API_BASE", "https://api.example.test/provider/v1")
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


def _messages_sse(*events) -> bytes:
    """Anthropic-style SSE: `event:` + `data:` pairs, no `[DONE]` terminator."""
    out = b""
    for e in events:
        obj = e if isinstance(e, dict) else {"type": e}
        out += b"event: " + (obj.get("type") or "message").encode("utf-8") + b"\n"
        out += b"data: " + json.dumps(obj).encode("utf-8") + b"\n\n"
    return out


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


# --- 6. messages (Claude-on-a-gateway) mode --------------------------------

def test_messages_mode_uses_messages_url_on_the_gateway(monkeypatch: pytest.MonkeyPatch):
    """Claude via a gateway: `{gateway_base}/messages`, x-api-key + version pin,
    and no Bearer — the gateway base is what's called, never the vendor."""
    _messages_mode(monkeypatch, key="sk-gw-123")
    seen: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, content=_messages_sse(
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "ok"}},
            {"type": "message_stop"}))

    mock = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    _collect(up.stream_events({"model": "m", "messages": [], "stream": True}, mock))

    assert seen["url"] == "https://api.example.test/provider/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-gw-123"
    assert seen["headers"]["anthropic-version"] == up.ANTHROPIC_VERSION
    assert "authorization" not in seen["headers"]


def test_messages_payload_hoists_system_and_keeps_max_tokens(monkeypatch: pytest.MonkeyPatch):
    """The shape has no `system` role and *requires* `max_tokens`: system turns
    become the top-level field, and the ceiling is never absent."""
    _messages_mode(monkeypatch)
    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, content=_messages_sse({"type": "message_stop"}))

    mock = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    tools = [{"type": "function", "function": {
        "name": "read_story_file", "description": "read one file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}]
    _collect(up.stream_events({
        "model": "claude-sonnet-5-5",
        "messages": [{"role": "system", "content": "you are the muse"},
                     {"role": "system", "content": "keep the voice"},
                     {"role": "user", "content": "who is Kael?"}],
        "options": {"num_predict": 1024, "temperature": 0.8},
        "tools": tools,
    }, mock))

    body = captured["body"]
    assert body["model"] == "claude-sonnet-5-5"
    assert body["system"] == "you are the muse\n\nkeep the voice"
    assert [m["role"] for m in body["messages"]] == ["user"]
    assert body["messages"][0]["content"] == [{"type": "text", "text": "who is Kael?"}]
    assert body["max_tokens"] == 1024
    # `temperature` must NOT reach the wire: current Claude models 400 on it.
    assert "temperature" not in body
    assert body["stream"] is True
    assert "options" not in body
    assert body["tools"][0] == {
        "name": "read_story_file", "description": "read one file",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}}


def test_messages_max_tokens_has_a_default_when_options_are_absent():
    """No `options` at all must still satisfy the required field."""
    body = up.to_anthropic_payload(
        {"model": "m", "messages": [{"role": "user", "content": "u"}]})
    assert body["max_tokens"] == up.DEFAULT_MAX_TOKENS


def test_messages_pairs_tool_results_into_user_turns():
    """A tool result is a `tool_result` block in a *user* turn, paired to its
    `tool_use` by id; roles must alternate, so same-role turns merge."""
    out = up.to_anthropic_messages([
        {"role": "system", "content": "s"},
        {"role": "user", "content": "who is Kael?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "toolu_9", "function": {"name": "read_story_file",
                                           "arguments": {"path": "bible/characters/kael.md"}}},
        ]},
        {"role": "tool", "tool_name": "read_story_file", "content": "# Kael"},
        {"role": "user", "content": "and?"},
    ])

    # system is gone, and the trailing user turn merged with the tool result.
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert out[1]["content"][0] == {
        "type": "tool_use", "id": "toolu_9", "name": "read_story_file",
        "input": {"path": "bible/characters/kael.md"}}
    assert out[2]["content"][0] == {
        "type": "tool_result", "tool_use_id": "toolu_9", "content": "# Kael"}
    assert out[2]["content"][1] == {"type": "text", "text": "and?"}


def test_messages_pairs_a_result_with_no_id_by_name():
    """Internally a result carries only `tool_name`; it must still find its call."""
    out = up.to_anthropic_messages([
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "search_story", "arguments": {"query": "ember"}}}]},
        {"role": "tool", "tool_name": "search_story", "content": "one hit"},
    ])

    call = out[0]["content"][0]
    assert call["type"] == "tool_use" and call["id"]
    assert out[1]["content"][0] == {
        "type": "tool_result", "tool_use_id": call["id"], "content": "one hit"}


def test_messages_text_deltas_stream_through(monkeypatch: pytest.MonkeyPatch):
    """Text arrives as `text_delta` events; nothing else is mistaken for prose."""
    _messages_mode(monkeypatch)

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_messages_sse(
            {"type": "message_start", "message": {"role": "assistant"}},
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "The dog "}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "padded across the road."}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_stop"}))

    mock = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    events = _collect(up.stream_events({"model": "m", "messages": [], "stream": True}, mock))

    assert "".join(e.get("content", "") for e in events) == "The dog padded across the road."


def test_messages_reassembles_streamed_tool_input_fragments(monkeypatch: pytest.MonkeyPatch):
    """A `tool_use` block opens first (id + name), then its arguments arrive as
    `input_json_delta` fragments — same reassembly as the OpenAI path."""
    _messages_mode(monkeypatch)
    args = '{"path": "chapters/ch-03.md"}'

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_messages_sse(
            {"type": "content_block_start", "index": 1,
             "content_block": {"type": "tool_use", "id": "toolu_77",
                               "name": "read_story_file", "input": {}}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": args[:9]}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": args[9:]}},
            {"type": "content_block_stop", "index": 1},
            {"type": "message_stop"}))

    mock = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    events = _collect(up.stream_events({"model": "m", "messages": [], "stream": True}, mock))

    calls = [c for e in events for c in (e.get("tool_calls") or [])]
    assert len(calls) == 1
    assert calls[0]["id"] == "toolu_77"
    assert calls[0]["function"]["name"] == "read_story_file"
    assert json.loads(calls[0]["function"]["arguments"]) == {"path": "chapters/ch-03.md"}


def test_messages_error_event_becomes_a_real_error(monkeypatch: pytest.MonkeyPatch):
    """Regression net for the exact failure that started this: a gateway that
    refuses the model must say so, not stream nothing for 300 seconds."""
    _messages_mode(monkeypatch)

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_messages_sse(
            {"type": "error", "error": {
                "type": "invalid_request_error",
                "message": 'Model "x" must be called via /provider/v1/messages'}}))

    mock = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    with pytest.raises(RuntimeError) as err:
        _collect(up.stream_events({"model": "m", "messages": [], "stream": True}, mock))

    assert "must be called via" in str(err.value)


def test_messages_complete_returns_internal_shape(monkeypatch: pytest.MonkeyPatch):
    """The style digest is non-streaming and expects the Ollama shape."""
    _messages_mode(monkeypatch)
    captured: dict = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "dry, close-third cadence."}],
            "stop_reason": "end_turn"})

    mock = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    out = asyncio.run(up.complete(
        {"model": "m", "messages": [{"role": "user", "content": "p"}],
         "options": {"num_predict": 400}}, mock))

    assert out == {"message": {"content": "dry, close-third cadence."}}
    assert captured["body"]["stream"] is False
    assert captured["body"]["max_tokens"] == 400


def test_agentic_chat_with_tools_in_messages_mode(monkeypatch: pytest.MonkeyPatch):
    """End-to-end through the API: turn 1 asks for a file, the server reads it,
    turn 2 answers — and the echoed thread is valid Messages shape (tool_use in
    the assistant turn, tool_result in a user turn)."""
    _messages_mode(monkeypatch)
    requests_seen: list[dict] = []
    state = {"turn": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8") or "{}")
        requests_seen.append(body)
        if not body.get("stream"):
            # style digest (first touch of this book) — answer, don't stream.
            return httpx.Response(200, json={
                "content": [{"type": "text", "text": "terse, cold cadence."}]})
        state["turn"] += 1
        if state["turn"] == 1:
            return httpx.Response(200, content=_messages_sse(
                {"type": "content_block_start", "index": 0,
                 "content_block": {"type": "tool_use", "id": "toolu_1",
                                   "name": "read_story_file", "input": {}}},
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "input_json_delta",
                           "partial_json": '{"path": "bible/characters/kael.md"}'}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_stop"}))
        return httpx.Response(200, content=_messages_sse(
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "Kael is the ember-bearer."}},
            {"type": "message_stop"}))

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
    use = next(blk for m in turn2["messages"] if m["role"] == "assistant"
               for blk in m["content"] if blk.get("type") == "tool_use")
    res = next(blk for m in turn2["messages"] if m["role"] == "user"
               for blk in m["content"] if blk.get("type") == "tool_result")
    assert use["id"] == "toolu_1"
    assert res["tool_use_id"] == "toolu_1"
    assert "# Kael" in res["content"]
    # The tool result rides in a USER turn (the shape demands it).
    assert turn2["messages"][-1]["role"] == "user"


def test_the_dialect_alias_anthropic_still_selects_the_same_shape(monkeypatch: pytest.MonkeyPatch):
    """`anthropic` stays accepted so an env written before the rename works."""
    monkeypatch.setattr(up, "MUSE_API", up.ANTHROPIC)
    monkeypatch.setattr(up, "MUSE_API_BASE", "https://api.example.test/provider/v1")
    assert up.is_messages() is True
    assert up.chat_url() == "https://api.example.test/provider/v1/messages"


# --- an empty answer must never look like silence (3.0.9) ------------------
# This gateway runs the model with extended thinking ON, and thinking spends the same output
# budget as the reply. The canon sweep asked for a whole-manuscript audit at a 4096 ceiling,
# thought until it ran out, and streamed nothing — so the panel showed an empty report with no
# explanation. Whatever the cause, the author gets a sentence, not a blank.

def _notice_body(prompt: str = "audit the book") -> dict:
    return {"model": "claude-sonnet-5-5",
            "messages": [{"role": "user", "content": prompt}],
            "options": {"num_predict": 40}}


def _notice_transport(lines: list[str]):
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content="".join(lines).encode())
    return httpx.AsyncClient(transport=httpx.MockTransport(_handler), timeout=10)


def _collect_notice(lines: list[str]) -> list[dict]:
    async def go():
        out = []
        async for ev in up._stream_anthropic(_notice_body(), _notice_transport(lines)):
            out.append(ev)
        return out
    return asyncio.run(go())


_THINKING_ONLY = [
    'data: {"type":"message_start"}\n\n',
    'data: {"type":"content_block_start","index":0,'
    '"content_block":{"type":"thinking","thinking":"","signature":""}}\n\n',
    'data: {"type":" content_block_delta"}\n\n',
    'data: {"type":"content_block_delta","index":0,'
    '"delta":{"type":"signature_delta","signature":"AAAA"}}\n\n',
    'data: {"type":"content_block_stop","index":0}\n\n',
    'data: {"type":"message_delta","delta":{"stop_reason":"max_tokens"}}\n\n',
    'data: {"type":"message_stop"}\n\n',
]

_TEXT_STREAM = [
    'data: {"type":"message_start"}\n\n',
    'data: {"type":"content_block_start","index":0,'
    '"content_block":{"type":"text","text":""}}\n\n',
    'data: {"type":"content_block_delta","index":0,'
    '"delta":{"type":"text_delta","text":"## Canon\\n"}}\n\n',
    'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n',
]


def test_a_thinking_only_reply_says_why_it_is_empty():
    events = _collect_notice(_THINKING_ONLY)
    text = "".join(e.get("content") or "" for e in events)
    assert text, "an empty answer must not be streamed as silence"
    assert "output budget" in text and "ask again" in text


def test_a_real_reply_is_untouched_by_the_notice():
    events = _collect_notice(_TEXT_STREAM)
    text = "".join(e.get("content") or "" for e in events)
    assert text == "## Canon\n"
    assert "output budget" not in text


def test_a_truncated_but_present_reply_gets_no_notice():
    """stop_reason=max_tokens WITH text is a normal truncation, not an empty answer."""
    lines = [*_TEXT_STREAM[:-1],
             'data: {"type":"message_delta","delta":{"stop_reason":"max_tokens"}}\n\n']
    text = "".join(e.get("content") or "" for e in _collect_notice(lines))
    assert text == "## Canon\n"


def test_the_sweep_ceiling_leaves_room_to_think():
    from app import config
    assert config.MUSE_NUM_PREDICT >= 12000, "thinking spends the same budget as the answer"

"""Upstream LLM transport — one dialect internally, three on the wire (D20, D42).

The Muse speaks exactly one dialect of its own (the *Ollama* shape):

    payload  = {"model", "messages", "options": {"num_predict", "temperature"},
                "tools": [...], "stream": bool}
    event    = {"message": {"content": str, "tool_calls": [{function:{name,
                                                                   arguments}}]}}

That shape is what every Muse feature is written against — think-stripping, the
agentic tool loop, canon context, the style digest, thread persistence. This
module is the *only* place that knows a provider might want something else, so
switching brains never means forking the Muse.

`KATHA_MUSE_API` selects the wire dialect:

    ollama  (default)  POST {OLLAMA_BASE}/api/chat         NDJSON, LAN box, no key
    openai             POST {MUSE_API_BASE}/chat/completions
                                                           SSE, bearer key
    anthropic          POST {MUSE_API_BASE}/messages       SSE, x-api-key

The anthropic dialect exists because some gateways serve a Claude model *only*
in the Messages shape and answer
`400 unsupported_model: … must be called via /provider/v1/messages` on the
OpenAI one. A provider that publishes `supported_endpoints` per model in
`GET /models` is telling you exactly which dialect to use — read it, don't guess
a model alias.

Nothing here holds a client of its own: `muse.py` passes its module-level
`_client`, so the existing test pattern
(`monkeypatch.setattr(muse_mod, "_client", …)`) covers every dialect.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from .config import (
    MUSE_API,
    MUSE_API_BASE,
    MUSE_API_KEY,
    MUSE_UPSTREAM_CONNECT_TIMEOUT,
    MUSE_UPSTREAM_TIMEOUT,
    OLLAMA_BASE,
)

OLLAMA = "ollama"
OPENAI = "openai"
# The Messages dialect is named after the ENDPOINT it posts to, not the vendor
# that invented the shape: this is what a *gateway* asks for. Traffic still goes
# to MUSE_API_BASE, so a commandcode/OpenRouter-style base is the normal case.
MESSAGES = "messages"
ANTHROPIC = "anthropic"  # accepted alias for the same wire shape
MESSAGES_SHAPES = (MESSAGES, ANTHROPIC)

# The Messages shape asks for a version pin; gateways generally ignore the value
# but native Anthropic rejects a request without one.
ANTHROPIC_VERSION = "2023-06-01"

# `max_tokens` is required by the Messages shape and has no server default.
DEFAULT_MAX_TOKENS = 4096


# --- mode / request shape -------------------------------------------------

def is_openai() -> bool:
    """True when the Muse is routed at an OpenAI-compatible gateway."""
    return MUSE_API == OPENAI


def is_messages() -> bool:
    """True when the Muse posts the Messages shape — `POST {base}/messages`
    with an `x-api-key`, which is what gateways require for Claude models."""
    return MUSE_API in MESSAGES_SHAPES


def _uses_keyed_base() -> bool:
    """Both keyed dialects read MUSE_API_BASE; ollama reads OLLAMA_BASE."""
    return is_openai() or is_messages()


def base_url() -> str:
    """Upstream base URL for the active mode (no trailing slash).

    In the keyed modes an empty base falls back to `OLLAMA_BASE` on purpose: a
    gateway fronting the same box (jengas) is the least surprising default.
    """
    base = MUSE_API_BASE if _uses_keyed_base() else OLLAMA_BASE
    return (base or OLLAMA_BASE).rstrip("/")


def chat_url() -> str:
    """The endpoint the active dialect is POSTed to."""
    if is_messages():
        return f"{base_url()}/messages"
    if is_openai():
        return f"{base_url()}/chat/completions"
    return f"{base_url()}/api/chat"


def headers() -> dict[str, str]:
    """Auth headers. The key is a header, never a body field: it must never
    reach a log line, an error message, or an API response."""
    if is_messages() and MUSE_API_KEY:
        return {"x-api-key": MUSE_API_KEY, "anthropic-version": ANTHROPIC_VERSION}
    if is_openai() and MUSE_API_KEY:
        return {"Authorization": f"Bearer {MUSE_API_KEY}"}
    return {}


def timeout() -> httpx.Timeout:
    """Per-request timeout: stream timeouts are generous, but *connecting* to a
    dead upstream must fail in seconds (D23). A blackholed host otherwise hangs
    the Muse UI for the full MUSE_UPSTREAM_TIMEOUT with no error at all."""
    return httpx.Timeout(MUSE_UPSTREAM_TIMEOUT, connect=MUSE_UPSTREAM_CONNECT_TIMEOUT)


# --- payload translation (internal -> OpenAI wire) -------------------------

def _tool_call_out(call: dict, index: int) -> dict:
    """Internal tool call -> OpenAI tool call.

    Arguments are stored internally either as a dict (the model's parsed
    arguments) or as the raw JSON string; the wire always wants the string.
    """
    fn = call.get("function") or {}
    args = fn.get("arguments")
    if not isinstance(args, str):
        args = json.dumps(args or {}, ensure_ascii=False)
    return {
        "id": call.get("id") or f"call_{index}",
        "type": "function",
        "function": {"name": fn.get("name") or "", "arguments": args},
    }


def to_openai_messages(messages: list[dict]) -> list[dict]:
    """Convert the internal message list to OpenAI's.

    Two differences matter:

    * an assistant tool-call turn needs `id` + `type` and string arguments;
    * a tool result needs `tool_call_id` (we tag results with `tool_name`
      internally, so pair them back with the calls that are still awaiting a
      result — in order, matching by name when there's a choice).
    """
    out: list[dict] = []
    pending: list[tuple[str, str]] = []  # (tool name, call id) awaiting a result

    for i, msg in enumerate(messages):
        role = msg.get("role") or "user"
        if role == "assistant" and msg.get("tool_calls"):
            calls = [_tool_call_out(tc, i * 100 + j) for j, tc in enumerate(msg["tool_calls"])]
            for call in calls:
                pending.append((call["function"]["name"], call["id"]))
            out.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": calls,
            })
        elif role == "tool":
            name = msg.get("tool_name") or ""
            call_id = msg.get("tool_call_id")
            if not call_id:
                idx = next((k for k, (n, _) in enumerate(pending) if n == name), None)
                if idx is None and pending:
                    idx = 0
                call_id = pending.pop(idx)[1] if idx is not None else (name or "call_unknown")
            out.append({
                "role": "tool",
                "tool_call_id": call_id,
                "content": msg.get("content") or "",
            })
        else:
            out.append({"role": role, "content": msg.get("content") or ""})

    return out


def to_openai_payload(payload: dict) -> dict:
    """Internal payload -> OpenAI /chat/completions body."""
    opts = payload.get("options") or {}
    body: dict[str, Any] = {
        "model": payload.get("model"),
        "messages": to_openai_messages(payload.get("messages") or []),
        "stream": bool(payload.get("stream")),
    }
    if "num_predict" in opts:
        # Internal `num_predict` is Ollama's name for the completion ceiling.
        body["max_tokens"] = opts["num_predict"]
    if "temperature" in opts:
        body["temperature"] = opts["temperature"]
    if payload.get("tools"):
        # Already OpenAI shape internally ({"type": "function", "function": …}).
        body["tools"] = payload["tools"]
    return body


# --- payload translation (internal -> Anthropic Messages wire) -------------

def _tool_use_id(call: dict, i: int, j: int) -> str:
    """A stable id for a tool call the model made without naming one."""
    return call.get("id") or f"toolu_{i}_{j}"


def _tool_input(call: dict) -> dict:
    """Internal arguments are a dict or a raw JSON string; the wire wants a dict."""
    args = (call.get("function") or {}).get("arguments")
    if isinstance(args, str):
        try:
            return json.loads(args) or {}
        except json.JSONDecodeError:
            return {}
    return args or {}


def to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Internal message list -> Messages API `messages`.

    Three things the internal shape doesn't state and the wire does:

    * `system` turns are not messages at all — they become the top-level
      `system` field (see `to_anthropic_payload`);
    * a tool result is a `tool_result` block inside a **user** turn, paired to
      its `tool_use` by id — internally results only carry `tool_name`, so they
      are paired with the calls still awaiting one, by name (exactly as the
      OpenAI path does);
    * roles must alternate, so consecutive same-role turns get merged into one.
    """
    turns: list[tuple[str, list[dict]]] = []
    pending: list[tuple[str, str]] = []  # (tool name, tool_use id) awaiting a result

    def _push(role: str, blocks: list[dict]) -> None:
        if turns and turns[-1][0] == role:
            turns[-1][1].extend(blocks)
        else:
            turns.append((role, blocks))

    for i, msg in enumerate(messages):
        role = msg.get("role") or "user"
        if role == "system":
            continue
        if role == "assistant" and msg.get("tool_calls"):
            blocks: list[dict] = []
            if msg.get("content"):
                blocks.append({"type": "text", "text": msg["content"]})
            for j, tc in enumerate(msg["tool_calls"]):
                call_id = _tool_use_id(tc, i, j)
                pending.append(((tc.get("function") or {}).get("name") or "", call_id))
                blocks.append({
                    "type": "tool_use",
                    "id": call_id,
                    "name": (tc.get("function") or {}).get("name") or "",
                    "input": _tool_input(tc),
                })
            _push("assistant", blocks)
        elif role == "tool":
            name = msg.get("tool_name") or ""
            call_id = msg.get("tool_call_id")
            if not call_id:
                idx = next((k for k, (n, _) in enumerate(pending) if n == name), None)
                if idx is None and pending:
                    idx = 0
                call_id = pending.pop(idx)[1] if idx is not None else "toolu_unknown"
            _push("user", [{
                "type": "tool_result",
                "tool_use_id": call_id,
                "content": msg.get("content") or "",
            }])
        else:
            _push(role, [{"type": "text", "text": msg.get("content") or ""}])

    return [{"role": role, "content": blocks} for role, blocks in turns]


def to_anthropic_payload(payload: dict) -> dict:
    """Internal payload -> Messages API body (`POST {base}/messages`)."""
    opts = payload.get("options") or {}
    msgs = payload.get("messages") or []
    system = "\n\n".join(
        m.get("content") or "" for m in msgs if (m.get("role") or "") == "system"
    ).strip()

    body: dict[str, Any] = {
        "model": payload.get("model"),
        "messages": to_anthropic_messages(msgs),
        # Required by the shape and with no default of its own.
        "max_tokens": int(opts.get("num_predict") or DEFAULT_MAX_TOKENS),
        "stream": bool(payload.get("stream")),
    }
    if system:
        body["system"] = system
    # `temperature` is deliberately NOT forwarded, even though the internal
    # payload carries one. Current Claude models reject sampling parameters
    # outright — `400 invalid_request_error: temperature is deprecated for this
    # model` — and the Messages shape treats them as optional anyway. Losing the
    # knob is better than losing the answer. (If a gateway ever wants it back,
    # this is the one line to restore.)
    if payload.get("tools"):
        # Internally OpenAI-shaped ({"type": "function", "function": …}); the
        # Messages shape flattens it and calls the schema `input_schema`.
        body["tools"] = [
            {
                "name": (t.get("function") or {}).get("name") or "",
                "description": (t.get("function") or {}).get("description") or "",
                "input_schema": (t.get("function") or {}).get("parameters")
                or {"type": "object", "properties": {}},
            }
            for t in payload["tools"]
        ]
    return body


# --- streaming ------------------------------------------------------------

async def _stream_ollama(payload: dict, client: httpx.AsyncClient) -> AsyncIterator[dict]:
    """NDJSON lines of Ollama chat chunks -> normalized events."""
    async with client.stream(
        "POST", chat_url(), json={**payload, "stream": True},
        headers=headers(), timeout=timeout(),
    ) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = obj.get("message") or {}
            event: dict[str, Any] = {}
            if msg.get("content"):
                event["content"] = msg["content"]
            if msg.get("tool_calls"):
                event["tool_calls"] = msg["tool_calls"]
            if event:
                yield event


async def _stream_openai(payload: dict, client: httpx.AsyncClient) -> AsyncIterator[dict]:
    """OpenAI SSE deltas -> normalized events.

    Content streams straight through. Tool calls arrive as *fragments* keyed by
    index (the id once, the name once, the arguments in pieces), so they are
    reassembled and emitted as one complete, internal-shaped call list at the
    end of the stream — exactly what the Ollama path produces.
    """
    body = to_openai_payload({**payload, "stream": True})
    calls: dict[int, dict] = {}

    async with client.stream(
        "POST", chat_url(), json=body, headers=headers(), timeout=timeout(),
    ) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue

            choices = obj.get("choices") or []
            if not choices:
                continue
            choice = choices[0] or {}
            # Streaming chunks carry `delta`; a few gateways send a whole
            # `message` on the final chunk instead.
            delta = choice.get("delta") or choice.get("message") or {}

            # `reasoning_content` / `reasoning` is the think channel — never
            # forwarded (in ollama mode ThinkStreamFilter handles the same job).
            content = delta.get("content")
            if content:
                yield {"content": content}

            for frag in delta.get("tool_calls") or []:
                idx = frag.get("index")
                if idx is None:
                    idx = len(calls)
                slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if frag.get("id"):
                    slot["id"] = frag["id"]
                fn = frag.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["arguments"] += fn["arguments"]

    if calls:
        yield {"tool_calls": [
            {
                "id": slot["id"] or f"call_{idx}",
                "type": "function",
                "function": {
                    "name": slot["name"],
                    "arguments": slot["arguments"] or "{}",
                },
            }
            for idx, slot in sorted(calls.items())
        ]}


async def _stream_anthropic(payload: dict, client: httpx.AsyncClient) -> AsyncIterator[dict]:
    """Anthropic Messages SSE -> normalized events.

    Text arrives as `text_delta`. Tool calls open with a `tool_use` block whose
    arguments then arrive as `input_json_delta` fragments — the same fragment
    problem the OpenAI path has, so it gets the same treatment: collect by block
    index and emit one complete, internal-shaped call list at the end of the
    stream. A provider-side `error` event is raised so it surfaces to the author
    as the existing `[ERROR]` line instead of a silent empty reply.
    """
    body = to_anthropic_payload({**payload, "stream": True})
    calls: dict[int, dict] = {}

    async with client.stream(
        "POST", chat_url(), json=body, headers=headers(), timeout=timeout(),
    ) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue

            kind = obj.get("type")
            if kind == "error":
                err = obj.get("error") or {}
                raise RuntimeError(err.get("message") or "upstream error")

            if kind == "content_block_start":
                block = obj.get("content_block") or {}
                if block.get("type") == "tool_use":
                    slot = calls.setdefault(
                        obj.get("index") or 0,
                        {"id": "", "name": "", "arguments": ""},
                    )
                    slot["id"] = block.get("id") or slot["id"]
                    slot["name"] = block.get("name") or slot["name"]
                    # A non-streaming provider may hand over the whole `input`.
                    given = block.get("input")
                    if isinstance(given, dict) and given:
                        slot["arguments"] += json.dumps(given)
            elif kind == "content_block_delta":
                delta = obj.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield {"content": delta["text"]}
                elif delta.get("type") == "input_json_delta":
                    slot = calls.setdefault(
                        obj.get("index") or 0,
                        {"id": "", "name": "", "arguments": ""},
                    )
                    slot["arguments"] += delta.get("partial_json") or ""

    if calls:
        yield {"tool_calls": [
            {
                "id": slot["id"] or f"call_{idx}",
                "type": "function",
                "function": {
                    "name": slot["name"],
                    "arguments": slot["arguments"] or "{}",
                },
            }
            for idx, slot in sorted(calls.items())
        ]}


async def stream_events(payload: dict, client: httpx.AsyncClient) -> AsyncIterator[dict]:
    """Stream normalized `{"content"|"tool_calls"}` events from the active upstream."""
    if is_messages():
        gen = _stream_anthropic(payload, client)
    elif is_openai():
        gen = _stream_openai(payload, client)
    else:
        gen = _stream_ollama(payload, client)
    async for event in gen:
        yield event


# --- one-shot completion (style digest) -----------------------------------

async def complete(payload: dict, client: httpx.AsyncClient) -> dict:
    """Non-streaming single completion, returned in the internal shape
    (`{"message": {"content": str}}`) so callers need no mode awareness."""
    if is_messages():
        r = await client.post(
            chat_url(), json=to_anthropic_payload({**payload, "stream": False}),
            headers=headers(), timeout=timeout(),
        )
        r.raise_for_status()
        blocks = r.json().get("content") or []
        text = "".join(b.get("text") or "" for b in blocks if b.get("type") == "text")
        return {"message": {"content": text}}

    if is_openai():
        body = to_openai_payload({**payload, "stream": False})
        r = await client.post(chat_url(), json=body, headers=headers(), timeout=timeout())
        r.raise_for_status()
        choices = (r.json().get("choices") or [{}])
        msg = (choices[0] or {}).get("message") or {}
        return {"message": {"content": msg.get("content") or ""}}

    r = await client.post(
        chat_url(), json={**payload, "stream": False},
        headers=headers(), timeout=timeout(),
    )
    r.raise_for_status()
    obj = r.json()
    return {"message": {"content": (obj.get("message") or {}).get("content") or ""}}

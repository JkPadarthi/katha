"""Upstream LLM transport — one dialect internally, two on the wire (D20).

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

    ollama  (default)  POST {OLLAMA_BASE}/api/chat        NDJSON, LAN box, no key
    openai             POST {MUSE_API_BASE}/chat/completions
                                                          SSE, bearer key

Nothing here holds a client of its own: `muse.py` passes its module-level
`_client`, so the existing test pattern
(`monkeypatch.setattr(muse_mod, "_client", …)`) covers both dialects.
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


# --- mode / request shape -------------------------------------------------

def is_openai() -> bool:
    """True when the Muse is routed at an OpenAI-compatible gateway."""
    return MUSE_API == OPENAI


def base_url() -> str:
    """Upstream base URL for the active mode (no trailing slash).

    In openai mode an empty base falls back to `OLLAMA_BASE` on purpose: a
    gateway fronting the same box (jengas) is the least surprising default.
    """
    base = MUSE_API_BASE if is_openai() else OLLAMA_BASE
    return (base or OLLAMA_BASE).rstrip("/")


def chat_url() -> str:
    """The one endpoint both dialects are POSTed to."""
    return f"{base_url()}/chat/completions" if is_openai() else f"{base_url()}/api/chat"


def headers() -> dict[str, str]:
    """Auth headers. The key is a header, never a body field: it must never
    reach a log line, an error message, or an API response."""
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


async def stream_events(payload: dict, client: httpx.AsyncClient) -> AsyncIterator[dict]:
    """Stream normalized `{"content"|"tool_calls"}` events from the active upstream."""
    gen = _stream_openai(payload, client) if is_openai() else _stream_ollama(payload, client)
    async for event in gen:
        yield event


# --- one-shot completion (style digest) -----------------------------------

async def complete(payload: dict, client: httpx.AsyncClient) -> dict:
    """Non-streaming single completion, returned in the internal shape
    (`{"message": {"content": str}}`) so callers need no mode awareness."""
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

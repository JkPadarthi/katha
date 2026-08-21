"""Muse proxy — talks to a friend's Ollama box, hides the upstream from the
client (D16/D17/D19).

Public functions:
    chat(messages, chapter_id=None, chip=None) -> AsyncIterator[str]
    rewrite(text, style, chapter_id=None)      -> AsyncIterator[str]

Both yield visible prose tokens (never <think> blocks). The HTTP layer wraps
these in SSE.

The Ollama client lives at module scope so tests can swap its transport via
`monkeypatch.setattr(muse_mod, "_client", mock_client)`.
"""

from __future__ import annotations

import json
import re
from typing import AsyncIterator

import httpx

from .config import (
    MUSE_CHAT_MODEL,
    MUSE_FALLBACK_MODEL,
    MUSE_MODEL,
    MUSE_NUM_PREDICT,
    MUSE_REWRITE_MODEL,
    MUSE_UPSTREAM_TIMEOUT,
    OLLAMA_BASE,
)

# Module-level client — patchable from tests.
_client = httpx.AsyncClient(timeout=MUSE_UPSTREAM_TIMEOUT)


# --- token stripping ------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think>.*$", re.DOTALL)  # unterminated


def strip_think(text: str) -> str:
    """Remove <think>…</think> blocks from a chunk of model output.

    Ollama streams token-by-token, so a single chunk may begin inside a
    thinking block. We strip complete blocks greedily; an unterminated
    opening is also stripped so the user never sees reasoning start.
    """
    text = _THINK_RE.sub("", text)
    text = _THINK_OPEN_RE.sub("", text)
    return text


# --- upstream call --------------------------------------------------------

async def _post_chat(payload: dict) -> AsyncIterator[str]:
    """POST to Ollama /api/chat with stream=True; yield visible-only deltas."""
    payload = {**payload, "stream": True}
    url = f"{OLLAMA_BASE.rstrip('/')}/api/chat"
    async with _client.stream("POST", url, json=payload) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = obj.get("message", {}).get("content", "")
            visible = strip_think(content)
            if visible:
                yield visible


# --- public: chat ---------------------------------------------------------

CHIP_PROMPTS: dict[str, str] = {
    "rewrite": "Rewrite the user's selected passage in proper novel English. Reply with ONLY the rewrite — no preamble, no explanation.",
    "continue": "Continue the scene from where it left off, matching the established voice and cadence. Write 1–3 paragraphs.",
    "scene": "Write a new scene that follows naturally from the current chapter. Include a setting, characters from the bible if relevant, and a hook at the end.",
    "canon": "Check the user's claim against the canon (the chapter text + bible). Reply with: VERIFIED / CONTRADICTS / UNCLEAR, then one short sentence explaining.",
}


async def chat(
    messages: list[dict],
    chapter_id: str | None = None,
    chip: str | None = None,
) -> AsyncIterator[str]:
    """Stream a chat reply from the Muse.

    `messages` is the full OpenAI-style thread (last item is the user turn).
    If `chip` is set, it's prepended as a system hint so the model knows the
    intent (rewrite/continue/scene/canon).
    """
    sys_parts: list[dict] = []
    if chip and chip in CHIP_PROMPTS:
        sys_parts.append({"role": "system", "content": CHIP_PROMPTS[chip]})
    full_messages = [*sys_parts, *messages]

    payload = {
        "model": MUSE_CHAT_MODEL,
        "messages": full_messages,
        "options": {"num_predict": MUSE_NUM_PREDICT, "temperature": 0.8},
    }
    async for delta in _post_chat(payload):
        yield delta


# --- public: rewrite ------------------------------------------------------

STYLE_PROMPTS: dict[str, str] = {
    "novel": "Rewrite the user's selection as polished literary prose. Maintain the original's voice but tighten cadence, vary sentence length, and surface sensory detail. Reply with ONLY the rewrite.",
    "scene": "Rewrite the selection as a vivid, cinematic scene. Strong verbs, specific nouns, present-tense energy. Reply with ONLY the rewrite.",
    "clean": "Clean up grammar and word choice with minimal stylistic change. Preserve the author's voice exactly; only fix the rough edges. Reply with ONLY the rewrite.",
}


async def rewrite(
    text: str,
    style: str = "novel",
    chapter_id: str | None = None,
) -> AsyncIterator[str]:
    """Stream a single rewrite proposal for `text` in the chosen `style`."""
    sys = STYLE_PROMPTS.get(style, STYLE_PROMPTS["novel"])
    payload = {
        "model": MUSE_REWRITE_MODEL,
        "messages": [
            {"role": "system", "content": sys},
            {"role": "user", "content": text},
        ],
        "options": {"num_predict": MUSE_NUM_PREDICT, "temperature": 0.7},
    }
    async for delta in _post_chat(payload):
        yield delta


# --- public: models info --------------------------------------------------

def models_info() -> dict:
    """Return the configured models + upstream base (for the UI)."""
    return {
        "default_model": MUSE_MODEL,
        "chat_model": MUSE_CHAT_MODEL,
        "rewrite_model": MUSE_REWRITE_MODEL,
        "fallback_model": MUSE_FALLBACK_MODEL,
        "ollama_base": OLLAMA_BASE,
    }

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
import re
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

_SSE_TOKEN_RE = re.compile(r"\\n|\\\\")   # wire tokens: escaped newline | escaped backslash


def _sse_un(m):
    return "\n" if m.group(0) == "\\n" else "\\"


def _payload_from_lines(lines) -> str:
    """Concatenate the data payloads from raw SSE lines (no prefix, no
    [DONE]/[STATUS]; asserts no [ERROR])."""
    out = []
    for line in lines:
        if not line.startswith("data:"):
            continue
        payload = line[6:] if len(line) > 5 and line[5] == " " else line[5:]
        if payload.strip() == "[DONE]" or payload.startswith("[STATUS]"):
            continue
        assert not payload.startswith("[ERROR]"), f"stream error event: {payload}"
        out.append(_SSE_TOKEN_RE.sub(_sse_un, payload))
    return "".join(out)


def _sse_payload(r) -> str:
    return _payload_from_lines(r.iter_lines())


def test_muse_rewrite_sse_roundtrips_backslashes_and_newlines(monkeypatch: pytest.MonkeyPatch):
    """Regression (0.3.x): the old sequential escape/unescape corrupted prose
    containing literal backslashes ('C:\\notes' became 'C:<newline>otes').
    The full server path — upstream chunks → _sse_escape → SSE wire — must
    reconstruct the original text exactly, real newlines included."""
    original = 'The map read C:\\new\\roads.\n\nKael followed it east.'
    chunks = [
        {"message": {"role": "assistant", "content": "The map read C:\\new\\roads."}, "done": False},
        {"message": {"role": "assistant", "content": "\n\nKael followed it east."}, "done": True},
    ]
    _patch_ollama(monkeypatch, _ollama_chat_ndjson(*chunks))

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/muse/rewrite",
            json={"text": "rewrite me", "style": "novel"},
        ) as r:
            assert r.status_code == 200
            payload = _sse_payload(r)

    assert payload == original


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

def test_thread_is_persisted_to_archive_dot_katha(tmp_path, monkeypatch):
    """When a Muse call carries a chapter_id, the exchange must be appended to
    `archive/.katha/muse/<chapter-slug>.md`."""
    import json as _json

    import httpx

    from app import muse as muse_mod
    from app.config import ARCHIVE_ROOT

    series_slug = ar.slugify("The Ember Throne")
    book_slug = ar.slugify("The First Flame")
    thread_path = ARCHIVE_ROOT / ".katha" / "muse" / "ch-01.md"

    # Clean any pre-existing file from earlier test runs.
    if thread_path.exists():
        thread_path.unlink()

    def _handler(request: httpx.Request) -> httpx.Response:
        body = _json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            content=_ollama_chat_ndjson(
                {"model": body.get("model", "gemma4:12b"),
                 "message": {"role": "assistant", "content": "mocked reply"},
                 "done": True},
            ),
        )

    transport = httpx.MockTransport(_handler)
    mock_client = httpx.AsyncClient(transport=transport, timeout=muse_mod._client.timeout)
    monkeypatch.setattr(muse_mod, "_client", mock_client)

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


def test_muse_persistence_dir_excluded_from_books_listing():
    """`/api/books` must NOT surface the Muse persistence directory
    (`archive/.katha/`) as a fake series. Otherwise the Rail shows a phantom
    empty book, App.jsx picks it as the first book, and the user sees a
    stuck 'Loading archive…' because the phantom book has no chapters."""
    from app import archive as ar_mod
    from app.config import ARCHIVE_ROOT

    # Plant a hidden directory that mirrors what Muse persistence writes.
    hidden = ARCHIVE_ROOT / ".katha" / "muse"
    hidden.mkdir(parents=True, exist_ok=True)
    # And a book.json that *would* be read if the dir were not hidden.
    (hidden / "book.json").write_text(
        '{"id": "muse", "series": ".katha", "title": "muse"}',
        encoding="utf-8",
    )

    try:
        books = ar_mod.list_books()
        # Must not contain a series whose slug starts with "."
        slugs = [b["series"] for b in books]
        assert not any(s.startswith(".") for s in slugs), (
            f"hidden directory leaked into books listing: {slugs}"
        )
        # And the real series must still be present.
        assert "the-ember-throne" in slugs
    finally:
        # Cleanup — both the file and the directory.
        (hidden / "book.json").unlink(missing_ok=True)
        # Leave the parent dirs; tests run on a temp archive normally.


def test_muse_persistence_dir_excluded_from_search_index():
    """`iter_searchable_docs` must NOT yield docs from `.katha/` — otherwise
    Muse threads leak into chapter search. Tests with a realistic structure:
    a hidden `.katha/<book>/chapters/` subtree."""
    from app import archive as ar_mod
    from app.config import ARCHIVE_ROOT

    hidden = ARCHIVE_ROOT / ".katha" / "muse-fake" / "chapters"
    hidden.mkdir(parents=True, exist_ok=True)
    # A would-be chapter file inside the hidden dir.
    (hidden / "ch-01.md").write_text(
        "# hidden\n\nThis is Muse persistence and must not be searchable.",
        encoding="utf-8",
    )

    try:
        for kind, series, *_ in ar_mod.iter_searchable_docs():
            assert not series.startswith("."), f"hidden series {series} leaked into search"
    finally:
        (hidden / "ch-01.md").unlink(missing_ok=True)
        hidden.rmdir()
        (hidden.parent).rmdir()


def test_style_digest_auto_generated_on_first_touch(monkeypatch: pytest.MonkeyPatch):
    """First call for a book with no cached digest: the Muse generates one
    via the rewrite model and writes it to disk."""
    import asyncio

    import httpx

    from app import muse as muse_mod
    from app.config import ARCHIVE_ROOT

    series_slug = ar.slugify("The Ember Throne")
    book_slug = ar.slugify("The First Flame")
    digest_path = ARCHIVE_ROOT / ".katha" / "muse" / f"style-{book_slug}.md"

    # Clean any pre-existing digest from earlier test runs.
    if digest_path.exists():
        digest_path.unlink()

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "model": body.get("model", "deepseek-r1:14b"),
                "message": {"role": "assistant", "content": "Auto-generated style fingerprint."},
                "done": True,
            },
        )

    transport = httpx.MockTransport(_handler)
    mock_client = httpx.AsyncClient(transport=transport, timeout=muse_mod._client.timeout)
    monkeypatch.setattr(muse_mod, "_client", mock_client)

    digest = asyncio.run(
        muse_mod._load_style_summary(book_slug, ARCHIVE_ROOT / series_slug / book_slug)
    )

    assert "Auto-generated" in digest
    assert digest_path.exists()
    assert "Auto-generated" in digest_path.read_text(encoding="utf-8")


# --- canon sweep (0.4) ----------------------------------------------------

def test_sweep_report_streams(monkeypatch: pytest.MonkeyPatch):
    """`/api/muse/sweep` with target='report' streams a whole-book continuity
    audit built from the manuscript + bible."""
    chunks = [
        {"model": "deepseek-r1:14b", "message": {"role": "assistant", "content": "## Report\n"}, "done": False},
        {"model": "deepseek-r1:14b", "message": {"role": "assistant", "content": "Kael's eyes change colour."}, "done": True},
    ]
    _patch_ollama(monkeypatch, _ollama_chat_ndjson(*chunks))

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/muse/sweep",
            json={
                "series": ar.slugify("The Ember Throne"),
                "book_id": ar.slugify("The First Flame"),
                "target": "report",
            },
        ) as r:
            assert r.status_code == 200
            assert "text/event-stream" in r.headers["content-type"]
            payload = _sse_payload(r)

    assert "Report" in payload
    assert "eyes change colour" in payload


def test_sweep_bible_streams_and_approval_writes(monkeypatch: pytest.MonkeyPatch):
    """target='bible' streams a proposed rewrite of one bible file. The
    approval step (PUT) then writes it to disk — md is the truth."""
    from app.config import ARCHIVE_ROOT

    proposed_text = "# Characters\n\n## Kael\n- Grey eyes, carries a debt.\n"
    chunks = [
        {"model": "deepseek-r1:14b",
         "message": {"role": "assistant", "content": proposed_text},
         "done": True},
    ]
    _patch_ollama(monkeypatch, _ollama_chat_ndjson(*chunks))

    name = "sweep-check.md"
    series_slug, book_slug = ar.slugify("The Ember Throne"), ar.slugify("The First Flame")

    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/muse/sweep",
            json={"series": series_slug, "book_id": book_slug,
                  "target": "bible", "bible_name": name},
        ) as r:
            assert r.status_code == 200
            proposed = _sse_payload(r)

        put = client.put(
            f"/api/books/{series_slug}/{book_slug}/bible/{name}",
            json={"content": proposed},
        )
        assert put.status_code == 200
        assert put.json()["files"][name] == proposed

    on_disk = (ARCHIVE_ROOT / series_slug / book_slug / "bible" / name).read_text(encoding="utf-8")
    assert on_disk == proposed


def test_sweep_bible_rejects_bad_name(monkeypatch: pytest.MonkeyPatch):
    _patch_ollama(monkeypatch, _ollama_chat_ndjson(
        {"model": "deepseek-r1:14b", "message": {"role": "assistant", "content": "x"}, "done": True}
    ))
    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/muse/sweep",
            json={"series": ar.slugify("The Ember Throne"),
                  "book_id": ar.slugify("The First Flame"),
                  "target": "bible", "bible_name": "notes"},
        ) as r:
            payload = _sse_payload(r)
    assert "Invalid bible file name." in payload


# --- agentic chat: the model fetches story files via tools (1.1) ----------

def _agent_client(seen: list):
    """MockTransport: returns a read_story_file tool call on the first request,
    the final answer once a tool result is present."""
    import httpx

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen.append(body)
        has_tool = any(m.get("role") == "tool" for m in body.get("messages", []))
        if has_tool:
            chunk = {"model": "gemma4:12b",
                     "message": {"role": "assistant", "content": "It opens at Crosswater."},
                     "done": True}
        else:
            chunk = {"model": "gemma4:12b",
                     "message": {"role": "assistant", "content": "", "tool_calls": [
                         {"function": {"name": "read_story_file",
                                       "arguments": {"path": "chapters/ch-01.md"}}}]},
                     "done": True}
        return httpx.Response(200, content=_ollama_chat_ndjson(chunk),
                              headers={"content-type": "application/x-ndjson"})

    from app import muse as muse_mod
    return httpx.AsyncClient(transport=httpx.MockTransport(_handler),
                             timeout=muse_mod._client.timeout)


def test_chat_is_agentic_and_fetches_story(monkeypatch: pytest.MonkeyPatch):
    """With a chapter_id, the Muse is handed tools; the model's tool_call runs
    against the real archive and its result is fed back before the answer."""
    from app import muse as muse_mod

    seen: list = []
    monkeypatch.setattr(muse_mod, "_client", _agent_client(seen))

    chapter_id = f"{ar.slugify('The Ember Throne')}/{ar.slugify('The First Flame')}/ch-01"
    with TestClient(app) as client:
        with client.stream(
            "POST", "/api/muse/chat",
            json={"messages": [{"role": "user", "content": "What happened first?"}],
                  "chapter_id": chapter_id},
        ) as r:
            assert r.status_code == 200
            lines = list(r.iter_lines())

    # A [STATUS] progress event announced the fetch.
    assert any("[STATUS]" in ln and "ch-01" in ln for ln in lines)
    # The final payload is the model's answer.
    assert "Crosswater" in _payload_from_lines(lines)

    # The tool actually ran: a follow-up carried the chapter text back.
    followups = [b for b in seen if any(m.get("role") == "tool" for m in b.get("messages", []))]
    assert followups, "model did not receive a tool result"
    tool_msgs = [m for m in followups[-1]["messages"] if m.get("role") == "tool"]
    expected = (ar.book_dir("The Ember Throne", "The First Flame")
                / "chapters" / "ch-01.md").read_text(encoding="utf-8")
    assert tool_msgs[0]["content"] == expected


def test_story_tools_refuse_path_escapes():
    """The tools are the security boundary: no '.katha/', no '..', no absolute."""
    from app import muse as muse_mod

    ctx = muse_mod._tool_ctx(
        f"{ar.slugify('The Ember Throne')}/{ar.slugify('The First Flame')}/ch-01")
    assert ctx is not None

    for bad in (".katha/muse/ch-01.md", "../other-book/ch-01.md", "/etc/passwd"):
        out = muse_mod._run_tool(ctx, "read_story_file", {"path": bad})
        assert out.startswith("ERROR"), bad

    ok = muse_mod._run_tool(ctx, "read_story_file", {"path": "chapters/ch-01.md"})
    expected = (ar.book_dir("The Ember Throne", "The First Flame")
                / "chapters" / "ch-01.md").read_text(encoding="utf-8")
    assert ok == expected


def test_story_tool_lists_files():
    from app import muse as muse_mod

    ctx = muse_mod._tool_ctx(
        f"{ar.slugify('The Ember Throne')}/{ar.slugify('The First Flame')}/ch-01")
    listing = muse_mod._run_tool(ctx, "list_story_files", {})
    assert "chapters/ch-01.md" in listing
    assert "bible/characters/kael.md" in listing
    assert ".katha" not in listing

    # a nested bible file is readable by the tool
    ok = muse_mod._run_tool(ctx, "read_story_file", {"path": "bible/characters/kael.md"})
    assert "Kael" in ok

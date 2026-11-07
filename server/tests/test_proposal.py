"""Whole-chapter proposals (2.9, D45) — the Muse proposes, the author disposes.

What this net has to hold:

1. **A proposal is parked, never applied.** The chapter file and its revision
   counter are untouched by the tool call — the Muse has no write access, and
   nothing an LLM says may rewrite the author's prose unattended.
2. **Accept is a normal save.** It goes through the same path as autosave, so the
   md is rewritten, a revision snapshot is taken (D9), the FTS index is updated and
   the proposal is consumed. The heading the Muse sent is used once, not twice.
3. **Discard is honest** — the chapter was never touched, and an accepted-then-gone
   proposal is a 404.
4. **Bad revisions are refused with a message to the model**: too short, or
   identical to the chapter as it stands. No `[PROPOSAL]` event, nothing on disk.
5. **The prompt tells the model the truth**: the tool is offered, and the result
   says NOT saved + do not paste the chapter into the chat.
6. **Ids are uninhabitable**: a traversal-shaped id is a 404, not a file read.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

_TMP = tempfile.mkdtemp(prefix="katha-proposal-test-")
os.environ["KATHA_ARCHIVE"] = str(Path(_TMP) / "archive")
os.environ["KATHA_DATA"] = str(Path(_TMP) / "data")

from app import archive as ar  # noqa: E402
from app import auth as auth_mod  # noqa: E402
from app import muse as muse_mod  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

SERIES = "Proposal Shelf"
BOOK = "Revision Book"
SID = ar.slugify(SERIES)
BID = ar.slugify(BOOK)

OLD_BODY = "\n\n".join(f"old line {i}, the ember guttered in the dark." for i in range(12))
# Comfortably over PROPOSAL_MIN_CHARS — a real revision, not a fragment. (A fixture
# that is too short gets refused by the guard, which is its own test below.)
NEW_BODY = "\n\n".join([
    "The ember had guttered, and Kael stood in the ash of it.",
    "He counted the coins he still owed and said nothing.",
    "Morning came grey and unforgiving over the harbour.",
    "The innkeeper had left a lamp burning on the sill for him.",
    "He did not thank her, and she did not expect it.",
    "Later, on the road, he would think of the debt and of the fire.",
    "For now he only walked, and the mist took the rest.",
])
NEW_TEXT = f"# The New Chapter\n\n{NEW_BODY}\n"

_CHAPTER: dict = {}


def _ndjson(*chunks: dict) -> bytes:
    return "\n".join(json.dumps(c) for c in chunks).encode("utf-8") + b"\n"


@pytest.fixture(scope="module", autouse=True)
def _book():
    r = client.post("/api/books", json={"series": SERIES, "title": BOOK})
    assert r.status_code == 201
    r = client.post(f"/api/books/{SID}/{BID}/chapters",
                    json={"title": "The Old Chapter", "content": OLD_BODY})
    assert r.status_code == 201
    _CHAPTER["id"] = r.json()["id"]
    yield


def _chapter_file() -> Path:
    p = ar.get_chapter(ar.book_dir(SERIES, BOOK), _CHAPTER["id"])
    assert p is not None
    return p


def _chapter_id() -> str:
    return _CHAPTER["id"]


def _mine() -> list[dict]:
    """Pending proposals for THIS chapter only (the list is archive-wide)."""
    return [p for p in muse_mod.list_proposals()
            if p["book"] == BID and p["chapter"] == _chapter_id()]


def _chat(monkeypatch: pytest.MonkeyPatch, content: str, *, turn1_text: str = ""):
    """One /api/muse/chat turn in which the model calls propose_chapter_rewrite.

    Returns (sse_text, events, upstream_bodies) where events are (kind, payload)
    pairs parsed out of the SSE stream.
    """
    bodies: list[dict] = []
    state = {"turn": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8") or "{}")
        bodies.append(body)
        if not body.get("stream"):
            # the style digest — one-shot, not streamed
            return httpx.Response(200, json={"message": {"role": "assistant",
                                                         "content": "terse."}})
        state["turn"] += 1
        if state["turn"] == 1:
            return httpx.Response(200, content=_ndjson({
                "message": {
                    "role": "assistant",
                    "content": turn1_text,
                    "tool_calls": [{"function": {
                        "name": "propose_chapter_rewrite",
                        "arguments": {"content": content}}}],
                },
                "done": True,
            }))
        return httpx.Response(200, content=_ndjson({
            "message": {"role": "assistant", "content": "Ready for your review."},
            "done": True,
        }))

    real = muse_mod._client
    monkeypatch.setattr(muse_mod, "_client",
                        httpx.AsyncClient(transport=httpx.MockTransport(_handler),
                                          timeout=real.timeout))

    with TestClient(app) as c:
        with c.stream("POST", "/api/muse/chat", json={
            "messages": [{"role": "user", "content": "fix the chapter"}],
            "chapter_id": f"{SID}/{BID}/{_chapter_id()}",
        }) as r:
            assert r.status_code == 200
            sse = "".join(r.iter_text())

    events: list[tuple[str, str]] = []
    for line in sse.split("\n"):
        if not line.startswith("data:"):
            continue
        payload = line[6:] if len(line) > 5 and line[5] == " " else line[5:]
        if payload.startswith("[STATUS]"):
            events.append(("status", payload[8:].strip()))
        elif payload.startswith("[PROPOSAL]"):
            events.append(("proposal", payload[10:].strip()))
        elif payload.startswith("[ERROR]"):
            events.append(("error", payload[7:].strip()))
    return sse, events, bodies


def _streamed(bodies: list[dict]) -> list[dict]:
    """Only the streamed chat turns — the first request is often the style digest,
    which is a one-shot and carries no tools."""
    return [b for b in bodies if b.get("stream")]


def _make_proposal(monkeypatch: pytest.MonkeyPatch, content: str = NEW_TEXT) -> str:
    sse, events, _ = _chat(monkeypatch, content)
    pids = [p for k, p in events if k == "proposal"]
    assert pids, f"no proposal in stream: {sse[:300]}"
    return pids[-1]


# --- 1. a proposal is parked, never applied --------------------------------

def test_the_muse_tool_is_offered_and_says_it_is_not_saved(monkeypatch: pytest.MonkeyPatch):
    _, _, bodies = _chat(monkeypatch, NEW_TEXT)
    tools = _streamed(bodies)[0].get("tools") or []
    names = [(t.get("function") or {}).get("name") for t in tools]
    assert "propose_chapter_rewrite" in names
    desc = next((t["function"]["description"] for t in tools
                 if t["function"]["name"] == "propose_chapter_rewrite"), "")
    assert "NOT saved" in desc and "cannot save it" in desc


def test_a_proposal_leaves_the_chapter_and_its_revision_untouched(monkeypatch: pytest.MonkeyPatch):
    file = _chapter_file()
    before_text = file.read_text(encoding="utf-8")
    before_rev = ar._read_revision_marker(file)

    pid = _make_proposal(monkeypatch)

    assert file.read_text(encoding="utf-8") == before_text, "the chapter was written!"
    assert ar._read_revision_marker(file) == before_rev
    stored = muse_mod.read_proposal(pid)
    assert stored is not None
    # stored trimmed, on purpose: leading/trailing blank lines are not prose
    assert stored["content"] == NEW_TEXT.strip()
    assert stored["chapter"] == _chapter_id() and stored["book"] == BID
    assert stored["words"] > 0


def test_the_model_is_told_it_is_a_proposal_and_not_to_paste_the_chapter(monkeypatch: pytest.MonkeyPatch):
    _, _, bodies = _chat(monkeypatch, NEW_TEXT)
    tool_msgs = [m for m in _streamed(bodies)[-1]["messages"] if m["role"] == "tool"]
    assert tool_msgs, "no tool result reached the model"
    assert "NOT saved" in tool_msgs[-1]["content"]
    assert "Do NOT paste" in tool_msgs[-1]["content"]


def test_the_stream_announces_the_revision_with_a_status_and_an_id(monkeypatch: pytest.MonkeyPatch):
    sse, events, _ = _chat(monkeypatch, NEW_TEXT)
    kinds = [k for k, _ in events]
    assert "status" in kinds and "proposal" in kinds
    statuses = " ".join(p for k, p in events if k == "status")
    assert "preparing a full-chapter revision" in statuses
    assert "[PROPOSAL]" in sse


# --- 2. accepting is a normal save ----------------------------------------

def test_accepting_applies_the_revision_as_a_normal_save(monkeypatch: pytest.MonkeyPatch):
    file = _chapter_file()
    rev_before = ar._read_revision_marker(file)
    snaps_before = len(ar.list_revisions(ar.book_dir(SERIES, BOOK), _chapter_id()) or [])
    pid = _make_proposal(monkeypatch)

    r = client.post(f"/api/muse/proposals/{pid}/accept")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["title"] == "The New Chapter"          # the heading the Muse sent
    assert out["revision"] == rev_before + 1

    text = file.read_text(encoding="utf-8")
    assert text.startswith("# The New Chapter\n\n")
    assert text.count("# The New Chapter") == 1       # not written twice
    assert "The ember had guttered" in text
    assert "old line 1," not in text

    # a revision snapshot exists, like any other save (D9)
    snaps_after = len(ar.list_revisions(ar.book_dir(SERIES, BOOK), _chapter_id()) or [])
    assert snaps_after == snaps_before + 1

    # the search index knows the new prose
    hits = client.get("/api/search", params={"q": "counted the coins"}).json()
    assert any(h.get("doc_id") == _chapter_id() for h in hits.get("hits", hits if isinstance(hits, list) else []))

    # and the proposal is consumed
    assert client.get(f"/api/muse/proposals/{pid}").status_code == 404
    assert pid not in [p["id"] for p in _mine()]


def test_a_revision_without_a_heading_keeps_the_chapters_title(monkeypatch: pytest.MonkeyPatch):
    pid = _make_proposal(monkeypatch, "No heading here at all. " + "still a body, still prose. " * 12)
    r = client.post(f"/api/muse/proposals/{pid}/accept")
    assert r.status_code == 200
    assert r.json()["title"] == "The New Chapter"     # unchanged from the last save


# --- 3. discarding is honest ----------------------------------------------

def test_discarding_never_touched_the_chapter(monkeypatch: pytest.MonkeyPatch):
    file = _chapter_file()
    before = file.read_text(encoding="utf-8")
    pid = _make_proposal(monkeypatch, "A different revision. " + "dithered. " * 30)

    r = client.delete(f"/api/muse/proposals/{pid}")
    assert r.status_code == 200
    assert file.read_text(encoding="utf-8") == before
    assert client.post(f"/api/muse/proposals/{pid}/accept").status_code == 404
    assert client.delete(f"/api/muse/proposals/{pid}").status_code == 404


# --- 4. bad revisions are refused, with a reason ---------------------------

def test_a_fragment_is_refused_and_nothing_is_parked(monkeypatch: pytest.MonkeyPatch):
    _, events, bodies = _chat(monkeypatch, "far too short")
    assert "proposal" not in [k for k, _ in events]
    tool_msg = [m for m in _streamed(bodies)[-1]["messages"] if m["role"] == "tool"][-1]
    assert tool_msg["content"].startswith("ERROR")
    assert "COMPLETE revision" in tool_msg["content"]


def test_a_revision_identical_to_the_chapter_is_refused(monkeypatch: pytest.MonkeyPatch):
    current = _chapter_file().read_text(encoding="utf-8")
    _, events, bodies = _chat(monkeypatch, current)
    assert "proposal" not in [k for k, _ in events]
    tool_msg = [m for m in _streamed(bodies)[-1]["messages"] if m["role"] == "tool"][-1]
    assert "identical" in tool_msg["content"]


# --- 5. housekeeping + hardening ------------------------------------------

def test_only_the_newest_three_revisions_are_kept(monkeypatch: pytest.MonkeyPatch):
    for i in range(muse_mod.PROPOSAL_KEEP + 1):
        _make_proposal(monkeypatch, f"# Revision {i}\n\n" + (f"draft number {i}. " * 40))
    keep = _mine()
    assert len(keep) == muse_mod.PROPOSAL_KEEP
    assert all(p["id"].startswith(f"{BID}-") for p in keep)
    drafts = [(muse_mod.read_proposal(p["id"]) or {}).get("content", "") for p in keep]
    assert not any("draft number 0." in d for d in drafts), "the oldest should be pruned"


def test_a_traversal_shaped_id_is_a_404_not_a_file_read():
    for bad in ("%2E%2E%2F%2E%2E%2Fetc%2Fpasswd", "..", "a%2Fb", ".hidden", "x" * 200):
        r = client.get(f"/api/muse/proposals/{bad}")
        assert r.status_code == 404, f"{bad} -> {r.status_code}"


def test_split_heading_takes_one_heading_and_no_more():
    body, title = muse_mod.split_heading("# Fire\n\nthe body\n", "Fallback")
    assert (title, body) == ("Fire", "the body")
    body, title = muse_mod.split_heading("\n\n# Fire\n\nthe body", "Fallback")
    assert (title, body) == ("Fire", "the body")
    body, title = muse_mod.split_heading("no heading at all", "Fallback")
    assert (title, body) == ("Fallback", "no heading at all")
    body, title = muse_mod.split_heading("# Fire\n\n## Section\n\nbody", "Fallback")
    assert body.startswith("## Section")          # only the first heading is the title


def test_the_proposal_routes_are_behind_the_lock(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth_mod, "PASSWORD", "s3cret-not-real")
    assert client.get("/api/muse/proposals").status_code == 401
    assert client.get("/api/muse/proposals/anything").status_code == 401
    assert client.post("/api/muse/proposals/anything/accept").status_code == 401
    assert client.delete("/api/muse/proposals/anything").status_code == 401


# --- 6. long chapters: room to write, and honesty when it runs out (2.9.1) ---

def _chat_raw(monkeypatch: pytest.MonkeyPatch, tool_calls: list[dict]):
    """One chat turn whose first assistant message carries an arbitrary tool_calls."""
    bodies: list[dict] = []
    state = {"turn": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8") or "{}")
        bodies.append(body)
        if not body.get("stream"):
            return httpx.Response(200, json={"message": {"role": "assistant", "content": "terse."}})
        state["turn"] += 1
        if state["turn"] == 1:
            return httpx.Response(200, content=_ndjson({
                "message": {"role": "assistant", "content": "", "tool_calls": tool_calls},
                "done": True,
            }))
        return httpx.Response(200, content=_ndjson({
            "message": {"role": "assistant", "content": "Done."}, "done": True}))

    real = muse_mod._client
    monkeypatch.setattr(muse_mod, "_client",
                        httpx.AsyncClient(transport=httpx.MockTransport(_handler),
                                          timeout=real.timeout))
    with TestClient(app) as c:
        with c.stream("POST", "/api/muse/chat", json={
            "messages": [{"role": "user", "content": "fix the chapter"}],
            "chapter_id": f"{SID}/{BID}/{_chapter_id()}",
        }) as r:
            assert r.status_code == 200
            sse = "".join(r.iter_text())
    events = []
    for line in sse.split("\n"):
        if line.startswith("data: [STATUS]"):
            events.append(("status", line[14:].strip()))
        elif line.startswith("data: [PROPOSAL]"):
            events.append(("proposal", line[16:].strip()))
    return sse, events, bodies


def test_the_agent_turn_has_room_to_write_a_whole_chapter(monkeypatch: pytest.MonkeyPatch):
    """The bug: 4096 output tokens cannot hold a 5,000-word chapter, so the tool
    arguments were truncated mid-JSON and looked empty. The chat carries its own,
    much larger ceiling now."""
    _, _, bodies = _chat(monkeypatch, NEW_TEXT)
    streamed = _streamed(bodies)[0]
    used = streamed["options"]["num_predict"]
    assert used == muse_mod.MUSE_AGENT_MAX_TOKENS
    assert used >= 16000, f"a whole chapter needs room: {used}"
    assert used > muse_mod.MUSE_NUM_PREDICT      # other paths keep the small cap


def test_truncated_arguments_are_named_rather_than_looking_empty(monkeypatch: pytest.MonkeyPatch):
    """A tool call cut off mid-JSON must tell the model WHY, or it retries the same
    doomed call — which is exactly what it did, five times, live."""
    truncated = '{"content": "# The New Chapter\\n\\nThe ember had guttered, and Kael'
    before = len(_mine())                     # earlier tests park their own
    sse, events, bodies = _chat_raw(monkeypatch, [
        {"function": {"name": "propose_chapter_rewrite", "arguments": truncated}}])
    assert "proposal" not in [k for k, _ in events]
    tool_msg = [m for m in _streamed(bodies)[-1]["messages"] if m["role"] == "tool"][-1]
    assert "invalid JSON" in tool_msg["content"] and "cut off" in tool_msg["content"]
    assert "PARTS" in tool_msg["content"]
    assert len(_mine()) == before, "a truncated call must not park anything"


def test_a_long_revision_can_arrive_in_parts(monkeypatch: pytest.MonkeyPatch):
    """Two calls in one turn append to the same revision, so a chapter too long for a
    single response can still be handed over whole."""
    part1 = "# The New Chapter\n\n" + ("The ember guttered in the ash. " * 12)
    part2 = ("Morning came grey over the harbour. " * 12)
    sse, events, bodies = _chat_raw(monkeypatch, [
        {"function": {"name": "propose_chapter_rewrite", "arguments": {"content": part1}}},
        {"function": {"name": "propose_chapter_rewrite", "arguments": {"content": part2}}},
    ])
    pids = [p for k, p in events if k == "proposal"]
    assert len(set(pids)) == 1, f"parts must share one revision, got {pids}"

    stored = muse_mod.read_proposal(pids[0])
    assert stored is not None
    assert "ember guttered" in stored["content"] and "grey over the harbour" in stored["content"]
    tool_msgs = [m["content"] for m in _streamed(bodies)[-1]["messages"] if m["role"] == "tool"]
    assert any("Part appended" in m for m in tool_msgs), tool_msgs


def test_proposals_die_with_the_book(monkeypatch: pytest.MonkeyPatch):
    """A pending revision about a chapter in the trash is a banner nobody can act on."""
    pid = _make_proposal(monkeypatch)
    assert any(p["id"] == pid for p in _mine())

    r = client.delete(f"/api/books/{SID}/{BID}")
    assert r.status_code == 200
    assert muse_mod.read_proposal(pid) is None

    # put the book back for whatever runs next, and clear the trash properly
    client.post(f"/api/trash/{r.json()['entry']}/restore")

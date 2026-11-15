"""The Muse as an IDE (3.1, D54–D60).

What this net has to hold:

1. **Any story file, still never saved.** `edit_file` stages changes to chapters
   *and* bible files (even a brand-new bible file); the file on disk is untouched
   until the author accepts, and a bible accept writes + reindexes like the PUT.
2. **One live draft per file, and it stacks.** A later turn's edits land on the
   pending draft instead of starting a rival one, and `read_story_file` shows the
   Muse its own draft so its `old_text` can match.
3. **A draft survives the author typing.** An edit-built draft that went stale is
   replayed onto the new text; edits that no longer apply are dropped and named,
   edits the author already made are recognised as done. A full rewrite still
   can't be replayed and is refused (D49).
4. **One turn, many files.** A multi-file change is announced file by file, each
   with the same batch id.
5. **The author's rules ride on every call; `@` attaches files.**
6. **The sweep stages, and never stages an apology.**
7. **Usage is reported in every dialect; ghost text is a sentence.**
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

_TMP = tempfile.mkdtemp(prefix="katha-ide-test-")
os.environ["KATHA_ARCHIVE"] = str(Path(_TMP) / "archive")
os.environ["KATHA_DATA"] = str(Path(_TMP) / "data")

from app import archive as ar  # noqa: E402
from app import muse as muse_mod  # noqa: E402
from app import upstream as up  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

SERIES = "IDE Shelf"
BOOK = "Edit Book"
SID = ar.slugify(SERIES)
BID = ar.slugify(BOOK)

BODY = "\n\n".join([
    "Mira counted the coins she owed and said nothing.",
    "The harbour lay grey under a low sky.",
    "Somewhere a bell rang twice and then fell silent.",
    "She walked on, and the mist took the rest.",
])


@pytest.fixture(scope="module", autouse=True)
def _book():
    r = client.post("/api/books", json={"series": SERIES, "title": BOOK})
    assert r.status_code == 201
    yield


@pytest.fixture(autouse=True)
def _ollama(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(up, "MUSE_API", up.OLLAMA)
    monkeypatch.setattr(up, "MUSE_API_BASE", "")
    monkeypatch.setattr(up, "MUSE_API_KEY", "")
    yield


def _bdir() -> Path:
    return ar.book_dir(SERIES, BOOK)


def _chapter(title: str, body: str = BODY) -> tuple[str, Path]:
    r = client.post(f"/api/books/{SID}/{BID}/chapters", json={"title": title, "content": body})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    path = ar.get_chapter(_bdir(), cid)
    assert path is not None
    return cid, path


def _ctx(cid: str):
    ctx = muse_mod._tool_ctx(f"{SID}/{BID}/{cid}")
    assert ctx is not None
    return ctx


def _bible(name: str, text: str) -> Path:
    r = client.put(f"/api/books/{SID}/{BID}/bible/{name}", json={"content": text})
    assert r.status_code == 200
    return _bdir() / "bible" / name


def _edit(ctx, turn, path, *pairs):
    return muse_mod._run_tool(ctx, "edit_file", {
        "path": path,
        "edits": [{"old_text": o, "new_text": n} for o, n in pairs]}, turn)


def _ndjson(*chunks: dict) -> bytes:
    return "\n".join(json.dumps(c) for c in chunks).encode("utf-8") + b"\n"


def _mock(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real = muse_mod._client
    monkeypatch.setattr(muse_mod, "_client",
                        httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                          timeout=real.timeout))


def _scripted(monkeypatch: pytest.MonkeyPatch, rounds: list[dict], bodies: list[dict]):
    """A chat upstream that plays `rounds` (Ollama message dicts) in order."""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8") or "{}")
        bodies.append(body)
        if not body.get("stream"):
            return httpx.Response(200, json={"message": {"content": "terse."}})
        i = min(state["n"], len(rounds) - 1)
        state["n"] += 1
        return httpx.Response(200, content=_ndjson({"message": rounds[i], "done": True}))

    _mock(monkeypatch, handler)


def _chat(cid: str, text: str, chip: str | None = None) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    with TestClient(app) as c:
        with c.stream("POST", "/api/muse/chat", json={
            "messages": [{"role": "user", "content": text}],
            "chapter_id": f"{SID}/{BID}/{cid}", "chip": chip,
        }) as r:
            assert r.status_code == 200
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                for tag in ("[STATUS]", "[PROPOSAL]", "[USAGE]", "[ERROR]"):
                    if payload.startswith(tag):
                        events.append((tag.strip("[]").lower(), payload[len(tag):].strip()))
                        break
                else:
                    events.append(("text", payload))
    return events


# --- 1. any story file, still never saved ----------------------------------

def test_the_muse_can_stage_a_bible_edit_and_accepting_writes_and_reindexes():
    cid, _ = _chapter("Bible Edit")
    f = _bible("places.md", "# Places\n\n## The Harbour\n- Grey stone, a single bell.\n")
    before = f.read_text(encoding="utf-8")
    turn: dict = {}
    msg = _edit(_ctx(cid), turn, "bible/places.md", ("a single bell", "two bells, one cracked"))
    assert "NOT saved" in msg
    assert f.read_text(encoding="utf-8") == before, "the bible was written!"

    pid = turn["proposal_id"]
    detail = client.get(f"/api/muse/proposals/{pid}").json()
    assert detail["kind"] == "bible" and detail["path"] == "bible/places.md"
    assert detail["base_content"] == before and len(detail["hunks"]) == 1

    r = client.post(f"/api/muse/proposals/{pid}/accept")
    assert r.status_code == 200, r.text
    assert "two bells, one cracked" in f.read_text(encoding="utf-8")
    hits = client.get("/api/search?q=cracked").json()["hits"]
    assert any(h["kind"] == "bible" and h["doc_id"] == "places.md" for h in hits)


def test_the_muse_can_create_a_new_bible_file_through_review():
    cid, _ = _chapter("Bible Create")
    dest = _bdir() / "bible" / "characters" / "oren.md"
    turn: dict = {}
    msg = _edit(_ctx(cid), turn, "bible/characters/oren.md",
                ("", "# Oren\n\n- The harbour bell-ringer.\n"))
    assert "(a new file)" in msg
    assert not dest.exists()
    r = client.post(f"/api/muse/proposals/{turn['proposal_id']}/accept")
    assert r.status_code == 200, r.text
    assert dest.read_text(encoding="utf-8") == "# Oren\n\n- The harbour bell-ringer.\n"


@pytest.mark.parametrize("path, needle", [
    ("chapters/ch-99.md", "not a chapter"),
    ("bible/../book.json", "not an editable bible file"),
    ("bible/.hidden.md", "not an editable bible file"),
    ("chapters/ch-01.notes.md", "only edit"),
    ("series/series.md", "only edit"),
    ("book.json", "only edit"),
])
def test_edit_file_only_reaches_chapters_and_bible(path, needle):
    cid, _ = _chapter("Edit Scope")
    turn: dict = {}
    msg = _edit(_ctx(cid), turn, path, ("x", "y"))
    assert msg.startswith("ERROR") and needle in msg, msg
    assert "proposal_id" not in turn


def test_a_bare_chapter_id_and_an_omitted_path_both_mean_a_chapter():
    cid, _ = _chapter("Bare Id")
    ctx, turn = _ctx(cid), {}
    _edit(ctx, turn, cid, ("rang twice", "rang once"))
    first = turn["proposal_id"]
    _edit(ctx, turn, None, ("rang once", "rang once, flat"))
    assert turn["proposal_id"] == first
    p = muse_mod.read_proposal(first)
    assert p["path"] == f"chapters/{cid}.md" and "rang once, flat" in p["content"]


# --- 2. one live draft per file, and it stacks -----------------------------

def test_a_later_turn_stacks_on_the_pending_draft():
    cid, path = _chapter("Stack Across Turns")
    ctx = _ctx(cid)
    t1: dict = {}
    _edit(ctx, t1, None, ("said nothing", "kept her silence"))
    t2: dict = {}           # a new turn: nothing staged in it yet
    msg = _edit(ctx, t2, None, ("grey under a low sky", "pewter under a sagging sky"))
    assert "staged" in msg
    assert t2["proposal_id"] == t1["proposal_id"], "a rival draft was started"
    content = muse_mod.read_proposal(t1["proposal_id"])["content"]
    assert "kept her silence" in content and "pewter under a sagging sky" in content
    mine = [p for p in muse_mod.list_proposals() if p["path"] == f"chapters/{cid}.md"]
    assert len(mine) == 1


def test_read_story_file_shows_the_muse_its_own_draft():
    cid, path = _chapter("Read Draft")
    ctx, turn = _ctx(cid), {}
    assert "said nothing" in muse_mod._run_tool(ctx, "read_story_file",
                                                {"path": f"chapters/{cid}.md"})
    _edit(ctx, turn, None, ("said nothing", "kept her silence"))
    seen = muse_mod._run_tool(ctx, "read_story_file", {"path": f"chapters/{cid}.md"})
    assert seen.startswith("[Your pending revision") and "kept her silence" in seen
    # …and so its next edit, copied from what it read, matches.
    msg = _edit(ctx, {}, None, ("kept her silence", "kept her silence, as ever"))
    assert "staged" in msg


# --- 3. a draft survives the author typing ---------------------------------

def _save(cid: str, body: str, title: str):
    r = client.put(f"/api/books/{SID}/{BID}/chapters/{cid}", json={"title": title, "content": body})
    assert r.status_code == 200


def test_an_edit_draft_is_replayed_after_the_author_saves_elsewhere():
    cid, path = _chapter("Replay")
    turn: dict = {}
    _edit(_ctx(cid), turn, None, ("said nothing", "kept her silence"))
    pid = turn["proposal_id"]
    # the author keeps writing, somewhere the Muse didn't touch
    _save(cid, BODY + "\n\nA line written later.", "Replay")

    detail = client.get(f"/api/muse/proposals/{pid}").json()
    assert detail["stale"] is False, "an edit draft should replay, not go stale"
    assert detail["dropped"] == []
    r = client.post(f"/api/muse/proposals/{pid}/accept")
    assert r.status_code == 200, r.text
    text = path.read_text(encoding="utf-8")
    assert "kept her silence" in text and "A line written later." in text


def test_an_edit_whose_text_the_author_changed_is_dropped_and_named():
    cid, path = _chapter("Replay Conflict")
    turn: dict = {}
    _edit(_ctx(cid), turn, None,
          ("said nothing", "kept her silence"),
          ("rang twice", "rang three times"))
    pid = turn["proposal_id"]
    # the author rewrote the bell line themselves
    _save(cid, BODY.replace("rang twice", "tolled once"), "Replay Conflict")

    detail = client.get(f"/api/muse/proposals/{pid}").json()
    assert not detail["stale"]
    assert [d["old_text"] for d in detail["dropped"]] == ["rang twice"]
    r = client.post(f"/api/muse/proposals/{pid}/accept")
    assert r.status_code == 200
    text = path.read_text(encoding="utf-8")
    assert "kept her silence" in text and "tolled once" in text and "three times" not in text


def test_an_edit_the_author_already_made_is_recognised_as_done():
    cid, path = _chapter("Replay Same")
    turn: dict = {}
    _edit(_ctx(cid), turn, None,
          ("said nothing", "kept her silence"),
          ("rang twice", "rang three times"))
    pid = turn["proposal_id"]
    _save(cid, BODY.replace("said nothing", "kept her silence"), "Replay Same")
    detail = client.get(f"/api/muse/proposals/{pid}").json()
    assert detail["dropped"] == [] and len(detail["hunks"]) == 1


def test_a_draft_with_nothing_left_after_replay_disappears():
    cid, _ = _chapter("Replay Empty")
    turn: dict = {}
    _edit(_ctx(cid), turn, None, ("said nothing", "kept her silence"))
    pid = turn["proposal_id"]
    _save(cid, BODY.replace("said nothing", "kept her silence"), "Replay Empty")
    assert client.get(f"/api/muse/proposals/{pid}").status_code == 404
    assert muse_mod.read_proposal(pid) is None


def test_a_partial_accept_then_more_typing_still_replays_the_rest():
    """Accepted hunks are satisfied on replay, not reported as conflicts."""
    cid, path = _chapter("Partial Then Type")
    turn: dict = {}
    _edit(_ctx(cid), turn, None,
          ("said nothing", "kept her silence"),
          ("the mist took the rest", "the fog closed behind her"))
    pid = turn["proposal_id"]
    assert client.post(f"/api/muse/proposals/{pid}/accept", json={"hunks": [0]}).status_code == 200
    body = ar._body_text(path.read_text(encoding="utf-8")).strip()
    _save(cid, body + "\n\nAnother line.", "Partial Then Type")
    detail = client.get(f"/api/muse/proposals/{pid}").json()
    assert detail["dropped"] == [] and not detail["stale"]
    assert len(detail["hunks"]) == 1 and "fog" in detail["hunks"][0]["after"]


def test_a_stale_bible_rewrite_is_refused_like_a_chapter():
    cid, _ = _chapter("Bible Stale")
    f = _bible("timeline.md", "# Timeline\n\n- The bell rings.\n")
    pid = muse_mod._park(_ctx(cid), "bible", "bible/timeline.md", f,
                         "# Timeline\n\n- The bell rings twice.\n", None, {})
    _bible("timeline.md", "# Timeline\n\n- The bell rings at dawn.\n")
    detail = client.get(f"/api/muse/proposals/{pid}").json()
    assert detail["stale"] is True
    r = client.post(f"/api/muse/proposals/{pid}/accept")
    assert r.status_code == 409 and "bible/timeline.md" in r.json()["detail"]
    assert "at dawn" in f.read_text(encoding="utf-8")


# --- 4. one turn, many files -----------------------------------------------

def test_a_multi_file_turn_announces_each_file_with_one_batch(monkeypatch):
    cid, _ = _chapter("Rename Everywhere")
    _bible("characters/mira.md", "# Mira\n\n- Owes coins to the harbour-master.\n")
    bodies: list[dict] = []
    _scripted(monkeypatch, [
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "edit_file", "arguments": {
                "path": f"chapters/{cid}.md",
                "edits": [{"old_text": "Mira counted", "new_text": "Mirel counted"}]}}},
            {"function": {"name": "edit_file", "arguments": {
                "path": "bible/characters/mira.md",
                "edits": [{"old_text": "# Mira", "new_text": "# Mirel"}]}}},
        ]},
        {"role": "assistant", "content": "Renamed in two files — review them."},
    ], bodies)
    events = _chat(cid, "rename Mira to Mirel everywhere")
    pids = [v for k, v in events if k == "proposal"]
    assert len(pids) == 2
    metas = [muse_mod.read_proposal(p) for p in pids]
    assert {m["path"] for m in metas} == {f"chapters/{cid}.md", "bible/characters/mira.md"}
    assert len({m["batch"] for m in metas}) == 1 and metas[0]["batch"]
    statuses = [v for k, v in events if k == "status"]
    assert any("bible/characters/mira.md" in s for s in statuses)


# --- 5. rules + @-mentions -------------------------------------------------

def test_scaffold_creates_a_rules_file_that_sends_nothing_until_written():
    r = client.post(f"/api/books/{SID}/{BID}/bible/scaffold")
    assert "rules.md" in r.json()["files"]
    assert muse_mod.load_rules(_bdir()) == "", "the template is not a rule"


def test_the_authors_rules_reach_chat_rewrite_and_sweep(monkeypatch):
    cid, _ = _chapter("Rules")
    _bible("rules.md", "# Rules\n\n<!-- a comment -->\n\n- British spelling.\n- No em-dashes.\n")
    assert muse_mod.load_rules(_bdir()) == "- British spelling.\n- No em-dashes."
    bodies: list[dict] = []
    _scripted(monkeypatch, [{"role": "assistant", "content": "ok"}], bodies)

    _chat(cid, "hello")
    with TestClient(app) as c:
        with c.stream("POST", "/api/muse/rewrite", json={
                "text": "a line", "chapter_id": f"{SID}/{BID}/{cid}"}) as r:
            list(r.iter_lines())
        with c.stream("POST", "/api/muse/sweep", json={
                "series": SID, "book_id": BID, "target": "report"}) as r:
            list(r.iter_lines())

    streamed = [b for b in bodies if b.get("stream")]
    assert len(streamed) == 3
    for b in streamed:
        system = " ".join(m["content"] for m in b["messages"] if m["role"] == "system")
        assert "British spelling" in system and "a comment" not in system
    _bible("rules.md", "# Rules\n\n- \n")


def test_at_mentions_resolve_to_story_files():
    cid, _ = _chapter("Mentions")
    _bible("characters/kael.md", "# Kael\n")
    ctx = _ctx(cid)
    got = muse_mod.resolve_mentions(
        ctx, f"compare @{cid} with @kael and @places, (also @characters/kael.) @nobody")
    assert got == [f"chapters/{cid}.md", "bible/characters/kael.md", "bible/places.md"]
    assert muse_mod.resolve_mentions(ctx, "email me at a@b.com") == []
    n = int(cid.split("-")[1])
    assert muse_mod.resolve_mentions(ctx, f"@ch{n}") == [f"chapters/{cid}.md"]


def test_mentioned_files_are_attached_to_the_turn(monkeypatch):
    cid, _ = _chapter("Mention Attach")
    _bible("characters/kael.md", "# Kael\n\n- Grey eyes, a debt he will not name.\n")
    bodies: list[dict] = []
    _scripted(monkeypatch, [{"role": "assistant", "content": "ok"}], bodies)
    events = _chat(cid, "is @kael consistent here?")
    assert ("status", "attached kael.md") in events
    system = " ".join(m["content"] for m in [b for b in bodies if b.get("stream")][0]["messages"]
                      if m["role"] == "system")
    assert "a debt he will not name" in system


# --- 6. the sweep stages, and never stages an apology ----------------------

def test_the_sweep_report_asks_for_located_issues():
    p = muse_mod.SWEEP_REPORT_PROMPT
    assert "[ch-03]" in p and "[bible/timeline.md]" in p and "[general]" in p


def test_an_empty_model_reply_is_never_staged_as_a_bible_file(monkeypatch):
    """The adapter's "the model wrote nothing" sentence is for the author's eyes."""
    monkeypatch.setattr(up, "MUSE_API", up.MESSAGES)
    monkeypatch.setattr(up, "MUSE_API_BASE", "https://api.example.test/v1")
    monkeypatch.setattr(up, "MUSE_API_KEY", "k")
    _bible("places.md", "# Places\n")
    sse = (b'data: {"type":"message_start","message":{"usage":{"input_tokens":9}}}\n\n'
           b'data: {"type":"message_delta","delta":{"stop_reason":"max_tokens"},'
           b'"usage":{"output_tokens":4096}}\n\n')
    _mock(monkeypatch, lambda req: httpx.Response(200, content=sse))
    before = {p["id"] for p in muse_mod.list_proposals()}
    with TestClient(app) as c:
        with c.stream("POST", "/api/muse/sweep", json={
                "series": SID, "book_id": BID, "target": "bible",
                "bible_name": "places.md"}) as r:
            lines = list(r.iter_lines())
    assert not any("[PROPOSAL]" in ln for ln in lines)
    assert any("output budget" in ln for ln in lines)
    assert {p["id"] for p in muse_mod.list_proposals()} == before


# --- 7. usage + ghost text -------------------------------------------------

def _drain(gen) -> list[dict]:
    async def run():
        return [e async for e in gen]
    return asyncio.run(run())


def test_usage_is_reported_by_all_three_dialects(monkeypatch):
    payload = {"model": "m", "messages": [{"role": "user", "content": "hi"}],
               "options": {"num_predict": 10}}

    def run(body: bytes) -> dict:
        c = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: httpx.Response(200, content=body)))
        events = _drain(up.stream_events(payload, c))
        return next(e["usage"] for e in events if e.get("usage"))

    assert run(_ndjson({"message": {"content": "a"}, "done": False},
                       {"message": {"content": ""}, "done": True,
                        "prompt_eval_count": 12, "eval_count": 3})) == {"input": 12, "output": 3}

    monkeypatch.setattr(up, "MUSE_API", up.OPENAI)
    monkeypatch.setattr(up, "MUSE_API_BASE", "https://api.example.test/v1")
    body = (b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
            b'data: {"choices":[],"usage":{"prompt_tokens":20,"completion_tokens":5}}\n\n'
            b'data: [DONE]\n\n')
    assert run(body) == {"input": 20, "output": 5}

    monkeypatch.setattr(up, "MUSE_API", up.MESSAGES)
    body = (b'data: {"type":"message_start","message":{"usage":{"input_tokens":30,"output_tokens":1}}}\n\n'
            b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"a"}}\n\n'
            b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":7}}\n\n')
    assert run(body) == {"input": 30, "output": 7}


def test_chat_sums_usage_over_rounds_and_reports_it_once(monkeypatch):
    cid, _ = _chapter("Usage Rounds")
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8") or "{}")
        if not body.get("stream"):
            return httpx.Response(200, json={"message": {"content": "terse."}})
        state["n"] += 1
        msg = ({"role": "assistant", "content": "", "tool_calls": [
                   {"function": {"name": "list_story_files", "arguments": {}}}]}
               if state["n"] == 1 else {"role": "assistant", "content": "done"})
        return httpx.Response(200, content=_ndjson(
            {"message": msg, "done": True, "prompt_eval_count": 100, "eval_count": 10}))

    _mock(monkeypatch, handler)
    usage = [json.loads(v) for k, v in _chat(cid, "list the files") if k == "usage"]
    assert usage == [{"input": 200, "output": 20}]


def test_ghost_text_is_one_sentence_glued_to_the_cursor(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body["stream"] is False
        assert body["messages"][-1]["content"].rstrip().endswith("walked on")
        return httpx.Response(200, json={"message": {
            "content": "<think>hmm</think>into the fog.\nAnd a second line."}})

    _mock(monkeypatch, handler)
    r = client.post("/api/muse/complete", json={"before": "She walked on"})
    assert r.json() == {"text": " into the fog."}
    r = client.post("/api/muse/complete", json={"before": "She walked on "})
    assert r.json()["text"] == "into the fog."


def test_ghost_text_fails_quietly(monkeypatch):
    _mock(monkeypatch, lambda req: httpx.Response(500, json={"error": "boom"}))
    r = client.post("/api/muse/complete", json={"before": "She walked on"})
    assert r.status_code == 200 and r.json() == {"text": ""}

# Katha — Status

**Phase 1.0** — the IDE is complete and shipping as an installable PWA, with
reading mode, writing rituals, and EPUB delivery. The client is served from the
same FastAPI server as the API.

## Done
- **0.1 Shell** — three panes, Hermes tokens, Cmd+K.
- **0.2 Archive** — FastAPI + SQLite index over a Markdown archive; chapters
  CRUD, autosave → revision, FTS5 search.
- **0.3 Muse** — streaming chat + rewrite (SSE), quick chips, apply-to-page,
  rewrite-with-diff, canon context, style digest, thread persistence.
- **0.3.8** — CORS allowlist, path-traversal guards, composite-key index
  migration, SSE escape fix, async canon loaders, editable chapter titles.
- **0.4** — focus mode; canon sweep (continuity report + approval-gated bible
  diffs); Electron replaced by a PWA (manifest, shell-only service worker,
  icons), served same-origin from the Pi.
- **1.0** — reading mode with margin-note annotations (`ch-NN.notes.md`
  sidecars); writing rituals (daily goal, streak, 14-day history); EPUB export
  (stdlib); optional proactive nudge.
- **1.1** — agentic Muse chat: the model fetches story files on demand via tools
  (`list_story_files` / `read_story_file` / `search_story`), scoped to the book +
  series root and never `.katha/`; progress shown via `[STATUS]` SSE events.
  Rewrite stays contextual (deepseek-r1 has no tools).
- **1.2** — the bible is a recursive tree (`bible/characters/kael.md`); a legacy
  flat `characters.md` is auto-split per `##` heading on boot (original kept as
  `.orig`). Bible overlay renders the tree; nested PUT paths.

## Next
- **2.0** — the PWA as the universal client (desktop + mobile). No Flutter.

## Verify
- Server: `cd server && .venv\Scripts\python.exe -m pytest -q` (40 tests).
- Client: `cd desktop && npm run build`.
- Install: build, serve via the Pi, open over `tailscale serve` HTTPS, Install app.

## Open
- Ollama (the Muse upstream) must be reachable on the LAN for Muse + sweep.
- Whole-book continuous reading mode and offline support are out of scope.

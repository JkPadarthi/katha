# Katha — Status

**Phase 0.4** — the IDE is complete and shipping as an installable PWA; the
client is served from the same FastAPI server as the API.

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

## Next
- **1.0** — reading mode + annotations; writing rituals (goals/streaks);
  EPUB export; optional nudge toggle.

## Verify
- Server: `cd server && .venv\Scripts\python.exe -m pytest -q` (33 tests).
- Client: `cd desktop && npm run build`.
- Install: build, serve via the Pi, open over `tailscale serve` HTTPS, Install app.

## Open
- Ollama (the Muse upstream) must be reachable on the LAN for Muse + sweep.
- Whole-book continuous reading mode and offline support are out of scope.

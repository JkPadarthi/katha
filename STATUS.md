# Katha — Status

**Phase 2.1** — the IDE is complete and shipping as an installable PWA, with
reading mode, writing rituals, and EPUB delivery. The client is served from the
same FastAPI server as the API. The Muse is no longer tied to one brain: it can
talk to the LAN Ollama box **or** any OpenAI-compatible gateway.

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
- **1.3** — mobile layout: below 768px, one pane at a time with bottom tabs
  (Chapters / Page / Muse) and swipe between panes. The PWA is now usable on a
  phone, not just installable.
- **2.0** — client rebuilt from scratch on a token-theme system: **Hermes /
  Paper / Slate**, default follows the OS then remembers your pick. Shared `ui/`
  primitives; the rail's "+ New chapter" is now wired. Dead files removed.
- **2.0.1 hardening** — edit-only autosave (opening a chapter no longer writes
  a revision; a failed load can never blank a file); nested bible paths work in
  the canon sweep; SPA static serving is contained to `dist/`; Muse threads are
  restored when a chapter opens (and no longer re-append the whole history);
  the rail switches between series/books and can create one; chapters past 99
  are supported and sorted numerically; revision numbers survive deleted
  snapshots; canon lookups use OR'd FTS terms scoped to the book; a fresh
  checkout boots without an `archive/` directory. The bible has a canonical
  shape (one file per main character, a shared side-characters file, places,
  timeline) scaffolded on book creation and backfillable from the panel.
- **2.1** — the Muse gets a second upstream dialect. `app/upstream.py` is the
  only place that knows a provider's wire format: internally the Muse still
  speaks the Ollama shape (so think-stripping, the agentic tool loop, canon
  context and the style digest are untouched), while `KATHA_MUSE_API=openai`
  routes it at any OpenAI-compatible `/chat/completions` gateway — bearer key,
  `options`→`max_tokens`, SSE deltas, and tool-call fragments reassembled with
  ids so the agentic loop works on both. Mode-aware model defaults; switching
  brains is three env vars, and `=ollama` switches back (the LAN settings are
  untouched). Also: a short **connect** timeout, so a dead upstream surfaces as
  a real `[ERROR]` in the Muse instead of freezing it for 300s — that freeze was
  the first thing the dormant jenga box exposed.

## Next
- Dogfood the full loop (write → autosave/revisions → Muse tools → rewrite diff
  → sweep → reading + notes → EPUB); browser-verify the three themes + mobile.
- Then: a revision-history browser (list / preview / restore).
- Later: a settings affordance for the Muse dialect (today it's env-only).

## Verify
- Server: `cd server && .venv/bin/python -m pytest -q` (70 tests).
- Client: `cd desktop && npm run build`.
- Install: build, serve via the Pi, open over `tailscale serve` HTTPS, Install app.

## Open
- The Muse upstream must be reachable: the LAN Ollama box (`KATHA_MUSE_API=ollama`,
  default) or a cloud gateway with a key (`KATHA_MUSE_API=openai`). With neither,
  everything except the Muse still works — writing, revisions, search, bible,
  reading mode, EPUB.
- Whole-book continuous reading mode and offline support are out of scope.

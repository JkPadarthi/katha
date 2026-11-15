# Katha — Project

Architecture, components, and the API contract.

## Shape

```
Pi 5 (Docker Compose)                         Browser / installed PWA
┌───────────────────────────────┐             ┌────────────────────────┐
│ FastAPI (uvicorn :4901)       │  same origin│ React SPA (Vite)       │
│  ├ /            → built PWA   │◄───────────►│  Rail · Page · Muse     │
│  ├ /api/...     → JSON API    │   /api      │  + CommandPalette,      │
│  ├ /api/muse/*  → SSE stream  │             │    DiffOverlay, Sweep   │
│  └ archive/     → md (truth)  │             └────────────────────────┘
│      series/book/chapters/*.md│   Tailscale serve → HTTPS origin
│      series/book/bible/*.md   │
│      .katha/muse/…            │   Ollama (LAN) ←─ Muse proxy
│  data/katha.db  → SQLite index│
└───────────────────────────────┘
```

## Components

- **Client** (`desktop/src/`) — React + Vite + Tailwind, no router, state in
  `App.jsx`. `lib/api.js` is the entire backend boundary (same-origin `/api` +
  SSE streaming); `lib/useTheme.js` drives the theme system (Hermes/Paper/Slate,
  OS-follow default); `lib/settings.js` holds per-machine prefs; `lib/resume.js`
  picks the landing chapter. `ui/` holds the shared primitives (`Overlay`,
  `Button`, `Field`). Components: `TitleBar`, `ThemePicker`, `Rail`, `Editor`
  (autosave, ghost text), `ReadingView`, `Muse` (chat, @-mentions, pending changes,
  token meter), `ProposalReview` (per-hunk review, inline or modal, multi-file),
  `HistoryPanel`, `SecurityPanel` (provider, key, password), `CommandPalette`, `DiffOverlay`, `SweepPanel` (located issues +
  Fix), `BiblePanel`, `RitualsCard`, `SettingsPanel`, `NewBookDialog`,
  `BookDetailsDialog`, `ConfirmDeleteDialog`. `public/sw.js` caches the shell only.
- **Server** (`server/app/`) — `main.py` (HTTP + SSE + static PWA + the lock),
  `schemas.py` (contracts), `archive.py` (files = truth), `db.py` (SQLite index
  + FTS5), `muse.py` (the Muse: agentic chat with story tools, staged edits,
  rewrite, ghost text, canon sweep), `upstream.py` (the three wire dialects),
  `hunks.py` (word-level hunks + partial merge), `prose.py` (paragraph rule),
  `epub.py`, `stats.py`, `trash.py`, `auth.py`, `settings_store.py` (settings
  changed in the app), `config.py`.
  `seed.py` bootstraps sample data; `tests/` cover all of it.

## The Muse as an IDE (3.1)

The Muse reads the story with tools (`list_story_files`, `read_story_file`,
`search_story`) and changes it with `edit_file` (targeted find/replace on a chapter
or bible file) or `propose_chapter_rewrite` (the whole open chapter). It **cannot
save**: every change is a *proposal* in `.katha/proposals/`, one live draft per
file. The author reviews it hunk by hunk; accepting runs the same save path as an
edit they made. Edit-built drafts replay onto the file if the author types in the
meantime (D58). Context on every call: the file index, the style digest, the
author's `bible/rules.md`, and any `@`-mentioned files.

## Storage (source of truth)

```
<archive>/
  <series>/series.json
    <book>/book.json
      chapters/ch-01.md          # "# Title\n\n<body>"
      chapters/ch-01.1.md        # revision snapshot (D9)
      chapters/ch-01.notes.md    # reading-mode annotations (1.0)
      bible/characters/kael.md   # one file per main character (1.2 tree)
      bible/characters/side-characters.md  # NPCs / supporting cast
      bible/places.md            # loose files still allowed
      bible/timeline.md
      bible/rules.md             # the author's rules for the Muse (3.1)
  .katha/muse/<book>-<chapter>.md  # Muse threads (book-scoped, 2.4)
  .katha/muse/style-<book>.md    # style digest
  .katha/proposals/<id>.json     # staged Muse changes awaiting review (2.9 → 3.1)
  .katha/trash/                  # deleted things, restorable (2.3)
  .katha/stats/writing.jsonl     # writing-ritual log (1.0)
```

`KATHA_DATA/settings.json` (0600, beside the index, not in backups) holds what the
author changed in Settings → Muse & security: the Muse's connection and the password
(as a salted scrypt hash). It wins over the environment when present (D62).

SQLite (`data/katha.db`) indexes chapters, revision metadata, and an FTS5
`search_index` — rebuildable from the md at any time.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | status + version + db heartbeat (public) |
| POST | `/api/auth/login` · `/api/auth/logout` | the lock (D32) |
| GET | `/api/settings` | Muse connection (key never returned) + lock state |
| PUT | `/api/settings/muse` | provider, address, key, models (current password) |
| POST | `/api/settings/muse/reset` · `/api/settings/muse/test` | back to env · test the connection |
| PUT | `/api/settings/password` | set / change / turn off the lock (current password) |
| GET / POST | `/api/books` | series → books tree / create series + book |
| PUT | `/api/books/{series}/{book}/meta` | author (per book) |
| GET / PUT / DELETE | `/api/books/{series}/{book}/cover` | cover image (normalised) |
| GET / POST | `…/{book}/chapters` | list / create chapter |
| GET / PUT | `…/chapters/{id}` | read / save (+ revision snapshot) |
| GET | `…/chapters/{id}/revisions[/{n}]` | revision history |
| GET / PUT | `…/chapters/{id}/notes` | reading-mode notes |
| GET / PUT | `…/{book}/bible[/{name:path}]` | read / write canon (nested paths ok) |
| POST | `…/{book}/bible/scaffold` | create the starter bible (idempotent) |
| GET | `/api/search?q=&limit=` | FTS5 across chapters + bible |
| POST | `/api/search/reindex` | rebuild the index from md |
| GET | `/api/stats` | writing rituals |
| GET | `…/{book}/export.epub` | EPUB download |
| GET | `/api/muse/models` | configured models |
| GET | `/api/muse/thread?chapter_id=` | persisted chat thread for a chapter |
| POST | `/api/muse/chat` | SSE chat — agentic; reads files and stages edits |
| POST | `/api/muse/rewrite` | SSE rewrite of a selection |
| POST | `/api/muse/complete` | ghost text: one-sentence continuation |
| POST | `/api/muse/sweep` | SSE canon sweep (`report` \| `bible` → proposal) |
| GET | `/api/muse/proposals[/{id}]` | staged changes (list / one, with hunks) |
| POST | `/api/muse/proposals/{id}/accept` | accept all or `{hunks: [...]}` |
| DELETE | `/api/muse/proposals/{id}` | discard |
| GET / DELETE | `…/impact` · chapter, book, bible file, series | what a delete would take / move to trash |
| GET / DELETE | `/api/trash[/{entry}]` | list / erase for good |
| POST | `/api/trash/{entry}/restore` | put it back |

SSE contract: each event is `data: <escaped chunk>\n\n`, terminated by
`data: [DONE]\n\n`. Side channels, never prose: `data: [STATUS] <msg>` (progress),
`data: [PROPOSAL] <id>` (a change was staged), `data: [USAGE] {"input","output"}`
(tokens), and `data: [ERROR] <msg>` (upstream failure). Escaping is single-pass
(`\n` → literal, `\` → `\\`) and mirrored exactly on the client.

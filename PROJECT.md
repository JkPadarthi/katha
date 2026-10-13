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

- **Client** (`desktop/`) — React + Vite + Tailwind, no router, state in
  `App.jsx`. `src/api.js` is the entire backend boundary (same-origin `/api` +
  SSE streaming). `src/settings.js` holds per-machine prefs in `localStorage`.
  Components: `TitleBar`, `Rail`, `Page`, `Muse`, `CommandPalette`,
  `DiffOverlay`, `Sweep`. `public/sw.js` caches the shell only.
- **Server** (`server/app/`) — `main.py` (HTTP + SSE + static PWA),
  `schemas.py` (contracts), `archive.py` (files = truth), `db.py` (SQLite index
  + FTS5), `muse.py` (Ollama proxy: agentic chat with story tools, rewrite,
  canon sweep), `config.py`.
  `seed.py` bootstraps sample data; `tests/` cover archive + Muse + sweep.

## Storage (source of truth)

```
<archive>/
  <series>/series.json
    <book>/book.json
      chapters/ch-01.md          # "# Title\n\n<body>"
      chapters/ch-01.1.md        # revision snapshot (D9)
      chapters/ch-01.notes.md    # reading-mode annotations (1.0)
      bible/characters.md
      bible/places.md
  .katha/muse/<chapter>.md       # Muse threads
  .katha/muse/style-<book>.md    # style digest
  .katha/stats/writing.jsonl     # writing-ritual log (1.0)
```

SQLite (`data/katha.db`) indexes chapters, revision metadata, and an FTS5
`search_index` — rebuildable from the md at any time.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | status + version + db heartbeat |
| GET | `/api/books` | series → books tree |
| POST | `/api/books` | create series + book |
| GET | `/api/books/{series}/{book}/chapters` | list chapters |
| POST | `/api/books/{series}/{book}/chapters` | create chapter |
| GET/PUT | `/api/books/{series}/{book}/chapters/{id}` | read / autosave (+revision) |
| GET | `…/chapters/{id}/revisions[/{n}]` | revision history |
| GET/PUT | `/api/books/{series}/{book}/bible[/{name}]` | read / write canon |
| GET | `/api/search?q=&limit=` | FTS5 across chapters + bible |
| POST | `/api/search/reindex` | rebuild the index from md |
| GET | `/api/muse/models` | configured models |
| POST | `/api/muse/chat` | SSE chat — agentic; the model fetches story files via tools |
| POST | `/api/muse/rewrite` | SSE rewrite proposal |
| POST | `/api/muse/sweep` | SSE canon sweep (`report` \| `bible`) |
| GET | `/api/stats` | writing rituals (1.0) |
| GET | `/api/books/{series}/{book}/export.epub` | EPUB download (1.0) |

SSE contract: each event is `data: <escaped chunk>\n\n`, terminated by
`data: [DONE]\n\n`. A progress event is `data: [STATUS] <msg>\n\n` (never prose);
an upstream failure emits `data: [ERROR] <msg>\n\n`. Escaping is single-pass
(`\n` → literal, `\` → `\\`) and mirrored exactly on the client.

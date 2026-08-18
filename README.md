# Katha (कथा)

A self-hosted story-writing IDE. Three panes — chapters, the page, the Muse — with an AI companion that reads your story's folder, rewrites your drafts into proper novel English, and writes in your characters' voices.

Built to be *yours*: no SaaS, no stores, everything served from a Raspberry Pi 5 in a Docker Compose stack. Desktop client on Windows (Electron), native mobile app later (PWA rejected by design).

**Status:** Phase 0.0 — design, then scaffold. See STATUS.md.

## Stack

| Layer | Choice |
|---|---|
| Desktop client | Electron + React + Vite + Tailwind (Windows) |
| Backend | FastAPI + SQLite (index only) + Markdown archive on disk |
| AI routing | LiteLLM signpost → friend's 5060 (Ollama) / OpenRouter-free |
| Host | Pi 5, Docker Compose, Tailscale |
| Storage truth | `series/book/chapters/*.md` + `bible/` — portable, git-able |

## Quick start (soon)

```bash
# server on the Pi
cd server && docker compose up -d

# desktop on Windows
cd desktop && npm install && npm run dev
```

## Docs

- DECISIONS.md — every settled call and why
- PROJECT.md — architecture, components, API contract
- STATUS.md — where the quest stands
- ROADMAP.md — phases 0.0 → 2.0
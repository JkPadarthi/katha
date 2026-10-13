# Katha (कथा)

A self-hosted story-writing IDE. Three panes — chapters, the page, the Muse — with an AI companion that reads your story's folder, rewrites your drafts into proper novel English, and writes in your characters' voices.

Built to be *yours*: no SaaS, no stores. One FastAPI server on a Raspberry Pi 5 serves **both** the API and an installable **PWA**; your Markdown archive never leaves the Pi.

**Status:** Phase 0.4 — see STATUS.md.

## Stack

| Layer | Choice |
|---|---|
| Client | Installable **PWA** (React + Vite + Tailwind) — desktop **and** mobile, one codebase |
| Backend | FastAPI + SQLite (index only) + Markdown archive on disk |
| AI routing | Direct Ollama on a trusted LAN box (over Tailscale); no API key |
| Host | Pi 5, Docker Compose, Tailscale + `tailscale serve` for HTTPS |
| Storage truth | `series/book/chapters/*.md` + `bible/` — portable, git-able |

## Quick start

```bash
# on the Pi — serves the API and the built PWA on one port
cd server
docker compose up -d

# HTTPS origin so the PWA is installable (service workers need a secure context)
tailscale serve --bg https / http://localhost:4901
```

Open the served URL and use **Install app** in the browser (works on desktop and phone).

### Dev

```bash
cd server && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 4901
cd desktop && npm install && npm run dev   # :5173, proxies /api → :4901
```

## Docs

- ROADMAP.md — phases 0.0 → 2.0
- DECISIONS.md — every settled call and why
- PROJECT.md — architecture, components, API contract
- STATUS.md — where the quest stands

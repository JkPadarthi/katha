# Katha — Roadmap

Phases 0.0 → 2.0. Single-user, self-hosted, no SaaS, by design.

## Phase 0.0 — the IDE

- **0.1 Shell** ✅ — three-pane layout, Hermes-token theme, Cmd+K skeleton.
- **0.2 Archive** ✅ — FastAPI + SQLite (index only) + md storage; chapters CRUD, autosave, revision history; FTS5 search.
- **0.3 Muse** ✅ — streaming chat, quick chips, apply-to-page, rewrite-with-diff + style presets, canon context + style digest + thread persistence.
- **0.3.8 hardening** ✅ — CORS allowlist, path-traversal guards, composite-key index migration, SSE escape fix, async canon loaders, editable titles.
- **0.4 Courier + polish** ✅ — focus mode, canon sweep (audit + approval-gated bible diffs), PWA packaging (client replaces the Electron desktop app; served from the Pi over Tailscale).
- **Exit criteria** — Jaswanth writes a story in Katha and the Muse genuinely helps.

## Phase 1.0 — Experience extras

- Reading mode — flip the page into book form; annotate (md sidecars). ✅
- Writing rituals — goals, streaks, quiet discipline (discipline > motivation). ✅
- Delivery — downloadable EPUB export. ✅
- Optional — proactive nudge toggle (D11). ✅

## Phase 2.0 — PWA everywhere (was: native mobile)

- **One installable PWA** for desktop **and** mobile — no Flutter, no separate mobile codebase. The 0.4 client work is the foundation.
- Companion use — write scenes on the bus, same archive, same Muse.
- Requires — an HTTPS origin reachable from the phone: Tailscale stays the boundary; `tailscale serve` provides the certificate. (See DECISIONS: the earlier "PWA rejected by design" call is overturned.)

## Later / never

- **Multi-user** — not a goal. Single user by design (D12).
- **SaaS / cloud sync** — never. The Pi is the city.

# Katha — Decisions

Every settled call and why. Newest first.

## 2026-10 — Client is an installable PWA (overturns the earlier "PWA rejected" call)
The client was an Electron desktop app. We are replacing it with a single
installable **PWA** for desktop *and* mobile. Why: one codebase instead of an
Electron app plus a future Flutter app; trivial installs; no stores. Cost:
losing the frameless custom window chrome and Chromium-version guarantees.
**This overturns** the roadmap's "native mobile app / PWA rejected by design"
and the standing taste preference for a real native app over a PWA.

## 2026-10 — Online-only; the API is same-origin
The PWA caches only the **app shell**; every byte of prose is fetched live from
`/api`. No offline editing, no sync — that would mean local storage + reconcile,
i.e. the cloud sync we ruled out. FastAPI serves the built client at `/` and the
API at `/api` on **one port**, so there is no base-URL configuration and no
cross-origin traffic. This retires the old `_resolveBase()` logic and the
hardcoded Tailscale fallback, and makes the earlier "in-app server address"
setting unnecessary.

## 2026-10 — HTTPS via `tailscale serve` (D12, extended)
A service worker only runs in a secure context. Plain `http://<ip>:4901` won't
install a PWA. `tailscale serve --bg https / http://localhost:4901` gives a valid
`https://<pi>.<tailnet>.ts.net/` origin. Tailscale remains the security boundary;
there is still **no app auth** (single user).

## 2026-10 — Canon sweep = audit + approval-gated bible diffs
"Canon sweep" (0.4) reads the whole manuscript and (a) streams a read-only
continuity report, and (b) can propose rewrites of individual bible files that
the author reviews in the same word-diff overlay as rewrites. Nothing is written
until Accept. Implemented as `POST /api/muse/sweep` (SSE) + `PUT .../bible/{name}`.

## 2026-10 — Annotations are md sidecars
Reading-mode annotations persist as `chapters/ch-NN.notes.md` — portable,
git-able, and already excluded from chapter listings by the `ch-\d{2}\.md`
fullmatch. Keeps the "md on disk is the truth" principle (the DB is only an
index, and must never hold data that can't be rebuilt).

## D19 — Muse context: style digest + thread persistence
The first time a book is touched, the Muse reads the last few chapters and
writes a style fingerprint (`archive/.katha/muse/style-<book>.md`). Every exchange
is appended to `archive/.katha/muse/<chapter>.md`. Best-effort — never breaks a
stream.

## D18 — Canon context
If a `chapter_id` (`series/book/ch-NN`) is supplied, the system prompt is
prefixed with the current chapter plus up to 4 FTS5-ranked bible hits, capped at
`MUSECONTEXT_MAX_TOKENS`.

## D16/D17 — Muse proxy
Chat and rewrite are proxied to a friend's Ollama box and streamed to the client
as SSE. `<think>…</think>` blocks (deepseek-r1) are stripped so the reader never
sees chain-of-thought. Chat uses a faster non-thinking model; rewrite keeps the
thinking model.

## D14 — Config is environment-driven
`KATHA_ARCHIVE`, `KATHA_DATA`, `KATHA_WEB_DIR`, `KATHA_CORS_ORIGINS`,
`OLLAMA_BASE`, `MUSE_*` — see `server/.env.example`.

## D13 — Health / version heartbeat
`GET /api/health` returns status, version, and `db_ok`.

## D12 — Single user, Tailscale, no auth
One author. Access is over a private Tailscale network. There is deliberately no
application authentication; Tailscale is the boundary. Multi-user is not a goal.

## D9 — Revision time machine
Every save writes a full-copy snapshot `ch-NN.<rev>.md` beside the chapter, with
a `.rev` counter. Snapshots are excluded from chapter listings and search.

## D6 / D5 — Markdown is the truth; SQLite is an index only
The archive (`series/book/chapters/*.md` + `bible/`) is the source of truth.
SQLite holds a rebuildable index (chapters, revisions meta) and an FTS5 search
index. On schema-version mismatch the derived tables are dropped and repopulated
from md — md is never touched.

## D7 — Quick chips
Pre-written prompts (rewrite / continue / new scene / canon?) that pre-fill the
Muse composer.

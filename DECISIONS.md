# Katha — Decisions

Every settled call and why. Newest first.

## 2026-11 — Hardening pass (2.0.1)
- **Autosave is edit-only.** The editor keeps a saved baseline (chapter key +
  body + title) and only PUTs when the buffer differs. Opening a chapter costs
  a GET, not a revision; a failed GET leaves the baseline invalidated so an
  empty buffer can never overwrite the file.
- **Sweep shares the bible write guard.** `sweep_bible` resolves names through
  `archive.safe_bible_path` (nested paths allowed, traversal/hidden/non-md
  rejected) instead of a flat-name regex — the 1.2 tree and 0.4 sweep now agree.
- **The bible has a canonical shape.** `characters/<name>.md` is one main
  character per file; `characters/side-characters.md` holds NPCs and the
  supporting cast; `places.md` and `timeline.md` are scaffolded alongside. New
  books get it at creation, `POST …/bible/scaffold` backfills old books
  idempotently (never overwrites edited canon), and the panel is reachable
  without an existing file (rail "Add bible" + ⌘K "Open bible").
- **The rail is the book picker.** Series/books are switched from the rail;
  "New book" calls `POST /api/books`. Command-palette hits carry their own
  series/book so a search result opens the right book.
- **Threads are readable.** `GET /api/muse/thread` parses `.katha/muse/*.md`
  and the client restores it on chapter open; persistence writes only the last
  exchange (the client already sends the full thread each turn).
- **Chapters are `ch-\d{2,}`.** 100+ chapters are valid and sorted numerically
  everywhere (rail, search, sweep, style digest, EPUB).
- **Static serving is contained.** The SPA fallback resolves under `WEB_DIR`
  and rejects anything outside, matching the archive's path guards.
- **Canon retrieval uses OR'd terms.** FTS5 ANDs bare terms, so a prose query
  never matched; `_fts_or_query` quotes + ORs distinctive tokens and scopes
  the search to the current book.

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

## 2026-10 — Client rebuilt on a token-theme system (2.0)
The presentation layer was rewritten from scratch (same React/Vite/Tailwind;
the FastAPI backend and the `api.js` contract are unchanged). Themes are now
first-class: semantic CSS variables defined once in Tailwind's `@theme` and
overridden per theme via `:root[data-theme="…"]`, so every component re-themes
for free. Three themes ship — **Hermes** (dark/gold), **Paper** (warm light),
**Slate** (cool dark) — and the default **follows the OS** (`prefers-color-
scheme`) until the user picks one, which is then remembered. Shared `ui/`
primitives (`Overlay`, `Button`, `Field`) replace the per-panel copies. The rail's
"+ New chapter" button is now wired (POST /chapters).

## 2026-10 — Mobile layout: one pane + bottom tabs + swipe
Below 768px the app switches from the three-column grid to one pane at a time,
with a bottom tab bar (Chapters / Page / Muse) and horizontal swipe between
panes (swipe is ignored when the gesture starts in a `textarea`/`input`/
`[contenteditable]`, so it never hijacks text selection). Tapping a chapter in
the rail jumps to the Page pane. This is the concrete "2.0 PWA everywhere"
deliverable — the same client now works on a phone. Desktop (≥768px) is
unchanged.

## 2026-10 — The bible is a tree; characters split per file
`bible/` is a recursive folder tree: `bible/characters/kael.md`,
`bible/characters/mira.md`, `bible/places/crosswater.md`, while loose
`bible/timeline.md` still works. Every bible walk (`read_bible`,
`iter_searchable_docs`, the Muse's `list_story_files` / sweep context, EPUB)
is recursive and skips hidden segments. `PUT .../bible/{name:path}` accepts
nested paths, guarded by `archive.safe_bible_path` (no `..`, absolute, hidden,
or non-.md). A one-time migration `split_characters_bible` splits a legacy flat
`bible/characters.md` by its `##` headings into `bible/characters/<slug>.md`,
renaming the original to `characters.md.orig` (never listed) so nothing is lost.

## 2026-10 — Muse chat is agentic (tools), rewrite stays contextual
Instead of pre-injecting the current chapter, the chat model is given **tools**
to fetch the story itself: `list_story_files`, `read_story_file`, `search_story`.
It is handed the file index + the style digest, not the chapter. Scope is the
current **book + series root**, `.md` only, never `.katha/` (Muse threads, style
digests, stats) or app files — the tool path resolver is the security boundary.
**Rewrite stays contextual** because the rewrite model (`deepseek-r1:14b`) has no
tool support; it still gets the current chapter + bible + style digest. The agent
model is a new `MUSE_AGENT_MODEL` (default `gemma4:12b`, which advertises tools).
Long-running fetches surface as a `[STATUS]` SSE event so the UI can show
"reading ch-03…".

## 2026-10 — Annotations are md sidecars
Reading-mode annotations persist as `chapters/ch-NN.notes.md` — portable,
git-able, and already excluded from chapter listings by the `ch-\d{2,}\.md`
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

## D37 — An empty archive is a state, not an error (2.4)
`GET /api/books` returning `[]` is a legitimate answer. The client used to set
`loadError = 'Server returned an empty archive.'`, which rendered as *"Failed to
load archive — server didn't respond"* — a lie about the server, and it buried the
thing the author actually needed (the trash). Now the tree is just fetched, and an
empty archive renders an empty panel that offers to create a book/series and says
where deleted things wait.

## D36 — Erasing is a separate, deliberate act (2.4)
`DELETE /api/trash/{entry}` and `DELETE /api/trash` (empty) are the **only** code
that destroys anything in Katha. Delete stays a move (D33); erasing is what you
ask for afterwards, per entry or wholesale, and the UI always routes it through a
red confirm that says the restore is gone for good. Nothing ages out on its own.

## D42 — The Muse's third dialect is named after the endpoint, not the vendor (2.7.0)
`KATHA_MUSE_API` now accepts `messages`: `POST {MUSE_API_BASE}/messages` with an
`x-api-key` and a version pin — the shape a gateway requires for Claude models.
Traffic still goes to `MUSE_API_BASE`; the dialect is a wire shape, never a vendor
address, so a commandcode/OpenRouter-style base is the normal case (the name is
`messages`, not `anthropic`, exactly so nobody reads it as "bypass the gateway";
`anthropic` is still accepted as an alias).

Two things forced it, both worth remembering:

* **A gateway can serve a model on one endpoint only, and it says so.** Read
  `supported_endpoints` per model in `GET /models` rather than guessing an alias:
  `claude-sonnet-5-5` is `['/messages']` while `deepseek/deepseek-v4-flash` is
  `['/chat/completions', '/responses']`. Calling a Claude model on
  `/chat/completions` answers `400 unsupported_model: … must be called via
  /provider/v1/messages`.
* **The Messages shape differs in ways a naive port gets wrong.** `system` is a
  top-level field, not a role; `max_tokens` is required and has no default; tools
  flatten to `{name, description, input_schema}`; and a tool result is a
  `tool_result` block inside a *user* turn paired by id — which forces
  consecutive same-role turns to be merged, because the roles must alternate.
  Streaming is `text_delta` + `input_json_delta` fragments, reassembled into the
  same complete internal call list the OpenAI path produces, so the agentic tool
  loop never learns which dialect it is on.

## D41 — The logo is generated, and its light is one gradient (2.6.0)
The mark is a near-black tile carrying a golden **क** (the first letter of कथा),
produced by `scripts/make-logo.py` (pillow + fonttools; `scripts/requirements-logo.txt`)
— generated, never hand-drawn in an editor, so it can be re-made at any size and the
vector cannot drift from the rasters. The glyph is **Noto Sans Devanagari SemiBold**
(SIL OFL, so baking the outline into the repo is safe); FreeSans/FreeSerif were
compared and Apple's Sangam/ITF look finer but are not redistributable.
Per-size tuning is empirical and matters: ink 62% normally, **48%** for maskable
(inside the 80% safe circle), 78%/86% for the 32/16px favicons with a heavier glyph
below 48px — a looped Devanagari glyph at 16px closes up otherwise. Rasters are
drawn at 4× and downsampled, because PIL's own hinting at 32px destroys the glyph.
The lighting is ONE ramp along `t = (x + y)`, which is exactly what an SVG
`linearGradient` from (0,0) to (1,1) is — that is why the vector and the rasters
agree: same maths, not two hand-tuned things. Stops run champagne → gold → amber
(0.52 *is* the app's `--color-accent`) with the specular band folded in as an extra
stop, plus a `feDropShadow` falling away from the light. Two choices came straight
from looking at the result: the highlight never reaches white (it reads silver) and
the turn-away end never goes brown (it reads tarnished).
`/logo.svg` is public **exactly**, not as a prefix, because the login card shows the
mark before anyone is signed in.

## D40 — Settings is the second front door; focus keeps a retractable rail (2.5.1)
The title bar hides `lock` and `focus` below `md` — so on a phone there was no way
to lock the archive at all, and the theme picker was a small popover nobody would
find. Both now live in **Settings** as well: a three-way theme choice (it writes the
same `theme` setting the picker does, so the two stay in sync) and `Lock now`
(`signOut`, the same call the title bar makes). Controls may be duplicated for
reach, never for state.
**Focus mode no longer throws the rail away.** A writer wants the map of the book
while writing, so focus keeps the chapter list and the rail's own toggle *retracts*
it to the 48px strip of chapter numbers; that choice persists like the focus flag
itself. The Muse column stays hidden in focus — that is what focus is for.

## D39 — Chapter 0 is the prologue, and it is opt-in (2.5)
`POST /api/books/{s}/{b}/chapters` takes an optional `number`; `number: 0` creates
`ch-00`. It sorts first because the chapter sort key is numeric, it is **never
scaffolded** (a new book still starts empty), and the rail offers `+ Prologue` only
while the book has none. A book *with* a prologue still numbers its next chapter
from the highest existing number (`max+1`, not `count+1`), so `ch-00` can't make
the next chapter `ch-01` again; a duplicate `ch-00` is a 409, and `number` is
validated 0..999. Everything downstream already keys off the id pattern and needs
no special case: revision snapshots `ch-00.<rev>.md`, notes `ch-00.notes.md`, the
Muse thread `<book>-ch-00.md`, trash entries, search rows, EPUB order.

## D35 — Muse threads are book-scoped (2.4, reads + adoption in 2.4.1)
Thread files are `archive/.katha/muse/<book>-<chapter>.md`, not `<chapter>.md`.
Chapter ids repeat across books (`ch-01` exists in every one of them), so the
chapter-only name silently shared one conversation between two books — open
`ch-01` in a second book and you were reading the first book's chat, and a chapter
delete could take the wrong book's history. Writes became book-scoped in 2.4;
**reads follow the same name and nothing else** (2.4.1), so no book can ever be
handed another book's conversation.
Pre-2.4 files are handled once, at boot, by `muse.migrate_legacy_threads()`: a
legacy `<chapter>.md` is adopted by the single book that both owns that chapter id
and **had that chapter when the conversation was written** (mtime, 60 s slack) —
which is what tells two books' `ch-01` apart, since the archive alone cannot. The
scan counts books sitting in the **trash** too, so a book the author has deleted
and can restore still claims its own log. If it stays un-attributable the file
moves to `.katha/muse/legacy/` and is re-examined on every boot: kept, never
served, never deleted. Deletes move only the book-scoped file; the legacy name is
shared, so it is never moved.

## D38 — The sample story is planted once, never re-planted (2.4.1)
`Dockerfile CMD` ran `python seed.py` on **every** container start, and `seed()`
re-creates whatever is missing — so an author who deleted every book found the
sample story back after any restart, and therefore after every deploy (it looked
exactly like a deleted book coming back from the dead). Booting an empty archive is
a legitimate state now: `seed.py --once` plants the sample only when there is no
book AND no `.katha/seeded` marker, and it writes the marker whenever it finds an
archive that already has books (so an upgrade from ≤2.4 is *recorded* as seeded
rather than re-seeded). `cd-deploy.sh` no longer refuses an empty archive for the
same reason — it refuses only a *missing* directory, which would mean
`KATHA_ARCHIVE_DIR` is mis-set.

## D34 — Bible files and whole series are deletable, through the same trash (2.4)
`DELETE /api/books/{s}/{b}/bible/{name}` and `DELETE /api/series/{series}`, each
with an `/impact` sibling the confirm dialog reads first. The bible is deleted
**file by file** by design: `ar.safe_bible_path()` — the guard the editor writes
through — resolves only real `.md` files, so a folder name resolves to nothing and
no request shape can take the whole bible. Keeping that boundary intact is worth
more than the convenience (D33 holds the trash semantics). A series moves as one
tree: its directory (books + `series.json`) plus every book-scoped Muse thread that
belongs to it, and restore puts all of it back.

## D33 — Delete is a move, and it can be undone (2.3)
The author can now remove a chapter or a whole book from the app. Because the
archive is the only copy of the novel, **delete never unlinks anything**: the
files move to `archive/.katha/trash/<stamp>-<kind>-<slug>/` beside a `trash.json`
manifest listing every path that moved, and Settings → Trash restores each one to
exactly where it came from (chapter md, every revision snapshot, the `.rev`
counter, the notes sidecar, the chapter's Muse thread — and `series.json` when the
last book of a series goes, or the rail is left with a series containing no
books).

`.katha/` is already git-ignored, hidden from `list_books()` and skipped by the
search indexer, so nothing in the trash can leak back into the UI while a misclick
stays recoverable. Nothing ages out on its own: markdown weighs nothing, and an
unexpected deletion is the thing this exists to prevent.

The app forgets immediately — index rows dropped, FTS rebuilt from disk, rail
refreshed. Restore **refuses (409) rather than overwrite** a path that something
else has taken since (a chapter id can be reused), and the confirm dialog asks the
server what would actually go (`…/impact` → chapters, words, revision snapshots,
notes, threads, files, bytes) so the delete is one deliberate click, never a
surprise.


## D32 — One password in front of everything (supersedes D12)
D12 said "single user, Tailscale, no auth — Tailscale is the boundary". That held
while Katha only ever ran on a tailnet. It now sits in front of the novels on a
host that can be exposed beyond it, so: **one password**, and everything except
the login page is behind it — the PWA shell, every `/api` route (Muse SSE
included) and the built assets. Public by necessity: `/login` itself, the PWA
manifest/icons/service worker (browsers fetch these without credentials, and they
carry no story data) and `/api/health` (the container's own healthcheck calls it
with no cookie — a 401 there would mark every deploy unhealthy and trip the CD
rollback).

`KATHA_PASSWORD` (plaintext env) is hashed at boot with the house scrypt helper;
the session is a signed cookie, `HttpOnly`, `SameSite=Lax`, 30 days, whose signing
key is derived from the password — so **rotating the password signs every session
out**. Empty password = no lock at all, which keeps dev/tailnet installs and the
test suite booting exactly like 2.0.x. `Secure` is set automatically when the
login arrived over TLS, or forced with `KATHA_COOKIE_SECURE=1`; plain http on the
tailnet (already WireGuard-encrypted) stays usable. Failed logins are throttled
(8 per 15 min per IP). The login page is self-contained and themed with the same
three token sets as the app (Hermes/Paper/Slate), following the same rule as the
shell: the OS decides until the author chooses.

## D31 — The archive gets a local snapshot; the card is an accepted risk
`katha-archive-backup.timer` (03:30 daily) tars the md archive and takes a
consistent SQLite copy of the index via SQLite's own backup API, keeping 14, all
on the deploy host — the same shape wedding-cards and shop-inventory use. The
off-box (gdrive/rclone) leg was considered and declined for now: the novels then
live on **one** SD card with same-card snapshots. That protects against a bad
edit, a bad deploy and index corruption — not against the card dying.

## D30 — Deploys happen any time; quiet hours are opt-in
`touch ~/katha/logs/night_only` restricts deploys to 22:00–00:00 IST for a period
the author wants frozen. Nothing is protected by default: a container restart
reconnects the PWA in seconds, and the author asked for deploys when they happen.

## D29 — A failed deploy never breaks a running one
The build runs before anything is replaced (a failed build exits with the running
version untouched), every deploy is tagged per-SHA (`katha:<sha>`) for rollback,
and after `up` the container's own healthcheck plus the `/api/health` version is
polled for 90 s — unhealthy ⇒ automatic rollback to `last_good`.

## D28 — The CI gate is real, and needs no secret on this host
`.github/workflows/test.yml` runs pytest (server) and a client build on every
push. The deploy script refuses to cross unless the pushed SHA's check-runs are
green, reading them via `gh` → `~/katha/secrets/github_ci_token` → **plain
unauthenticated curl** (the repo is public). Only if all three are unavailable
does it proceed with a loud WARN rather than silently skipping the gate.

## D27 — CI tests; the host builds
GitHub runners are x86 and this image must be arm64 — emulating that build with
qemu turns a ~80 s native build into ~10 minutes. So Actions runs the tests, and
the deploy host builds the image it will actually run.

## D26 — Dev and prod are different hosts *and* different directories
**abhi** runs prod: a deploy clone at `~/Projects/katha` that CD owns (main only,
never hand-edited), matching recruit / shop-inventory / wedding-cards.
`~/Projects/Katha` on bharat stays the workshop — branches, experiments, and
never the live archive — so uncommitted work can neither block a deploy nor be
shuffled by one.

## D25 — Data lives outside every checkout
`KATHA_ARCHIVE_DIR` / `KATHA_INDEX_DIR` (compose interpolation from
`server/.env`) point at `~/katha/archive` and `~/katha/index` on the deploy host;
the compose defaults stay `./archive` / `./data` so a fresh clone still boots. A
deploy `git pull` therefore cannot touch the novels, and no checkout owns the
truth. The deploy script refuses to deploy if those binds don't resolve or if the
archive is empty — a deploy that seeded an empty archive would look exactly like
the library was lost.

## D24 — Tool calls are translated, not dumbed down
The agentic Muse (D-tools: `list_story_files` / `read_story_file` / `search_story`)
must work on both dialects. Ollama and OpenAI disagree on the shape: OpenAI tool
calls carry an `id` + `type`, arguments as a JSON *string*, and results are paired
back with `tool_call_id` (we tag results with `tool_name` internally, so the
adapter matches them in order, by name). Streaming tool calls also arrive as
*fragments keyed by index* — id once, name once, arguments in pieces — so they are
reassembled before the tool loop ever sees them. Dumbing this down (dropping tools
on the cloud path) would silently disable the Muse's ability to read the story.

## D23 — A dead upstream fails fast and loudly
A blackholed upstream used to hang the Muse for the full `MUSE_UPSTREAM_TIMEOUT`
(300 s) while answering `200` with an empty stream — the UI showed nothing at all,
which reads as "frozen", not "broken". The connect step now gets its own short
budget (`MUSE_UPSTREAM_CONNECT_TIMEOUT`, default 10 s) and the existing `[ERROR]`
SSE event carries the failure to the client's error pane. Discovered the moment
the jenga box went dark.

## D22 — Model names are per dialect; an explicit env value always wins
A model id is meaningful only inside its dialect (`gemma4:12b` vs
`deepseek/deepseek-v4-flash`). Defaults are chosen per `KATHA_MUSE_API`, and any
explicit `MUSE_AGENT_MODEL` / `MUSE_REWRITE_MODEL` overrides both. Chat needs a
tool-capable model; rewrite wants a strong prose model — they may be different
vendors.

## D21 — Dialect, base URL and key are environment, never code
`KATHA_MUSE_API` (`ollama` | `openai`), `KATHA_MUSE_API_BASE` (full base, including
any `/v1`), `KATHA_MUSE_API_KEY` (bearer). The key is sent as a header only: never
logged, never returned by any endpoint, never echoed in an error message, never in
the client bundle. `server/.env` (gitignored) is injected via compose `env_file`,
so the secret is never written into the compose file.

## D20 — One dialect internally, two on the wire
The Muse keeps speaking the *Ollama* shape internally
(`{model, messages, options, tools, stream}` in, `{"message": {content, tool_calls}}`
out). `app/upstream.py` is the only module that knows a provider's wire format and
translates both directions when the dialect is `openai` (`options.num_predict` →
`max_tokens`, NDJSON → SSE deltas, and back). Everything the Muse learned since 0.3
— think-stripping, the tool loop, canon context, the style digest, thread
persistence — stays provider-agnostic and untouched. The LAN settings stay the
default, so `KATHA_MUSE_API=ollama` restores the old behavior byte for byte.

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

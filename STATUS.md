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

- **2.1.1 / 2.2.0** — the pipeline and the door (shipped together as **2.2.0**).
  **Pipeline**: a GitHub Actions gate (pytest + client build) on every push, and a
  pull-based CD timer on the prod host (`katha-cd.timer`, every 5 min) that
  deploys only when `origin/main` moves and the pushed SHA's checks are green
  (unauthenticated check-runs — the repo is public), builds before replacing
  anything, tags each deploy per-SHA, health-gates it and auto-rolls back to the
  last good tag. **Growth path**: `KATHA_ARCHIVE_DIR`/`KATHA_INDEX_DIR` moved the
  archive and index *outside* the checkout, so a deploy pull can never touch the
  novels and prod can live on a different host (`~/katha/archive` +
  `~/katha/index` on the deploy host) while the workshop stays a workshop. Plus
  `katha-archive-backup.timer`: a daily snapshot of the md archive and a
  consistent copy of the index, keeping 14.
- **2.6.0** — the mark. Katha has a logo: a near-black tile carrying a golden
  **क** — the first letter of कथा — rendered as metal lit from the upper-left
  (champagne where the light strikes, the app's own `#ffbf00` across the surface,
  amber where it turns away), with a specular band and a soft shadow lifting it
  off the tile. It is *generated*: `scripts/make-logo.py` writes `logo.svg` and
  every icon from the same numbers — favicons tuned per size (16/32 are
  deliberately heavier), 180 for iOS, a maskable 512 that sits inside the safe
  circle — because the whole lighting model is a single `t = (x + y)` ramp, which
  is literally what an SVG `linearGradient` (0,0)→(1,1) is (D41). It now shows in
  the title bar, the login card and the browser tab; `/logo.svg` is public
  *exactly* (never as a prefix) so the locked card can display it.
- **2.5.1** — the door and the map. **Settings** now holds the two controls the
  title bar kept to itself: the three-way **theme** choice (with swatches, same
  setting the picker writes, so they stay in sync) and **Lock now** — which never
  existed on a phone, because the title bar hides `lock` below 768px. **Focus mode
  keeps the chapter list**, retractable: the rail's toggle collapses it to the 48px
  strip of chapter numbers, and that choice persists. The Muse column still folds
  away in focus.
- **2.5** — chapter 0, and chats that know whose they are. A book can now have an
  **optional prologue**: `+ Prologue` in the rail (offered only while the book
  doesn't have one) creates `ch-00`, which sorts before chapter one and does not
  disturb numbering — the next new chapter is still `ch-01`, then `ch-02`. New
  books never get one; a duplicate is a clean 409 (D39). And finishing the
  2.4.1 thread work: pre-2.4 Muse chats are now adopted by the book that **had that
  chapter when the conversation was written** — the archive alone can't tell two
  books' `ch-01` apart, but time can, so an author whose old book shares a chapter
  id with a new one still gets the right conversation back (and the book can be
  sitting in the trash while it happens) (D35).
- **2.4.1** — two bugs that both amounted to *"it came back"*. (1) The sample
  story was re-planted on **every** container start (`Dockerfile CMD` ran
  `python seed.py`, which re-creates whatever is missing), so deleting every book
  lasted only until the next restart or deploy — and the resurrected sample looked
  exactly like the deleted book. Seeding is now a first-run act (`seed.py --once`
  + a `.katha/seeded` marker), an empty archive is legitimate, and the deploy
  guard refuses only a *missing* archive dir (D38). (2) Muse threads were
  book-scoped for writing in 2.4 but still *read* the old chapter-only name, so
  `ch-01` in a new book showed the first book's conversation; reads are now
  book-scoped with no fallback, and pre-2.4 threads are adopted once at boot by
  the book that owns that chapter id — counting books sitting in the trash, so a
  deleted-then-restored book still gets its own chat back. Un-attributable legacy
  files are kept in `.katha/muse/legacy/`, never served (D35).
- **2.4** — the rest of the tree, and the door out. **Bible files** can be deleted
  from the bible panel (a `×` on each row) and a whole **series** can be taken out
  in one move, both through the same move-to-trash machinery as chapters and books
  (D33) — the confirm dialog asks the server what would actually go (books,
  chapters, words, revision snapshots, margin notes, Muse threads, bible files,
  files, size) before it offers the red button. A bible file is deleted one file at
  a time, on purpose: the guard the editor writes through only resolves real `.md`
  files, so no path shape exists that takes the whole bible (D34). A series travels
  as one tree — books, `series.json`, and the books' own Muse conversations — and
  comes back whole. **Erasing is now possible**: Settings → Trash can `Erase for
  good` one entry or `Empty trash`, which is the only code path in Katha that
  destroys anything, and it always asks twice (D36). Under the hood the Muse thread
  files are now book-scoped — `ch-01.md` exists in every book, so the old
  chapter-only name meant two books shared one conversation and a delete could
  steal the other book's history (D35). Also fixed: an empty archive was reported
  as *"Failed to load archive — server didn't respond"*, which was both false and
  hid the trash; the empty state now offers to start a book or series (D37).
- **2.3** — delete + revive. A chapter or a whole book can be removed from the
  rail (a hover `×` on the chapter row, `×` beside the book selector), behind a
  dialog that says exactly what would go — chapters, words, revision snapshots,
  margin notes, Muse threads, files, size — with one deliberate red button. It is
  never an erase: the files move into `archive/.katha/trash/` with a manifest, and
  **Settings → Trash** brings any entry back to precisely where it was (revision
  counter and all, `series.json` included when the last book of a series goes).
  Restore refuses rather than clobber a path that has been reused since. The app
  forgets immediately: index rows dropped, search rebuilt, rail refreshed.
- **2.2** — the door. One password (`KATHA_PASSWORD`, hashed at boot with scrypt)
  in front of everything except the login page: the PWA shell, every `/api` route
  including the Muse SSE streams, and the built assets. Signed `HttpOnly`
  SameSite 30-day session cookie whose key derives from the password (rotating it
  signs everyone out); failed attempts throttled; `/api/health`, the PWA
  manifest/icons and the service worker stay public (browsers and the container's
  own healthcheck fetch them without credentials). An empty password means no
  lock, so dev and the test suite boot as before. The login page is
  self-contained and themed with the app's three token sets; an expired session
  bounces the SPA to `/login` instead of showing a mystery error, and there is a
  `lock` button in the title bar.

## Next
- Dogfood the full loop (write → autosave/revisions → Muse tools → rewrite diff
  → sweep → reading + notes → EPUB); browser-verify the three themes + mobile.
- Then: a revision-history browser (list / preview / restore).
- Later: a settings affordance for the Muse dialect (today it's env-only).

## Verify
- Server: `cd server && .venv/bin/python -m pytest -q` (86 tests).
- Client: `cd desktop && npm run build`.
- Install: build, serve via the Pi, open over `tailscale serve` HTTPS, Install app.
- Deploy: `katha-cd.timer` (every 5 min) on the prod host; decisions land in
  `~/katha/logs/cd.log`. Manual: `scripts/cd-deploy.sh --force`.

## Open
- The Muse upstream must be reachable: the LAN Ollama box (`KATHA_MUSE_API=ollama`,
  default) or a cloud gateway with a key (`KATHA_MUSE_API=openai`). With neither,
  everything except the Muse still works — writing, revisions, search, bible,
  reading mode, EPUB.
- Whole-book continuous reading mode and offline support are out of scope.

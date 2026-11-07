# Katha — Status

**Phase 2.1** — the IDE is complete and shipping as an installable PWA, with
reading mode, writing rituals, and EPUB delivery. The client is served from the
same FastAPI server as the API. The Muse is no longer tied to one brain: it can
talk to the LAN Ollama box, any OpenAI-compatible gateway, **or** a gateway that
serves Claude models in the Messages shape (2.7.0).

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
- **3.0.4** — the author's own numbers: line spacing **1.55**, paragraph gap **1.00em**
  (reading mode), with the write view and review pane set to the same rhythm so a chapter
  reads identically wherever it appears. Focus mode keeps a touch more air (1.62) for
  large-text composition. Tuned from a live preview rather than guessed.
- **3.0.3** — page rhythm. Reading mode had a line spacing of 1.95 and a paragraph gap of
  12px — the gap was *less than half a line*, so paragraphs ran together. Both directions
  now: lines tightened to 1.7 and paragraph gaps widened to 1.25em (~0.7 of a line, up from
  0.36), headings given more room above them, blockquotes the same treatment. Writing mode
  tightened to 1.7 (1.78 in focus) and the review pane matches, so prose reads the same
  wherever it appears. (A textarea has no paragraph model — its blank line *is* the gap, and
  it scales with the line height — so "more paragraph spacing" is only available in reading
  mode.)
- **3.0.2** — the review pane scrolls. It was the one fixed-height overlay in the app
  without the `flex h-full flex-col` wrapper, so its body grew instead of scrolling and the
  card's `overflow-hidden` clipped it: eleven changes, of which you could see the first few
  and reach no further. Now it matches BiblePanel and SweepPanel, which never had the
  problem. Keyboard moves between changes (`n`/`p`) scroll the pane too.
- **3.0.1** — an accept is only valid against the text the Muse read. Found on real data:
  ch-01 had been saved (226 words) *after* the waiting revision was written, and accepting
  would have merged it over prose the Muse never saw. Accepting now refuses with 409 and
  says why; the review pane warns before you tick anything. A partial accept is unaffected
  (it re-points the revision at what it just wrote). Also fixed: the proposal list counted
  hunks against nothing and reported 1 for an eleven-change revision.
- **3.0.0** — per-hunk review. A whole-chapter revision is no longer one yes/no: it is cut
  into hunks (word diff, git-style grouping) and reviewed one change at a time, in a pane
  that walks the chapter — untouched prose, then each change with its old and new lines and
  a ✓/✗ toggle. Accept some, set others aside: what you set aside stays pending, re-pointed
  at the revision you just wrote, and the leftovers still add up to the Muse's version
  exactly. Rejecting everything saves nothing and burns no revision. The banner now says how
  many decisions are waiting ("3 changes proposed — none applied"). **185 tests**, 18 of them
  the hunk maths and 5 the per-hunk routes.
- **2.9.3** — a waiting revision is discoverable. The banner was raised only by the live
  `[PROPOSAL]` marker, so a revision parked in another tab, in an earlier session, or by
  the API was on disk and invisible — the panel showed nothing. It now asks the server
  what is pending for the open chapter when it loads (D47). Also: progress lines read
  like progress — `reading the story index…`, not `reading list_story_files…`.
- **2.9.2** — a revision is announced only when the turn is finished. Parts can arrive
  across rounds, so announcing as soon as the first part lands would let you accept a
  third of a chapter; the marker is now collected during the turn and emitted at the end.
  (Caught while reading the parts code, before anyone hit it.)
- **2.9.1** — room to write a chapter. 2.9.0's handover worked on short chapters and
  failed silently on real ones: ch-01 is 4,775 words ≈ 7k tokens, but the chat's output
  ceiling was 4096, so the tool arguments were **truncated mid-JSON** — they parsed to
  nothing and the Muse was told "0 characters". It retried five times and then reported
  the failure to the author as "each attempt went out empty", which is what you saw.
  Now the agentic chat has its own ceiling (`MUSE_AGENT_MAX_TOKENS`, 32k — the gateway
  allows 64k, and only generated tokens cost), truncated arguments are reported as
  *cut off* instead of empty, a long revision may arrive in **parts** (each call appends
  to the same revision), and pending revisions are deleted along with their book.
- **2.9.0** — the Muse proposes, the author disposes. Asking the Muse to "write the
  chapter" used to produce either prose to copy by hand or, worse, a promise to do
  it later — its tools were read-only and the author was left holding the text. Now
  it has a real handover: `propose_chapter_rewrite` parks the complete revision,
  the stream announces `[PROPOSAL] <id>`, and the Muse panel offers **Review diff**
  (the existing word-level overlay, whole chapter vs whole chapter) with **Accept**
  or **Discard**. Accept runs the *same* save path as autosave, so the revision
  snapshot, search index and writing stats behave exactly as if you had typed it;
  discard leaves the chapter untouched because it never was touched. Revisions under
  200 characters, or identical to what is already there, are refused with a reason
  the model sees. 13 new tests pin the safety property that matters most: *the
  chapter file and its revision counter are unchanged by a proposal.*
- **2.8.1** — the deploy learns to wait, and the Muse learns to work. A forced deploy
  of 2.8.0 landed 57 seconds into a Muse turn: recreating the container killed the
  stream mid-reply, and the persisted thread kept a half-written assistant turn
  ("I'll re-open ch-01…") — after which the model spent its next turn apologising
  instead of working, and the author reasonably concluded the Muse had ignored them.
  `cd-deploy.sh` now **defers while the archive is being written to** (5 minutes,
  `KATHA_DEPLOY_QUIET_MINUTES`, `--force` still overrides), so a CI-green commit
  waits instead of interrupting. The Muse's system prompt also states the two rules
  it kept missing: call a tool in the same turn rather than announcing it, and write
  the prose into the reply because its tools are read-only (the Muse proposes, the
  author applies). Pinned by a test on the upstream payload; 143 tests green; the
  guard verified by running it against a freshly-touched archive.
- **2.8.0** — the book's face. An EPUB with no cover is a grey rectangle in every
  reader's library, and Katha's exports had no `<dc:creator>` either, so the shelf
  could not even say who wrote it. Both now exist, and neither is invented: **the
  cover is your own image**, normalised on upload (real format sniffed, EXIF
  orientation honoured, fitted to 1600×2560 without upscaling, alpha flattened,
  re-encoded JPEG under 8 MB) and stored *inside the book* so it survives delete →
  restore and rides along in every backup. The EPUB gets the full wiring — image
  item with `properties="cover-image"`, `cover.xhtml` first in the spine, the
  legacy `<meta name="cover">`, a `guide` reference — plus **the author**, held per
  book in `book.json` (a Settings value only prefills; a pen name per series works).
  Reachable from the rail's ✎ on the book row: author, cover preview/replace/remove,
  and a *Download EPUB* button right there so you can check the shelf result. New
  books can be born with their author. 13 new tests (`tests/test_cover.py`) pin the
  normalisation, the exact EPUB wiring, the no-cover case, the trash round trip and
  the lock over every new route — and one of them caught a real bug on the way in
  (CSS braces eaten by a `.format()` template).
- **2.7.1** — the gateway's two rules, learned the hard way. 2.7.0 shipped the
  dialect and a green test suite; pointing it at the real Claude model then
  answered `400 unsupported_model: … must be called via /messages` (fixed by the
  dialect itself), and after that `400 invalid_request_error: temperature is
  deprecated for this model`. Current Claude models **refuse sampling
  parameters**, so the messages dialect no longer forwards `temperature` — a
  lost knob beats a lost answer. Verified live afterwards, through the gateway,
  with a real tool call: `[STATUS] reading …`, `tool_use` blocks streamed as
  `input_json_delta` fragments, `stop_reason: tool_use`, and the rewrite slot
  answering on the second model setting.
- **2.7.0** — the Muse learns a third dialect. `app/upstream.py`
  now speaks the **Messages shape** (`POST {base}/messages`, `x-api-key` + a
  version pin) alongside Ollama-native and OpenAI-compatible — which is what a
  gateway requires for Claude models, and the only way to reach one that is not
  the vendor itself. System turns become the top-level `system` field,
  `max_tokens` is always sent (the shape demands it), tools flatten to
  `input_schema`, tool results ride in *user* turns paired to their `tool_use` by
  id, and streaming `text_delta` / `input_json_delta` fragments reassemble into
  exactly the internal events the agentic loop already consumed — so not one line
  of `muse.py` changed (D42). The net grew 12 → 22 tests in `test_upstream.py`,
  including one that pins the failure that started it (a gateway refusing the
  model must surface its message as `[ERROR]`, not stream nothing).
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
  *exactly* (never as a prefix) so the locked card can display it. (2.6.1, after
  looking at it in place: the title-bar mark goes to 18px — 16 is the floor of
  legibility for a looped glyph — and the login mark drops 1px to sit level with
  the wordmark.)
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

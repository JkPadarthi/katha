import React, { useEffect, useState } from 'react'
import TopBar from './shell/TopBar.jsx'
import Dock from './shell/Dock.jsx'
import Conversation from './shell/Conversation.jsx'
import Editor, { editorApi } from './components/Editor.jsx'
import CommandPalette from './components/CommandPalette.jsx'
import DiffOverlay from './components/DiffOverlay.jsx'
import ProposalReview from './components/ProposalReview.jsx'
import HistoryPanel from './components/HistoryPanel.jsx'
import SecurityPanel from './components/SecurityPanel.jsx'
import SweepPanel from './components/SweepPanel.jsx'
import BiblePanel from './components/BiblePanel.jsx'
import SettingsPanel from './components/SettingsPanel.jsx'
import ConfirmDeleteDialog from './components/ConfirmDeleteDialog.jsx'
import NewBookDialog from './components/NewBookDialog.jsx'
import BookDetailsDialog from './components/BookDetailsDialog.jsx'
import Icon from './ui/Icon.jsx'
import { Button } from './ui/Button.jsx'
import * as api from './lib/api.js'
import { getSetting, setSetting } from './lib/settings.js'
import { useTheme } from './lib/useTheme.js'
import { useBook } from './lib/useBook.js'
import { useMuse, museApi } from './lib/useMuse.js'
import { useReview } from './lib/useReview.js'
import { useStats } from './lib/useStats.js'
import { useMeasure, MEASURES } from './lib/useMeasure.js'

// KATHA 4.0 — "One Page" (D63). The manuscript has the whole window. Where you are is a
// breadcrumb at the top that opens the book; the Muse is a dock at the bottom of the
// page; its changes are reviewed in the prose itself. The same layout on a phone.
export default function App() {
  const { theme, choose } = useTheme()
  const nav = useBook()
  const { archive, series, book, chapter, chapterKey, activeChapter } = nav
  const muse = useMuse({ series, chapter, book })

  // panels
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [focusMode, setFocusMode] = useState(() => getSetting('focus', false))
  const [threadOpen, setThreadOpen] = useState(() => getSetting('thread', false))
  const [historyOpen, setHistoryOpen] = useState(false)
  const [securityOpen, setSecurityOpen] = useState(false)
  const [sweepOpen, setSweepOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [newBookOpen, setNewBookOpen] = useState(false)
  const [bookFace, setBookFace] = useState(false)
  const [bibleName, setBibleName] = useState(null)        // null = closed
  const [bibleKey, setBibleKey] = useState(0)             // bumped: the bible re-reads
  const [confirmTarget, setConfirmTarget] = useState(null)

  // preferences
  const [ghostOn, setGhostOn] = useState(() => getSetting('ghost', false))
  const [goal, setGoal] = useState(() => getSetting('goal', '') ?? '')
  const [nudgeOn, setNudgeOn] = useState(() => getSetting('nudge', false))
  const [nudge, setNudge] = useState(false)
  const stats = useStats(goal)
  const [measure, setMeasure] = useMeasure()

  // the selection on the page, and what the Muse does with it
  const [selection, setSelection] = useState(null)
  const [inlineBusy, setInlineBusy] = useState(false)
  const [rewriteOpen, setRewriteOpen] = useState(false)
  const [proposed, setProposed] = useState('')
  const [rewriteBusy, setRewriteBusy] = useState(false)
  const [rewriteStyle, setRewriteStyle] = useState('novel')

  useEffect(() => { setSetting('focus', focusMode) }, [focusMode])
  useEffect(() => { setSetting('thread', threadOpen) }, [threadOpen])

  // A saved file goes straight into the editor as the saved baseline — never through
  // autosave, which would write it a second time and make the rest stale (3.1, D61).
  const landSaved = (saved) => {
    if (!saved) return
    if (saved.kind === 'bible') {
      setBibleKey((k) => k + 1)
    } else if (saved.id === activeChapter && editorApi.loadSaved) {
      editorApi.loadSaved(saved.content, saved.title, saved.revision)
      setSelection(null)       // its offsets point into the text that was just replaced
    }
  }
  const review = useReview({ series, landSaved, refreshArchive: nav.refresh })
  const { proposal } = review

  const jump = (id) => {
    nav.setActiveChapter(id)
    setSelection(null)
  }

  // keyboard: ⌘K palette, ⌘⇧F focus, ⌘I edit the selection, Esc backs out
  useEffect(() => {
    const onKey = (e) => {
      const mod = e.metaKey || e.ctrlKey
      const key = e.key.toLowerCase()
      if (mod && key === 'k') { e.preventDefault(); setPaletteOpen((v) => !v) }
      if (mod && e.shiftKey && key === 'f') { e.preventDefault(); setFocusMode((v) => !v) }
      if (mod && !e.shiftKey && key === 'i') { e.preventDefault(); setFocusMode(false); setTimeout(() => museApi.focus?.(), 0) }
      if (e.key === 'Escape') {
        setPaletteOpen(false)
        setRewriteOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Proactive nudge (D11): off by default.
  useEffect(() => {
    if (!nudgeOn) { setNudge(false); return }
    let timer
    const reset = () => {
      setNudge(false)
      clearTimeout(timer)
      timer = setTimeout(() => {
        if (!paletteOpen && !rewriteOpen && !sweepOpen && !settingsOpen) setNudge(true)
      }, 4 * 60 * 1000)
    }
    const evs = ['keydown', 'mousemove', 'mousedown', 'touchstart']
    evs.forEach((e) => window.addEventListener(e, reset))
    reset()
    return () => {
      clearTimeout(timer)
      evs.forEach((e) => window.removeEventListener(e, reset))
    }
  }, [nudgeOn, paletteOpen, rewriteOpen, sweepOpen, settingsOpen])

  // --- inline edit on a selection (3.1, D57) — sent from the dock since 4.0 -----------
  const runInline = async (instruction) => {
    const sel = selection
    if (!instruction || !sel?.text || !museApi.ask) return
    setInlineBusy(true)
    try {
      // The Muse reads the file, so the passage must be on disk first.
      if (editorApi.flush) await editorApi.flush()
      const ids = await museApi.ask(
        `Selected passage (in ${chapter?.id}), exactly as it stands in the file:\n<<<\n${sel.text}\n>>>\n\nInstruction: ${instruction}`,
        { chip: 'inline', chapterId: chapterKey }
      )
      if (ids && ids.length) {
        muse.dismiss()
        await review.open(ids[ids.length - 1])
      }
    } catch { /* the reply card shows the error */ }
    finally {
      setInlineBusy(false)
    }
  }

  // --- Fix a continuity issue from the sweep (3.1, D60) -------------------------------
  const fixIssue = async (issue) => {
    if (!series || !book) return
    setSweepOpen(false)
    const ids = new Set((book.chapters || []).map((c) => c.id))
    const target = issue.refs.find((r) => ids.has(r)) || activeChapter
    if (!target) return
    if (target !== activeChapter) jump(target)
    const staged = await museApi.ask?.(
      `Fix this continuity issue — [${issue.refs.join(', ')}] ${issue.text}`,
      { chip: 'fix', chapterId: `${series.series}/${series.book}/${target}` }
    )
    if (staged && staged.length) await review.open(staged[0])
  }

  // --- rewrite a selection in a chosen style, side by side ------------------------------
  const runRewrite = async (sel, style) => {
    if (!sel || !sel.text) return
    setProposed('')
    setRewriteBusy(true)
    setRewriteOpen(true)
    try {
      const full = await api.museRewrite({ text: sel.text, style, chapterId: chapterKey, onDelta: (acc) => setProposed(acc) })
      setProposed(full)
    } catch (e) {
      setProposed('— Muse unavailable: ' + (e.message || 'unknown error') + ' —')
    } finally {
      setRewriteBusy(false)
    }
  }
  const onRewriteAccept = () => {
    if (editorApi.replaceSelection && proposed) editorApi.replaceSelection(proposed)
    setRewriteOpen(false)
    setProposed('')
    setSelection(null)   // offsets are stale once the text is replaced
  }

  // The open chapter's own changes are reviewed on the page itself (3.1, D60 — on a
  // phone too since 4.0); a bible file or another chapter in the review sheet.
  const inlineReview = !!proposal && proposal.kind === 'chapter' && proposal.chapter === activeChapter
  const reviewNode = (inline) => (
    <ProposalReview
      id={proposal.id}
      kind={proposal.kind}
      path={proposal.path}
      original={proposal.original}
      hunks={proposal.hunks}
      stale={proposal.stale}
      dropped={proposal.dropped}
      siblings={proposal.siblings}
      inline={inline}
      busy={review.busy}
      onAccept={(ids) => review.accept(ids)}
      onAcceptAllFiles={review.acceptAll}
      onDiscard={review.discard}
      onSwitch={review.open}
      onClose={review.close}
    />
  )

  const deleteChapter = (c) => setConfirmTarget({ kind: 'chapter', series: series.series, book: series.book, chapter: c.id, label: c.title })
  const deleteBook = () => {
    const s = archive?.find((x) => x.name === series?.series)
    setConfirmTarget({ kind: 'book', series: series.series, book: series.book, seriesTitle: s?.title || series.series, label: book?.title || series.book })
  }
  const exportEpub = () => series && api.exportEpub(series.series, series.book, `${series.book}.epub`).catch(() => {})

  // Every action the top bar and the palette can take, in one place.
  const actions = {
    jump,
    selectBook: (s, b) => { nav.selectBook(s, b); setSelection(null) },
    newChapter: async (kind) => { const c = await nav.newChapter(kind); if (c) setSelection(null) },
    newBook: () => setNewBookOpen(true),
    openBible: (name) => setBibleName(name || ''),
    sweep: () => setSweepOpen(true),
    editBook: () => setBookFace(true),
    exportEpub,
    deleteChapter,
    deleteBook,
    palette: () => setPaletteOpen(true),
    settings: () => setSettingsOpen(true),
    security: () => setSecurityOpen(true),
    toggleFocus: () => setFocusMode((v) => !v),
    chooseTheme: choose,
    measure,
    setMeasure
  }

  const commands = [
    ...(chapter ? [{ id: 'history', label: 'Revision history', hint: 'Chapter', run: () => setHistoryOpen(true) }] : []),
    ...(selection?.text ? [{ id: 'inline', label: 'Edit selection with the Muse', hint: 'Ctrl/⌘+I', run: () => museApi.focus?.() }] : []),
    { id: 'thread', label: threadOpen ? 'Hide the conversation' : 'Show the conversation with the Muse', hint: 'Muse', run: () => setThreadOpen((v) => !v) },
    { id: 'focus', label: focusMode ? 'Leave focus mode' : 'Focus mode', hint: 'Ctrl+Shift+F', run: actions.toggleFocus },
    { id: 'new-chapter', label: 'New chapter', hint: 'Write', run: () => actions.newChapter('chapter') },
    { id: 'new-book', label: 'New book', hint: 'Write', run: actions.newBook },
    { id: 'bible', label: 'Open bible', hint: 'Canon', run: () => setBibleName('') },
    { id: 'sweep', label: 'Canon sweep', hint: 'Muse', run: actions.sweep },
    ...(series ? [{ id: 'export', label: 'Export EPUB', hint: 'Deliver', run: exportEpub }] : []),
    { id: 'theme', label: theme === 'hermes' ? 'Light mode' : 'Dark mode', hint: 'Theme', run: () => choose(theme === 'hermes' ? 'day' : 'hermes') },
    ...MEASURES.filter((m) => m.id !== measure).map((m) => ({ id: 'measure-' + m.id, label: `Page width: ${m.label}`, hint: 'View', run: () => setMeasure(m.id) })),
    { id: 'settings', label: 'Settings', hint: '', run: actions.settings },
    { id: 'security', label: 'Muse & security (provider, API key, password)', hint: 'Settings', run: actions.security },
    { id: 'lock', label: 'Lock', hint: '', run: api.signOut }
  ]

  const nudgeNode = nudge && !focusMode && (
    <div className="float mb-2 flex items-center gap-2 rounded-full py-1 pl-4 pr-1 text-[13.5px] text-mute">
      <span className="flex-1">Still going?</span>
      <button
        onClick={() => { museApi.setDraft?.('Continue the scene from where I left off.'); setNudge(false) }}
        className="h-8 rounded-full px-3 text-[13px] font-medium text-accent hover:bg-accent/10"
      >
        Ask the Muse
      </button>
      <button onClick={() => setNudge(false)} aria-label="Dismiss" className="inline-flex h-8 w-8 items-center justify-center rounded-full hover:bg-panel-2">
        <Icon name="x" size={15} />
      </button>
    </div>
  )

  return (
    <div className="flex h-full flex-col bg-base">
      {!focusMode && (
        <TopBar
          archive={archive}
          series={series}
          book={book}
          chapter={chapter}
          stats={stats}
          theme={theme}
          focus={focusMode}
          a={actions}
        />
      )}

      {archive && series ? (
        <div className="relative flex min-h-0 flex-1">
          <div className="relative min-w-0 flex-1">
            <Editor
              chapter={chapter}
              series={series}
              focus={focusMode}
              onSelection={setSelection}
              onHistory={() => setHistoryOpen(true)}
              ghost={ghostOn}
            />
            {inlineReview && reviewNode(true)}
            {!inlineReview && !focusMode && (
              <Dock
                muse={muse}
                selection={selection}
                onInline={runInline}
                onRewrite={selection?.text ? () => runRewrite(selection, rewriteStyle) : null}
                inlineBusy={inlineBusy}
                onReview={review.open}
                onAcceptAll={review.acceptAll}
                reviewBusy={review.busy}
                threadOpen={threadOpen}
                onToggleThread={() => setThreadOpen((v) => !v)}
                disabled={!chapter}
              >
                {nudgeNode}
              </Dock>
            )}
            {focusMode && (
              <button
                onClick={() => setFocusMode(false)}
                className="absolute right-4 top-4 z-30 inline-flex h-9 items-center gap-2 rounded-lg px-3 text-[13px] text-mute opacity-40 transition-opacity hover:bg-panel-2 hover:text-ink hover:opacity-100 focus:opacity-100"
                title="Leave focus mode (Ctrl+Shift+F)"
              >
                <Icon name="focus" size={16} /> Leave focus
              </button>
            )}
          </div>
          {threadOpen && !focusMode && (
            <Conversation muse={muse} chapterTitle={chapter?.title} onClose={() => setThreadOpen(false)} />
          )}
        </div>
      ) : nav.loadError ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
          <div className="text-[15px] font-medium text-err">Couldn't load the archive</div>
          <div className="text-[13px] text-mute">{nav.loadError}</div>
          <div className="text-[12.5px] text-mute">
            Tried <code className="text-ink">{window.location.origin}</code>. Open DevTools (F12) → Network for details.
          </div>
        </div>
      ) : archive ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
          <h1 className="font-serif text-[30px] font-semibold text-ink">Your archive is empty</h1>
          <p className="max-w-sm text-[14px] leading-relaxed text-mute">
            Start a series and a book — that's the whole setup. The chapters, the bible and
            the Muse all hang off it.
          </p>
          <Button variant="primary" size="lg" onClick={() => setNewBookOpen(true)}>New book</Button>
          <p className="text-[13px] text-mute">Deleted something? It is waiting in Settings → Trash.</p>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center text-[14px] text-mute">Opening the archive…</div>
      )}

      {paletteOpen && archive && (
        <CommandPalette
          onClose={() => setPaletteOpen(false)}
          onJump={jump}
          onOpenHit={(hit) => {
            setSelection(null)
            if (nav.openHit(hit) === 'bible') setBibleName(hit.doc_id)
          }}
          series={series}
          archive={archive}
          commands={commands}
        />
      )}
      {rewriteOpen && selection && (
        <DiffOverlay
          original={selection.text}
          proposed={proposed}
          busy={rewriteBusy}
          style={rewriteStyle}
          onStyleChange={(s) => { setRewriteStyle(s); if (selection) runRewrite(selection, s) }}
          onAccept={onRewriteAccept}
          onRetry={() => selection && runRewrite(selection, rewriteStyle)}
          onClose={() => { setRewriteOpen(false); setProposed('') }}
        />
      )}
      {proposal && !inlineReview && reviewNode(false)}
      {historyOpen && series && chapter && (
        <HistoryPanel
          series={series}
          chapter={chapter}
          current={editorApi.current ? editorApi.current() : null}
          onRestored={(saved) => {
            landSaved({ ...saved, kind: 'chapter' })
            nav.refresh()
            museApi.refreshPending?.()     // waiting edits replay onto the restored text
          }}
          onClose={() => setHistoryOpen(false)}
        />
      )}
      {sweepOpen && series && (
        <SweepPanel
          series={series}
          onClose={() => setSweepOpen(false)}
          onFix={fixIssue}
          onReview={(id) => { setSweepOpen(false); review.open(id) }}
        />
      )}
      {bibleName !== null && series && (
        <BiblePanel
          series={series}
          initial={bibleName}
          onClose={() => setBibleName(null)}
          onChanged={nav.refresh}
          refreshKey={bibleKey}
          onDeleteFile={(name) => setConfirmTarget({ kind: 'bible', series: series.series, book: series.book, path: name, label: name })}
        />
      )}
      {settingsOpen && (
        <SettingsPanel
          goal={goal}
          onGoal={(v) => { setGoal(v); setSetting('goal', v === '' ? null : Number(v)) }}
          nudge={nudgeOn}
          onNudge={(v) => { setNudgeOn(v); setSetting('nudge', v) }}
          ghost={ghostOn}
          onGhost={(v) => { setGhostOn(v); setSetting('ghost', v) }}
          onOpenSecurity={() => setSecurityOpen(true)}
          onClose={() => setSettingsOpen(false)}
          onRestored={nav.refresh}
          theme={theme}
          onChooseTheme={choose}
        />
      )}
      {securityOpen && <SecurityPanel onClose={() => setSecurityOpen(false)} />}
      {newBookOpen && (
        <NewBookDialog
          onClose={() => setNewBookOpen(false)}
          onCreated={async (b) => { setNewBookOpen(false); await nav.onBookCreated(b); setSelection(null) }}
        />
      )}
      {bookFace && series && (
        <BookDetailsDialog
          series={series.series}
          book={series.book}
          title={book?.title || series.book}
          author={book?.author || ''}
          hasCover={!!book?.has_cover}
          onClose={() => setBookFace(false)}
          onSaved={nav.refresh}
        />
      )}
      {confirmTarget && (
        <ConfirmDeleteDialog
          target={confirmTarget}
          onClose={() => setConfirmTarget(null)}
          onDeleted={async (manifest) => {
            setConfirmTarget(null)
            if (manifest.kind === 'bible') setBibleKey((k) => k + 1)
            await nav.onDeleted(manifest)
            setSelection(null)
          }}
          onDeleteSeries={
            confirmTarget.kind === 'book'
              ? () => setConfirmTarget({ kind: 'series', series: confirmTarget.series, label: confirmTarget.seriesTitle || confirmTarget.series })
              : undefined
          }
        />
      )}
    </div>
  )
}

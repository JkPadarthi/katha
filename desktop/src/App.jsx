import React, { useEffect, useMemo, useState } from 'react'
import TitleBar from './components/TitleBar.jsx'
import Rail from './components/Rail.jsx'
import Page, { pageApi } from './components/Page.jsx'
import Muse, { museApi } from './components/Muse.jsx'
import CommandPalette from './components/CommandPalette.jsx'
import DiffOverlay from './components/DiffOverlay.jsx'
import Sweep from './components/Sweep.jsx'
import Settings from './components/Settings.jsx'
import * as api from './api.js'
import { getSetting, setSetting } from './settings.js'

export default function App() {
  const [archive, setArchive] = useState(null)
  const [series, setSeries] = useState(null)
  const [activeChapter, setActiveChapter] = useState(null)
  const [railCollapsed, setRailCollapsed] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  // Focus mode — hide the rails, center the page on the writing. Persisted.
  const [focusMode, setFocusMode] = useState(() => getSetting('focus', false))
  // Canon sweep overlay (0.4)
  const [sweepOpen, setSweepOpen] = useState(false)
  // Settings + writing rituals + proactive nudge (1.0)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [goal, setGoal] = useState(() => getSetting('goal', '') ?? '')
  const [nudgeOn, setNudgeOn] = useState(() => getSetting('nudge', false))
  const [nudge, setNudge] = useState(false)
  // Surface archive-load errors so the user sees what went wrong (instead
  // of a silent "Loading archive…" forever).
  const [loadError, setLoadError] = useState('')
  // Rewrite flow (0.3.3)
  const [selection, setSelection] = useState(null)
  const [rewriteOpen, setRewriteOpen] = useState(false)
  const [proposed, setProposed] = useState('')
  const [rewriteBusy, setRewriteBusy] = useState(false)
  const [rewriteStyle, setRewriteStyle] = useState('novel')

  // Load the live archive from the FastAPI backend.
  useEffect(() => {
    let alive = true
    setLoadError('')
    api
      .loadArchive()
      .then((a) => {
        if (!alive) return
        setArchive(a)
        // Pick the first book that actually has chapters. Defensive — even
        // with the hidden-dir fix, a future empty seeded series shouldn't
        // leave us stuck on an empty book.
        const firstWithChapters = a.find((s) => s.books?.some((b) => b.chapters?.length))
        const series0 = firstWithChapters || a[0]
        if (series0 && series0.books[0]) {
          const b = series0.books[0]
          setSeries({ series: series0.name, book: b.id })
          setActiveChapter(b.chapters[0]?.id || null)
        } else if (a.length === 0) {
          setLoadError('Server returned an empty archive.')
        }
      })
      .catch((err) => {
        if (alive) {
          console.error('Archive load failed:', err.message)
          setLoadError(`${err.message || err}`)
        }
      })
    return () => { alive = false }
  }, [])

  // Cmd+K / Ctrl+K opens the palette; Ctrl+Shift+F toggles focus — the IDE
  // muscle memory.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      }
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        setFocusMode((v) => !v)
      }
      if (e.key === 'Escape') {
        setPaletteOpen(false)
        setRewriteOpen(false)
        setFocusMode(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => { setSetting('focus', focusMode) }, [focusMode])

  // Proactive nudge (D11): when enabled, after a few quiet minutes offer to
  // have the Muse continue. Off by default — quiet, never nagging.
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

  const jumpTo = (id) => {
    setActiveChapter(id)
    setPaletteOpen(false)
  }

  const book = useMemo(
    () => (archive && series ? archive.find((s) => s.name === series.series)?.books?.find((b) => b.id === series.book) : null),
    [archive, series]
  )
  const chapter = useMemo(
    () => book?.chapters?.find((c) => c.id === activeChapter) || null,
    [book, activeChapter]
  )
  // `series/book/ch-NN` for the Muse server-side canon context.
  const activeChapterId = series && chapter ? `${series.series}/${series.book}/${chapter.id}` : null

  // --- Rewrite flow ------------------------------------------------------

  const runRewrite = async (sel, style) => {
    if (!sel || !sel.text) return
    setProposed('')
    setRewriteBusy(true)
    setRewriteOpen(true)
    try {
      const full = await api.museRewrite({
        text: sel.text,
        style,
        chapterId: activeChapterId,
        onDelta: (acc) => setProposed(acc)
      })
      setProposed(full)
    } catch (e) {
      setProposed('— Muse unavailable: ' + (e.message || 'unknown error') + ' —')
    } finally {
      setRewriteBusy(false)
    }
  }

  // Triggered when the Page reports a non-empty selection — debounced by
  // the textarea's selection events; we just stash the latest.
  const onSelection = (sel) => setSelection(sel)

  const onRewriteClick = () => {
    if (!selection || !selection.text) return
    runRewrite(selection, rewriteStyle)
  }

  const onAccept = () => {
    if (pageApi.replaceSelection && proposed) {
      pageApi.replaceSelection(proposed)
    }
    setRewriteOpen(false)
    setProposed('')
  }

  const onRetry = () => {
    if (!selection) return
    runRewrite(selection, rewriteStyle)
  }

  const onStyleChange = (s) => {
    setRewriteStyle(s)
    if (rewriteOpen && selection) runRewrite(selection, s)
  }

  const onCloseRewrite = () => {
    setRewriteOpen(false)
    setProposed('')
  }

  const commands = [
    {
      id: 'focus',
      label: focusMode ? 'Exit focus mode' : 'Enter focus mode',
      hint: 'Ctrl+Shift+F',
      run: () => setFocusMode((v) => !v)
    },
    {
      id: 'sweep',
      label: 'Canon sweep',
      hint: 'Muse',
      run: () => setSweepOpen(true)
    },
    ...(series
      ? [{
          id: 'export',
          label: 'Export EPUB',
          hint: 'Deliver',
          run: () => api.exportEpub(series.series, series.book, `${series.book}.epub`).catch(() => {})
        }]
      : []),
    {
      id: 'settings',
      label: 'Settings',
      hint: '',
      run: () => setSettingsOpen(true)
    }
  ]

  return (
    <div className="flex h-full flex-col bg-base">
      <TitleBar
        focus={focusMode}
        onToggleFocus={() => setFocusMode((v) => !v)}
        onOpenSettings={() => setSettingsOpen(true)}
      />
      <div
        className="grid min-h-0 flex-1"
        style={{
          gridTemplateColumns: focusMode
            ? '1fr'
            : railCollapsed ? '48px 1fr 320px' : '232px 1fr 320px',
          transition: 'grid-template-columns 160ms ease'
        }}
      >
        {archive && series ? (
          <>
            {!focusMode && (
              <Rail
                collapsed={railCollapsed}
                onToggle={() => setRailCollapsed((v) => !v)}
                active={activeChapter}
                onSelect={jumpTo}
                archive={archive}
              />
            )}
            <div className="relative min-h-0">
              <Page
                chapter={chapter}
                series={series}
                focus={focusMode}
                onSaved={() => {}}
                onSelection={onSelection}
                onReplaceRequested={true}
              />
              {/* Floating ✎ button — appears when the user has a non-empty selection */}
              {selection && selection.text && !rewriteOpen && (
                <button
                  onClick={onRewriteClick}
                  className="absolute right-6 top-6 z-30 flex items-center gap-1.5 rounded-md border border-gold/40 bg-panel px-3 py-1.5 text-[11px] font-medium text-gold shadow-lg shadow-black/40 hover:bg-gold/10"
                  title="Rewrite the selected text with the Muse"
                >
                  ✎ Rewrite selection
                </button>
              )}
              {nudge && !focusMode && (
                <div className="absolute bottom-5 left-1/2 z-30 flex -translate-x-1/2 items-center gap-2 rounded-full border hairline bg-panel px-3 py-1.5 text-[11px] text-mute shadow-lg shadow-black/40">
                  <span>Still going?</span>
                  <button
                    onClick={() => {
                      if (museApi.setDraft) museApi.setDraft('Continue the scene from where I left off.')
                      setNudge(false)
                    }}
                    className="rounded-full border border-gold/40 px-2 py-0.5 text-[10.5px] font-medium text-gold hover:bg-gold/10"
                  >
                    Ask the Muse
                  </button>
                  <button onClick={() => setNudge(false)} className="text-mute hover:text-ink">×</button>
                </div>
              )}
            </div>
            {!focusMode && <Muse series={series} chapter={chapter} />}
          </>
        ) : loadError ? (
          <div className="flex flex-col items-center justify-center gap-2 text-center text-mute">
            <div className="text-[12px] text-red-300">Failed to load archive</div>
            <div className="text-[10.5px] text-mute/70">{loadError}</div>
            <div className="text-[10px] text-mute/50">
              Server at <code className="text-ink">{window.location.origin}</code> didn't respond.
              Open DevTools (F12) → Network for details.
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center text-mute">
            Loading archive…
          </div>
        )}
      </div>
      {paletteOpen && archive && (
        <CommandPalette
          onClose={() => setPaletteOpen(false)}
          onJump={jumpTo}
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
          onStyleChange={onStyleChange}
          onAccept={onAccept}
          onRetry={onRetry}
          onClose={onCloseRewrite}
        />
      )}
      {sweepOpen && series && (
        <Sweep series={series} onClose={() => setSweepOpen(false)} />
      )}
      {settingsOpen && (
        <Settings
          goal={goal}
          onGoal={(v) => { setGoal(v); setSetting('goal', v === '' ? null : Number(v)) }}
          nudge={nudgeOn}
          onNudge={(v) => { setNudgeOn(v); setSetting('nudge', v) }}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  )
}

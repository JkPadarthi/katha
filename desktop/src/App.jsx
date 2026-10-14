import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import TitleBar from './components/TitleBar.jsx'
import Rail from './components/Rail.jsx'
import Editor, { editorApi } from './components/Editor.jsx'
import Muse, { museApi } from './components/Muse.jsx'
import CommandPalette from './components/CommandPalette.jsx'
import DiffOverlay from './components/DiffOverlay.jsx'
import SweepPanel from './components/SweepPanel.jsx'
import BiblePanel from './components/BiblePanel.jsx'
import SettingsPanel from './components/SettingsPanel.jsx'
import * as api from './lib/api.js'
import { getSetting, setSetting } from './lib/settings.js'
import { useMediaQuery } from './lib/useMediaQuery.js'
import { useTheme } from './lib/useTheme.js'

export default function App() {
  const { theme, choose } = useTheme()

  const [archive, setArchive] = useState(null)
  const [series, setSeries] = useState(null)
  const [activeChapter, setActiveChapter] = useState(null)
  const [railCollapsed, setRailCollapsed] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [focusMode, setFocusMode] = useState(() => getSetting('focus', false))
  const [loadError, setLoadError] = useState('')

  const [sweepOpen, setSweepOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [bibleName, setBibleName] = useState(null)   // null = closed
  const [goal, setGoal] = useState(() => getSetting('goal', '') ?? '')
  const [nudgeOn, setNudgeOn] = useState(() => getSetting('nudge', false))
  const [nudge, setNudge] = useState(false)

  // Rewrite flow
  const [selection, setSelection] = useState(null)
  const [rewriteOpen, setRewriteOpen] = useState(false)
  const [proposed, setProposed] = useState('')
  const [rewriteBusy, setRewriteBusy] = useState(false)
  const [rewriteStyle, setRewriteStyle] = useState('novel')

  // Mobile: one pane at a time — bottom tabs + horizontal swipe.
  const isMobile = useMediaQuery('(max-width: 767px)')
  const [pane, setPane] = useState(1)                 // 0=Chapters 1=Page 2=Muse
  const touchRef = useRef({ x0: 0, dx: 0, active: false })

  // Load the archive.
  useEffect(() => {
    let alive = true
    setLoadError('')
    api
      .loadArchive()
      .then((a) => {
        if (!alive) return
        setArchive(a)
        const firstWithChapters = a.find((s) => s.books?.some((b) => b.chapters?.length))
        const s0 = firstWithChapters || a[0]
        if (s0 && s0.books[0]) {
          const b = s0.books[0]
          setSeries({ series: s0.name, book: b.id })
          setActiveChapter(b.chapters[0]?.id || null)
        } else if (a.length === 0) {
          setLoadError('Server returned an empty archive.')
        }
      })
      .catch((err) => {
        if (alive) setLoadError(`${err.message || err}`)
      })
    return () => { alive = false }
  }, [])

  // Re-fetch the tree without disturbing the current selection.
  const refreshArchive = useCallback(async () => {
    try {
      setArchive(await api.loadArchive())
    } catch { /* keep the existing tree */ }
  }, [])

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
  const activeChapterId = series && chapter ? `${series.series}/${series.book}/${chapter.id}` : null

  const newChapter = async () => {
    if (!series) return
    try {
      const c = await api.createChapter(series.series, series.book, 'Untitled')
      await refreshArchive()
      setActiveChapter(c.id)
      if (isMobile) setPane(1)
    } catch { /* the archive refresh will surface any failure */ }
  }

  // --- rewrite flow ------------------------------------------------------
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

  const onSelection = (sel) => setSelection(sel)
  const onRewriteClick = () => { if (selection?.text) runRewrite(selection, rewriteStyle) }
  const onAccept = () => {
    if (editorApi.replaceSelection && proposed) editorApi.replaceSelection(proposed)
    setRewriteOpen(false)
    setProposed('')
  }
  const onRetry = () => { if (selection) runRewrite(selection, rewriteStyle) }
  const onStyleChange = (s) => {
    setRewriteStyle(s)
    if (rewriteOpen && selection) runRewrite(selection, s)
  }
  const onCloseRewrite = () => { setRewriteOpen(false); setProposed('') }

  // --- mobile swipe ------------------------------------------------------
  const onTouchStart = (e) => {
    const t = e.target
    if (t && t.closest && t.closest('textarea,input,[contenteditable]')) {
      touchRef.current.active = false
      return
    }
    const p = e.touches[0]
    touchRef.current = { x0: p.clientX, dx: 0, active: true }
  }
  const onTouchMove = (e) => {
    if (touchRef.current.active) touchRef.current.dx = e.touches[0].clientX - touchRef.current.x0
  }
  const onTouchEnd = () => {
    const { dx, active } = touchRef.current
    touchRef.current.active = false
    if (active && Math.abs(dx) > 60) {
      setPane((p) => Math.max(0, Math.min(2, p + (dx < 0 ? 1 : -1))))
    }
  }

  const pageNode = (
    <div className="relative h-full min-h-0">
      <Editor chapter={chapter} series={series} focus={focusMode} onSelection={onSelection} />
      {selection && selection.text && !rewriteOpen && (
        <button
          onClick={onRewriteClick}
          className="absolute right-6 top-6 z-30 flex items-center gap-1.5 rounded-md border border-accent/40 bg-panel px-3 py-1.5 text-[11px] font-medium text-accent shadow-lg shadow-black/40 hover:bg-accent/10"
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
            className="rounded-full border border-accent/40 px-2 py-0.5 text-[10.5px] font-medium text-accent hover:bg-accent/10"
          >
            Ask the Muse
          </button>
          <button onClick={() => setNudge(false)} className="text-mute hover:text-ink">×</button>
        </div>
      )}
    </div>
  )

  const commands = [
    {
      id: 'focus',
      label: focusMode ? 'Exit focus mode' : 'Enter focus mode',
      hint: 'Ctrl+Shift+F',
      run: () => setFocusMode((v) => !v)
    },
    { id: 'new-chapter', label: 'New chapter', hint: 'Write', run: newChapter },
    { id: 'sweep', label: 'Canon sweep', hint: 'Muse', run: () => setSweepOpen(true) },
    ...(series
      ? [{
          id: 'export',
          label: 'Export EPUB',
          hint: 'Deliver',
          run: () => api.exportEpub(series.series, series.book, `${series.book}.epub`).catch(() => {})
        }]
      : []),
    { id: 'settings', label: 'Settings', hint: '', run: () => setSettingsOpen(true) }
  ]

  return (
    <div className="flex h-full flex-col bg-base">
      <TitleBar
        focus={focusMode}
        onToggleFocus={() => setFocusMode((v) => !v)}
        onOpenSettings={() => setSettingsOpen(true)}
        theme={theme}
        onChooseTheme={choose}
      />

      {archive && series ? (
        isMobile ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="relative min-h-0 flex-1 overflow-hidden">
              <div
                className="flex h-full"
                style={{
                  transform: `translateX(-${pane * 100}%)`,
                  transition: 'transform 220ms ease',
                  touchAction: 'pan-y',
                  willChange: 'transform'
                }}
                onTouchStart={onTouchStart}
                onTouchMove={onTouchMove}
                onTouchEnd={onTouchEnd}
              >
                <div className="flex h-full w-full shrink-0 overflow-hidden">
                  <Rail
                    collapsed={false}
                    onToggle={() => setRailCollapsed((v) => !v)}
                    active={activeChapter}
                    onSelect={(id) => { jumpTo(id); setPane(1) }}
                    archive={archive}
                    onOpenBible={(name) => setBibleName(name || '')}
                    onNewChapter={newChapter}
                  />
                </div>
                <div className="flex h-full w-full shrink-0 overflow-hidden">{pageNode}</div>
                <div className="flex h-full w-full shrink-0 overflow-hidden">
                  <Muse series={series} chapter={chapter} />
                </div>
              </div>
            </div>
            <nav
              className="flex shrink-0 border-t hairline bg-panel"
              style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
            >
              {['Chapters', 'Page', 'Muse'].map((label, i) => (
                <button
                  key={label}
                  onClick={() => setPane(i)}
                  className={'flex-1 py-2.5 text-[11.5px] ' + (pane === i ? 'text-accent' : 'text-mute')}
                >
                  {label}
                </button>
              ))}
            </nav>
          </div>
        ) : (
          <div
            className="grid min-h-0 flex-1"
            style={{
              gridTemplateColumns: focusMode
                ? '1fr'
                : railCollapsed ? '48px 1fr 320px' : '232px 1fr 320px',
              transition: 'grid-template-columns 160ms ease'
            }}
          >
            {!focusMode && (
              <Rail
                collapsed={railCollapsed}
                onToggle={() => setRailCollapsed((v) => !v)}
                active={activeChapter}
                onSelect={jumpTo}
                archive={archive}
                onOpenBible={(name) => setBibleName(name || '')}
                onNewChapter={newChapter}
              />
            )}
            {pageNode}
            {!focusMode && <Muse series={series} chapter={chapter} />}
          </div>
        )
      ) : loadError ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 text-center text-mute">
          <div className="text-[12px] text-err">Failed to load archive</div>
          <div className="text-[10.5px] text-mute/70">{loadError}</div>
          <div className="text-[10px] text-mute/50">
            Server at <code className="text-ink">{window.location.origin}</code> didn't respond.
            Open DevTools (F12) → Network for details.
          </div>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center text-mute">Loading archive…</div>
      )}

      {paletteOpen && archive && (
        <CommandPalette onClose={() => setPaletteOpen(false)} onJump={jumpTo} archive={archive} commands={commands} />
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
        <SweepPanel series={series} onClose={() => setSweepOpen(false)} />
      )}
      {bibleName !== null && series && (
        <BiblePanel
          series={series}
          initial={bibleName}
          onClose={() => setBibleName(null)}
          onChanged={refreshArchive}
        />
      )}
      {settingsOpen && (
        <SettingsPanel
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

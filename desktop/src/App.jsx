import React, { useEffect, useMemo, useState } from 'react'
import TitleBar from './components/TitleBar.jsx'
import Rail from './components/Rail.jsx'
import Page, { pageApi } from './components/Page.jsx'
import Muse from './components/Muse.jsx'
import CommandPalette from './components/CommandPalette.jsx'
import DiffOverlay from './components/DiffOverlay.jsx'
import * as api from './api.js'

export default function App() {
  const [archive, setArchive] = useState(null)
  const [series, setSeries] = useState(null)
  const [activeChapter, setActiveChapter] = useState(null)
  const [railCollapsed, setRailCollapsed] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  // Rewrite flow (0.3.3)
  const [selection, setSelection] = useState(null)
  const [rewriteOpen, setRewriteOpen] = useState(false)
  const [proposed, setProposed] = useState('')
  const [rewriteBusy, setRewriteBusy] = useState(false)
  const [rewriteStyle, setRewriteStyle] = useState('novel')

  // Load the live archive from the FastAPI backend (0.2.1).
  useEffect(() => {
    let alive = true
    api
      .loadArchive()
      .then((a) => {
        if (!alive) return
        setArchive(a)
        const firstBook = a[0]
        if (firstBook && firstBook.books[0]) {
          const b = firstBook.books[0]
          setSeries({ series: firstBook.name, book: b.id })
          setActiveChapter(b.chapters[0]?.id || null)
        }
      })
      .catch((err) => {
        if (alive) console.error('Archive load failed:', err.message)
      })
    return () => { alive = false }
  }, [])

  // Cmd+K / Ctrl+K opens the palette — the IDE muscle memory.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      }
      if (e.key === 'Escape') {
        setPaletteOpen(false)
        setRewriteOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

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
        chapterId: null,
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

  return (
    <div className="flex h-full flex-col bg-base">
      <TitleBar />
      <div
        className="grid min-h-0 flex-1"
        style={{
          gridTemplateColumns: railCollapsed ? '48px 1fr 320px' : '232px 1fr 320px',
          transition: 'grid-template-columns 160ms ease'
        }}
      >
        {archive && series ? (
          <>
            <Rail
              collapsed={railCollapsed}
              onToggle={() => setRailCollapsed((v) => !v)}
              active={activeChapter}
              onSelect={jumpTo}
              archive={archive}
            />
            <div className="relative min-h-0">
              <Page
                chapter={chapter}
                series={series}
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
                  � Rewrite selection
                </button>
              )}
            </div>
            <Muse />
          </>
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
    </div>
  )
}

import React, { useEffect, useMemo, useState } from 'react'
import TitleBar from './components/TitleBar.jsx'
import Rail from './components/Rail.jsx'
import Page from './components/Page.jsx'
import Muse from './components/Muse.jsx'
import CommandPalette from './components/CommandPalette.jsx'
import * as api from './api.js'

export default function App() {
  const [archive, setArchive] = useState(null)
  const [series, setSeries] = useState(null)   // {series, book} ids of loaded book
  const [activeChapter, setActiveChapter] = useState(null)
  const [railCollapsed, setRailCollapsed] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)

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
        // Graceful degrade: nothing loaded, surface the error once.
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
      if (e.key === 'Escape') setPaletteOpen(false)
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
            <Page chapter={chapter} series={series} onSaved={() => {}} />
            <Muse />
          </>
        ) : (
          <div className="flex items-center justify-center text-mute">
            Loading archive…
          </div>
        )}
      </div>
      {paletteOpen && archive && (
        <CommandPalette onClose={() => setPaletteOpen(false)} onJump={jumpTo} />
      )}
    </div>
  )
}

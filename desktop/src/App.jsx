import React, { useEffect, useMemo, useState } from 'react'
import TitleBar from './components/TitleBar.jsx'
import Rail from './components/Rail.jsx'
import Page from './components/Page.jsx'
import Muse from './components/Muse.jsx'
import CommandPalette from './components/CommandPalette.jsx'
import { archive } from './data.js'

export default function App() {
  const [activeChapter, setActiveChapter] = useState('ch1')
  const [railCollapsed, setRailCollapsed] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)

  const book = archive[0].books[0]
  const chapter = useMemo(
    () => book.chapters.find((c) => c.id === activeChapter),
    [activeChapter, book]
  )

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
        <Rail
          collapsed={railCollapsed}
          onToggle={() => setRailCollapsed((v) => !v)}
          active={activeChapter}
          onSelect={jumpTo}
          archive={archive}
        />
        <Page chapter={chapter} />
        <Muse />
      </div>
      {paletteOpen && <CommandPalette onClose={() => setPaletteOpen(false)} onJump={jumpTo} />}
    </div>
  )
}
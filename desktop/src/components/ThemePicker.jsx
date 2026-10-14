import React, { useEffect, useRef, useState } from 'react'
import { THEMES } from '../lib/useTheme.js'

// Tiny preview swatch: the theme's background with an accent ring.
const SWATCH = {
  hermes: ['#0e0e12', '#ffbf00'],
  paper: ['#f6f1e7', '#9a5b17'],
  slate: ['#0f1419', '#5aa2f0']
}

function Swatch({ id }) {
  const [bg, accent] = SWATCH[id] || SWATCH.hermes
  return (
    <span
      className="inline-block h-3 w-3 shrink-0 rounded-full border"
      style={{ background: bg, borderColor: accent }}
    />
  )
}

// A small popover in the title bar to pick a theme.
export default function ThemePicker({ theme, onChoose }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const active = THEMES.find((t) => t.id === theme) || THEMES[0]

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-md border hairline px-2 py-0.5 text-[10.5px] text-mute hover:text-ink"
        title="Theme"
      >
        <Swatch id={theme} />
        {active.label}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-1 w-48 overflow-hidden rounded-md border hairline bg-panel shadow-2xl shadow-black/50">
          {THEMES.map((t) => (
            <button
              key={t.id}
              onClick={() => { onChoose(t.id); setOpen(false) }}
              className={
                'flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] ' +
                (t.id === theme ? 'bg-panel-2 text-ink' : 'text-mute hover:bg-panel-2/60 hover:text-ink')
              }
            >
              <Swatch id={t.id} />
              <span className="flex-1">{t.label}</span>
              <span className="text-[10px] text-mute/60">{t.hint}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

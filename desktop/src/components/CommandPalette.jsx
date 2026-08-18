import React, { useEffect, useMemo, useRef, useState } from 'react'
import { archive } from '../data.js'

// Cmd+K palette — the IDE muscle memory. Jumps to chapters now; muse
// commands and characters join the index with the backend.
export default function CommandPalette({ onClose, onJump }) {
  const [q, setQ] = useState('')
  const inputRef = useRef(null)

  useEffect(() => inputRef.current?.focus(), [])

  const items = useMemo(() => {
    const chapters = archive[0].books[0].chapters.map((c) => ({
      id: c.id,
      label: c.title,
      hint: 'chapter'
    }))
    const actions = [
      { id: 'act-new', label: 'New chapter', hint: 'action' },
      { id: 'act-rewrite', label: 'Muse · rewrite selection', hint: 'muse' },
      { id: 'act-continue', label: 'Muse · continue scene', hint: 'muse' },
      { id: 'act-canon', label: 'Muse · canon check', hint: 'muse' }
    ]
    const all = [...chapters, ...actions]
    const term = q.trim().toLowerCase()
    return term ? all.filter((i) => i.label.toLowerCase().includes(term)) : all
  }, [q])

  return (
    <div
      className="absolute inset-0 z-50 flex items-start justify-center bg-black/50 pt-[18vh]"
      onMouseDown={onClose}
    >
      <div
        onMouseDown={(e) => e.stopPropagation()}
        className="w-[520px] overflow-hidden rounded-lg border hairline bg-panel shadow-2xl shadow-black/60"
      >
        <div className="flex items-center gap-2 border-b hairline px-3">
          <span className="text-[12px] text-mute">⌘K</span>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Jump to a chapter or muse command…"
            className="w-full bg-transparent py-2.5 text-[13px] text-ink placeholder:text-mute/50 focus:outline-none"
          />
        </div>
        <ul className="max-h-[300px] overflow-y-auto p-1.5">
          {items.map((i) => (
            <li key={i.id}>
              <button
                onClick={() => (i.hint === 'chapter' ? onJump(i.id) : onClose())}
                className="flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-left text-[12.5px] hover:bg-panel-2"
              >
                <span className="text-ink">{i.label}</span>
                <span className="text-[10px] tracking-wide text-mute/60 uppercase">{i.hint}</span>
              </button>
            </li>
          ))}
          {items.length === 0 && (
            <li className="px-2.5 py-3 text-center text-[12px] text-mute">No roads lead there.</li>
          )}
        </ul>
      </div>
    </div>
  )
}
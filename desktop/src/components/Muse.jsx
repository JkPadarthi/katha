import React, { useState } from 'react'
import { museSeed } from '../data.js'

// THE MUSE — Zed-style chat panel. 0.1 proves the shape: chips, thread,
// composer, apply buttons. 0.3 wires the streaming and the models.

const CHIPS = [
  { id: 'rewrite', label: '✎ rewrite' },
  { id: 'continue', label: '➤ continue' },
  { id: 'scene', label: '✦ new scene' },
  { id: 'canon', label: '⚑ canon?' }
]

const APPLY = ['insert at cursor', 'replace selection', 'append to chapter']

export default function Muse() {
  const [messages] = useState(museSeed)
  const [draft, setDraft] = useState('')

  const send = (text) => {
    if (!text.trim()) return
    setDraft('')
    // 0.3: real streaming via SSE from the signpost. For now, the thread
    // acknowledges without pretending to think.
    setDraft('') // placeholder — composer stays honest until the Muse breathes
  }

  return (
    <aside className="flex min-h-0 flex-col border-l hairline bg-panel">
      <div className="flex items-center justify-between px-3 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gold">✦</span>
          <span className="text-[11.5px] font-medium text-ink">The Muse</span>
        </div>
        <span className="text-[10px] text-mute/60">0.3 · streaming</span>
      </div>

      {/* Quick chips — pre-written chat (D7) */}
      <div className="flex gap-1.5 overflow-x-auto px-3 pb-2">
        {CHIPS.map((c) => (
          <button
            key={c.id}
            className="shrink-0 rounded-full border hairline px-2.5 py-1 text-[11px] text-mute transition-colors hover:border-gold/50 hover:text-gold"
            title="Arrives with the Muse in 0.3"
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Thread */}
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-2">
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'flex justify-end' : ''}>
            <div
              className={
                'max-w-[92%] rounded-lg px-3 py-2 text-[12px] leading-relaxed ' +
                (m.role === 'user'
                  ? 'bg-panel-2 text-ink'
                  : 'border hairline bg-base text-mute')
              }
            >
              {m.text}
            </div>
          </div>
        ))}
        <div className="flex justify-center">
          <span className="text-[10px] text-mute/50">— apply buttons land with real responses —</span>
        </div>
      </div>

      {/* Composer */}
      <div className="shrink-0 border-t hairline p-3">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send(draft)
            }
          }}
          rows={2}
          className="w-full resize-none rounded-md border hairline bg-base px-2.5 py-2 text-[12.5px] text-ink placeholder:text-mute/50 focus:outline-none focus:ring-1 focus:ring-gold/50"
          placeholder="Tell the Muse what to write…"
        />
        {/* Apply rail — the bridge from chat to page (D7) */}
        <div className="mt-2 flex items-center justify-between">
          <div className="flex gap-1.5">
            {APPLY.map((a) => (
              <button
                key={a}
                className="rounded border hairline px-2 py-1 text-[10px] text-mute/70"
                title="0.3 — wires the Muse's words into the page"
              >
                {a}
              </button>
            ))}
          </div>
          <button
            onClick={() => send(draft)}
            className="rounded-md bg-gold px-3 py-1 text-[11px] font-semibold text-base hover:brightness-110"
          >
            Send
          </button>
        </div>
      </div>
    </aside>
  )
}
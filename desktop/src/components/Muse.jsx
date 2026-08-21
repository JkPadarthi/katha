import React, { useEffect, useRef, useState } from 'react'
import * as api from '../api.js'

// THE MUSE — Zed-style chat panel. 0.3 wires the streaming chat via the
// FastAPI Muse proxy (server/app/muse.py). The thread lives in component
// state; persistent per-chapter history ships in 0.3.4.

const CHIPS = [
  { id: 'rewrite',  label: '✎ rewrite' },
  { id: 'continue', label: '➤ continue' },
  { id: 'scene',    label: '✦ new scene' },
  { id: 'canon',    label: '⚑ canon?' }
]

// Quick prompts — what fills the composer when a chip is clicked.
const CHIP_PROMPTS = {
  rewrite:  'Rewrite my last sentence as proper novel English.',
  continue: 'Continue the scene from where I left off.',
  scene:    'Write a new scene that follows the current chapter.',
  canon:    'Is the last thing I wrote consistent with the bible?'
}

export default function Muse() {
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [streaming, setStreaming] = useState('')
  const [error, setError] = useState('')
  const abortRef = useRef(null)
  const threadRef = useRef(null)

  // Autoscroll the thread as the assistant streams.
  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight
    }
  }, [messages, streaming])

  const send = async (text, chip) => {
    if (!text.trim() || busy) return
    setError('')
    const userMsg = { role: 'user', text }
    setMessages((m) => [...m, userMsg])
    setDraft('')
    setBusy(true)
    setStreaming('')

    // Build the messages payload for the server (just role+content).
    const payloadMessages = [
      ...messages.map((m) => ({ role: m.role, content: m.text })),
      { role: 'user', content: text }
    ]

    const ac = new AbortController()
    abortRef.current = ac
    try {
      const full = await api.museChat({
        messages: payloadMessages,
        chapterId: null,
        chip: chip || null,
        onDelta: (acc) => setStreaming(acc),
        signal: ac.signal
      })
      setMessages((m) => [...m, { role: 'assistant', text: full }])
      setStreaming('')
    } catch (e) {
      if (e.name !== 'AbortError') {
        setError(e.message || 'Muse unavailable')
        setMessages((m) => [...m, { role: 'assistant', text: '— offline —' }])
      }
    } finally {
      setBusy(false)
      abortRef.current = null
    }
  }

  const stop = () => {
    abortRef.current?.abort()
    // Snapshot whatever streamed in so far as a partial assistant turn.
    if (streaming) {
      setMessages((m) => [...m, { role: 'assistant', text: streaming + '…' }])
    }
    setStreaming('')
    setBusy(false)
  }

  const onChip = (chipId) => {
    setDraft(CHIP_PROMPTS[chipId] || '')
  }

  return (
    <aside className="flex min-h-0 flex-col border-l hairline bg-panel">
      <div className="flex items-center justify-between px-3 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-gold">✦</span>
          <span className="text-[11.5px] font-medium text-ink">The Muse</span>
        </div>
        <span className="text-[10px] text-mute/60">
          {busy ? (
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-gold" />
              streaming
            </span>
          ) : (
            '0.3 · live'
          )}
        </span>
      </div>

      {/* Quick chips — pre-written chat (D7) */}
      <div className="flex gap-1.5 overflow-x-auto px-3 pb-2">
        {CHIPS.map((c) => (
          <button
            key={c.id}
            disabled={busy}
            onClick={() => onChip(c.id)}
            className="shrink-0 rounded-full border hairline px-2.5 py-1 text-[11px] text-mute transition-colors hover:border-gold/50 hover:text-gold disabled:opacity-50"
            title={`Pre-fill the composer with: ${CHIP_PROMPTS[c.id]}`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Thread */}
      <div ref={threadRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-2">
        {messages.length === 0 && !streaming && (
          <div className="flex h-full items-center justify-center text-[11px] text-mute/50">
            Tell the Muse what to write.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'flex justify-end' : ''}>
            <div
              className={
                'max-w-[92%] rounded-lg px-3 py-2 text-[12px] leading-relaxed whitespace-pre-wrap ' +
                (m.role === 'user'
                  ? 'bg-panel-2 text-ink'
                  : 'border hairline bg-base text-mute')
              }
            >
              {m.text}
            </div>
          </div>
        ))}
        {/* Live streaming bubble — appears during a Muse turn */}
        {(streaming || busy) && (
          <div className="flex justify-start">
            <div className="max-w-[92%] rounded-lg border hairline bg-base px-3 py-2 text-[12px] leading-relaxed whitespace-pre-wrap text-mute">
              {streaming || (
                <span className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-gold" />
                  thinking
                </span>
              )}
              {busy && streaming && (
                <span className="ml-0.5 inline-block h-3 w-1 animate-pulse bg-gold/70 align-middle" />
              )}
            </div>
          </div>
        )}
        {error && (
          <div className="rounded-md border border-red-500/30 bg-red-500/10 px-2.5 py-1.5 text-[10.5px] text-red-300">
            {error}
          </div>
        )}
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
          disabled={busy}
          className="w-full resize-none rounded-md border hairline bg-base px-2.5 py-2 text-[12.5px] text-ink placeholder:text-mute/50 focus:outline-none focus:ring-1 focus:ring-gold/50 disabled:opacity-60"
          placeholder="Tell the Muse what to write…"
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-[9.5px] text-mute/50">
            Enter to send · Shift+Enter newline
          </span>
          {busy ? (
            <button
              onClick={stop}
              className="rounded-md border border-red-500/40 px-3 py-1 text-[11px] font-semibold text-red-300 hover:bg-red-500/10"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={() => send(draft)}
              disabled={!draft.trim()}
              className="rounded-md bg-gold px-3 py-1 text-[11px] font-semibold text-base hover:brightness-110 disabled:opacity-40"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </aside>
  )
}

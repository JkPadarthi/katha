import React, { useEffect, useRef, useState } from 'react'
import * as api from '../lib/api.js'
import { editorApi } from './Editor.jsx'

// Imperative bridge so App can pre-fill the composer (proactive nudge).
export const museApi = { setDraft: null }

// THE MUSE — streaming chat. The server is agentic: given a chapter id, it can
// fetch the story files itself (see server/app/muse.py). The thread lives in
// component state.

const CHIPS = [
  { id: 'rewrite',  label: '✎ rewrite' },
  { id: 'continue', label: '➤ continue' },
  { id: 'scene',    label: '✦ new scene' },
  { id: 'canon',    label: '⚑ canon?' }
]

const CHIP_PROMPTS = {
  rewrite:  'Rewrite my last sentence as proper novel English.',
  continue: 'Continue the scene from where I left off.',
  scene:    'Write a new scene that follows the current chapter.',
  canon:    'Is the last thing I wrote consistent with the bible?'
}

const APPLY = ['insert at cursor', 'replace selection', 'append to chapter']

function latestAssistant(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'assistant' && messages[i].text) return messages[i].text
  }
  return ''
}

export default function Muse({ series, chapter }) {
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [streaming, setStreaming] = useState('')
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const abortRef = useRef(null)
  const threadRef = useRef(null)

  // `series/book/ch-NN` — tells the server which story to read (canon context
  // + the agentic tools). Null when nothing is open.
  const chapterId = series && chapter ? `${series.series}/${series.book}/${chapter.id}` : null

  useEffect(() => {
    museApi.setDraft = (t) => setDraft(t)
    return () => { museApi.setDraft = null }
  }, [])

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight
  }, [messages, streaming])

  const send = async (text, chip) => {
    if (!text.trim() || busy) return
    setError('')
    setStatus('')
    setMessages((m) => [...m, { role: 'user', text }])
    setDraft('')
    setBusy(true)
    setStreaming('')

    const payloadMessages = [
      ...messages.map((m) => ({ role: m.role, content: m.text })),
      { role: 'user', content: text }
    ]

    const ac = new AbortController()
    abortRef.current = ac
    try {
      const full = await api.museChat({
        messages: payloadMessages,
        chapterId,
        chip: chip || null,
        onDelta: (acc) => setStreaming(acc),
        onStatus: (s) => setStatus(s),
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
      setStatus('')
      abortRef.current = null
    }
  }

  const stop = () => {
    abortRef.current?.abort()
    if (streaming) setMessages((m) => [...m, { role: 'assistant', text: streaming + '…' }])
    setStreaming('')
    setStatus('')
    setBusy(false)
  }

  const applyAvailable = (mode) =>
    mode === 'insert' ? !!editorApi.insertAtCursor
      : mode === 'replace' ? !!editorApi.replaceSelection
      : !!editorApi.appendToChapter

  const applyTo = (mode, text) => {
    if (!text || busy) return
    if (mode === 'insert' && editorApi.insertAtCursor) editorApi.insertAtCursor(text)
    if (mode === 'replace' && editorApi.replaceSelection) editorApi.replaceSelection(text)
    if (mode === 'append' && editorApi.appendToChapter) editorApi.appendToChapter(text)
  }

  const latest = latestAssistant(messages) || streaming

  return (
    <aside className="flex min-h-0 flex-col border-l hairline bg-panel">
      <div className="flex items-center justify-between px-3 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-accent">✦</span>
          <span className="text-[11.5px] font-medium text-ink">The Muse</span>
        </div>
        <span className="text-[10px] text-mute/60">
          {busy ? (
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
              working
            </span>
          ) : 'live'}
        </span>
      </div>

      {/* Quick chips (D7) */}
      <div className="flex gap-1.5 overflow-x-auto px-3 pb-2">
        {CHIPS.map((c) => (
          <button
            key={c.id}
            disabled={busy}
            onClick={() => setDraft(CHIP_PROMPTS[c.id] || '')}
            className="shrink-0 rounded-full border hairline px-2.5 py-1 text-[11px] text-mute transition-colors hover:border-accent/50 hover:text-accent disabled:opacity-50"
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
                'max-w-[92%] whitespace-pre-wrap rounded-lg px-3 py-2 text-[12px] leading-relaxed ' +
                (m.role === 'user' ? 'bg-panel-2 text-ink' : 'border hairline bg-base text-mute')
              }
            >
              {m.text}
            </div>
          </div>
        ))}

        {(streaming || busy) && (
          <div className="flex justify-start">
            <div className="max-w-[92%] whitespace-pre-wrap rounded-lg border hairline bg-base px-3 py-2 text-[12px] leading-relaxed text-mute">
              {streaming || (
                <span className="flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                  {status || 'thinking'}
                </span>
              )}
              {busy && streaming && (
                <span className="ml-0.5 inline-block h-3 w-1 animate-pulse bg-accent/70 align-middle" />
              )}
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-md border border-err/30 bg-err/10 px-2.5 py-1.5 text-[10.5px] text-err">
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
          className="w-full resize-none rounded-md border hairline bg-base px-2.5 py-2 text-[12.5px] text-ink placeholder:text-mute/50 focus:outline-none focus:ring-1 focus:ring-accent/50 disabled:opacity-60"
          placeholder="Tell the Muse what to write…"
        />
        <div className="mt-2 flex items-center justify-between">
          <div className="flex gap-1.5">
            {APPLY.map((a) => {
              const mode = a === 'insert at cursor' ? 'insert'
                : a === 'replace selection' ? 'replace'
                : 'append'
              const disabled = !latest || !applyAvailable(mode)
              return (
                <button
                  key={a}
                  disabled={disabled}
                  onClick={() => applyTo(mode, latest)}
                  className="rounded border hairline px-2 py-1 text-[10px] text-mute/70 transition-colors hover:border-accent/50 hover:text-accent disabled:opacity-40 disabled:hover:border-hairline disabled:hover:text-mute/70"
                  title={
                    !latest ? 'Wait for the Muse to finish a reply'
                      : !applyAvailable(mode) ? `Apply "${mode}" is not available right now`
                      : `Apply the latest Muse reply: ${mode}`
                  }
                >
                  {a}
                </button>
              )
            })}
          </div>
          {busy ? (
            <button
              onClick={stop}
              className="rounded-md border border-err/40 px-3 py-1 text-[11px] font-semibold text-err hover:bg-err/10"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={() => send(draft)}
              disabled={!draft.trim()}
              className="rounded-md bg-accent px-3 py-1 text-[11px] font-semibold text-onaccent hover:brightness-110 disabled:opacity-40"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </aside>
  )
}

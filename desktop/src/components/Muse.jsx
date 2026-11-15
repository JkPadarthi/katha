import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import * as api from '../lib/api.js'
import { editorApi } from './Editor.jsx'
import { fileLabel } from './ProposalReview.jsx'
import { Button } from '../ui/Button.jsx'

// Imperative bridge so the rest of the app can drive the composer:
//   setDraft(text)                       pre-fill (proactive nudge)
//   ask(text, {chip, chapterId}) → ids   send a message (inline edit, Fix buttons);
//                                        resolves with the proposal ids the turn staged
//   refreshPending()                     re-read what is waiting for review
export const museApi = { setDraft: null, ask: null, refreshPending: null }

// THE MUSE — streaming chat. The server is agentic: given a chapter id, it can
// read the story files itself and stage edits to chapters and bible files (see
// server/app/muse.py). Nothing it does is saved until the author accepts it.

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
    if (messages[i].role === 'assistant' && messages[i].text && !messages[i].local) return messages[i].text
  }
  return ''
}

const k = (n) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : `${n}`)

// The @-mention under the caret, if any: {start, query}.
function mentionAt(text, caret) {
  const upto = text.slice(0, caret)
  const m = upto.match(/(^|[\s(])@([\w./-]*)$/)
  if (!m) return null
  return { start: caret - m[2].length - 1, query: m[2].toLowerCase() }
}

export default function Muse({ series, chapter, book, onReview }) {
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState([])     // staged changes waiting in this book
  const [busy, setBusy] = useState(false)
  const [streaming, setStreaming] = useState('')
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [usage, setUsage] = useState(null)       // last reply {input, output}
  const [spent, setSpent] = useState({ input: 0, output: 0 })   // this session
  const [mention, setMention] = useState(null)   // {start, query}
  const [pick, setPick] = useState(0)
  const abortRef = useRef(null)
  const threadRef = useRef(null)
  const composerRef = useRef(null)
  const queuedRef = useRef(null)                 // an ask() waiting for its chapter to open
  const caretRef = useRef(null)                  // where the caret goes after a mention pick

  // `series/book/ch-NN` — tells the server which story to read (canon context
  // + the agentic tools). Null when nothing is open.
  const chapterId = series && chapter ? `${series.series}/${series.book}/${chapter.id}` : null

  // Everything the author can @-mention in this book.
  const files = useMemo(() => {
    if (!book) return []
    const ch = (book.chapters || []).map((c) => ({
      token: c.id, label: c.title ? `${c.id} · ${c.title}` : c.id, kind: 'chapter'
    }))
    const bi = (book.bible || []).map((b) => ({
      token: b.id.replace(/\.md$/, ''), label: `bible · ${b.id}`, kind: 'bible'
    }))
    return [...ch, ...bi]
  }, [book])
  const matches = useMemo(() => {
    if (!mention) return []
    const q = mention.query
    return files.filter((f) => !q || f.token.toLowerCase().includes(q) || f.label.toLowerCase().includes(q)).slice(0, 8)
  }, [mention, files])

  const refreshPending = async () => {
    if (!series) { setPending([]); return }
    try {
      const r = await api.listProposals()
      const mine = (r.proposals || []).filter((p) => p.series === series.series && p.book === series.book)
      // the open chapter first, then the rest in the order the server gives (newest first)
      mine.sort((a, b) => (b.chapter === chapter?.id) - (a.chapter === chapter?.id))
      setPending(mine)
    } catch { /* best-effort: never block the thread on this */ }
  }

  useEffect(() => {
    museApi.setDraft = (t) => { setDraft(t); composerRef.current?.focus() }
    museApi.refreshPending = refreshPending
    return () => { museApi.setDraft = null; museApi.refreshPending = null }
  })

  // Restore the persisted conversation for the open chapter.
  useEffect(() => {
    // A live stream belongs to the chapter it started in — stop it on switch.
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
    let alive = true
    setBusy(false)
    setMessages([])
    setError('')
    setStatus('')
    setStreaming('')
    if (!chapterId) return
    // A change may have been staged while this tab was closed, or in another tab. The
    // SSE marker only ever covers a turn we watched live, so ask the server what is
    // still pending — otherwise a waiting change is invisible (2.9.3).
    refreshPending()
    api
      .museThread(chapterId)
      .then((r) => {
        if (!alive) return
        setMessages((r.messages || []).map((m) => ({ role: m.role, text: m.text })))
      })
      .catch(() => { /* history is best-effort */ })
      .finally(() => {
        // An ask() that was waiting for this chapter to open (a Fix button) goes now.
        const q = queuedRef.current
        if (alive && q && q.chapterId === chapterId) {
          queuedRef.current = null
          send(q.text, q.chip).then(q.resolve, q.reject)
        }
      })
    return () => { alive = false }
  }, [chapterId])

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight
  }, [messages, streaming])

  const send = async (text, chip) => {
    if (!text.trim() || busy) return []
    setError('')
    setStatus('')
    setMention(null)
    setMessages((m) => [...m, { role: 'user', text }])
    setDraft('')
    setBusy(true)
    setStreaming('')

    const payloadMessages = [
      ...messages
        .filter((m) => !m.local)
        .map((m) => ({ role: m.role, content: m.text })),
      { role: 'user', content: text }
    ]

    const staged = []
    const ac = new AbortController()
    abortRef.current = ac
    try {
      const full = await api.museChat({
        messages: payloadMessages,
        chapterId,
        chip: chip || null,
        onDelta: (acc) => setStreaming(acc),
        onStatus: (s) => setStatus(s),
        // The server staged a change for review. Nothing was written: this only
        // refreshes the "review" list (2.9, D45).
        onProposal: (id) => { staged.push(id) },
        onUsage: (u) => {
          setUsage(u)
          setSpent((s) => ({ input: s.input + (u.input || 0), output: s.output + (u.output || 0) }))
        },
        signal: ac.signal
      })
      setMessages((m) => [...m, { role: 'assistant', text: full }])
      setStreaming('')
    } catch (e) {
      if (e.name !== 'AbortError') {
        setError(e.message || 'Muse unavailable')
        // Local-only placeholder: shown, but never sent back as a model turn.
        setMessages((m) => [...m, { role: 'assistant', text: '— offline —', local: true }])
      }
    } finally {
      setBusy(false)
      setStatus('')
      abortRef.current = null
    }
    if (staged.length) await refreshPending()
    return staged
  }

  // ask(): send from outside the panel. If it is about another chapter, that chapter
  // opens first (the caller switches it) and the message goes once its thread loads.
  useEffect(() => {
    museApi.ask = (text, { chip, chapterId: target } = {}) => {
      if (target && target !== chapterId) {
        return new Promise((resolve, reject) => {
          queuedRef.current = { text, chip, chapterId: target, resolve, reject }
        })
      }
      return send(text, chip)
    }
    return () => { museApi.ask = null }
  })

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
  const totalHunks = pending.reduce((n, p) => n + (p.hunk_count || 0), 0)

  // --- composer + @-mentions ------------------------------------------------
  const onDraftChange = (e) => {
    setDraft(e.target.value)
    const m = mentionAt(e.target.value, e.target.selectionStart)
    setMention(m)
    setPick(0)
  }

  const takeMention = (f) => {
    if (!mention || !f) return
    const ta = composerRef.current
    const caret = ta ? ta.selectionStart : draft.length
    const next = draft.slice(0, mention.start) + '@' + f.token + ' ' + draft.slice(caret)
    caretRef.current = mention.start + f.token.length + 2
    setDraft(next)
    setMention(null)
  }

  // Place the caret after a picked mention *before* the next keystroke is handled — a
  // requestAnimationFrame here lost the race to fast typing and spliced the words.
  useLayoutEffect(() => {
    const c = caretRef.current
    const ta = composerRef.current
    if (c == null || !ta) return
    caretRef.current = null
    ta.focus()
    ta.setSelectionRange(c, c)
  }, [draft])

  const onComposerKey = (e) => {
    if (mention && matches.length) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setPick((i) => (i + 1) % matches.length); return }
      if (e.key === 'ArrowUp') { e.preventDefault(); setPick((i) => (i - 1 + matches.length) % matches.length); return }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); takeMention(matches[pick]); return }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setMention(null); return }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send(draft)
    }
  }

  return (
    <aside className="flex min-h-0 flex-col border-l hairline bg-panel">
      <div className="flex items-center justify-between px-3 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-accent">✦</span>
          <span className="text-[11.5px] font-medium text-ink">The Muse</span>
        </div>
        <span className="flex items-center gap-2 text-[10px] text-mute/60">
          {usage && !busy && (
            <span
              title={`Last reply: ${usage.input} tokens in, ${usage.output} out.\nThis session: ${spent.input} in, ${spent.output} out.`}
            >
              {k(usage.input)} in · {k(usage.output)} out
            </span>
          )}
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

      {/* Staged changes waiting for review, across every file in this book (2.9 → 3.1).
          The Muse cannot save: this is the author's decision, and nothing has changed
          until Accept. */}
      {pending.length > 0 && (
        <div className="mx-3 mb-2 rounded-md border border-accent/40 bg-accent/5 px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-accent">◆</span>
            <span className="min-w-0 flex-1 text-[11px] text-ink">
              {totalHunks
                ? `${totalHunks} ${totalHunks === 1 ? 'change' : 'changes'}`
                : 'Changes'}
              {pending.length > 1 ? ` in ${pending.length} files` : ''} — none applied.
            </span>
            <Button variant="accent" size="sm" onClick={() => onReview && onReview(pending[0].id)}>
              Review
            </Button>
          </div>
          <ul className="mt-1.5 space-y-0.5">
            {pending.map((p) => (
              <li key={p.id} className="flex items-center gap-2 text-[10.5px]">
                <button
                  onClick={() => onReview && onReview(p.id)}
                  className="min-w-0 flex-1 truncate text-left text-mute hover:text-ink"
                  title={p.stale ? 'This file changed since the Muse read it' : `Review ${p.path}`}
                >
                  {fileLabel(p.path)}
                  {typeof p.hunk_count === 'number' ? ` · ${p.hunk_count}` : ''}
                  {p.stale ? ' · ⚠ out of date' : ''}
                </button>
                <button
                  onClick={async () => {
                    try { await api.discardProposal(p.id) } catch { /* gone is gone */ }
                    refreshPending()
                  }}
                  className="text-mute/60 hover:text-err"
                  title="Discard this change"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Thread */}
      <div ref={threadRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-2">
        {messages.length === 0 && !streaming && (
          <div className="flex h-full flex-col items-center justify-center gap-1 text-center text-[11px] text-mute/50">
            <span>Tell the Muse what to write — or what to change.</span>
            <span className="text-[10px] text-mute/40">@ to point at a chapter or bible file</span>
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
      <div className="relative shrink-0 border-t hairline p-3">
        {mention && matches.length > 0 && (
          <ul className="absolute bottom-full left-3 right-3 z-20 mb-1 max-h-56 overflow-y-auto rounded-md border hairline bg-panel py-1 shadow-lg shadow-black/40">
            {matches.map((f, i) => (
              <li key={f.token}>
                <button
                  onMouseDown={(e) => { e.preventDefault(); takeMention(f) }}
                  className={
                    'flex w-full items-center gap-2 px-2.5 py-1 text-left text-[11px] ' +
                    (i === pick ? 'bg-panel-2 text-ink' : 'text-mute')
                  }
                >
                  <span className="text-accent/80">@</span>
                  <span className="truncate">{f.label}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <textarea
          ref={composerRef}
          value={draft}
          onChange={onDraftChange}
          onKeyDown={onComposerKey}
          onBlur={() => setTimeout(() => setMention(null), 120)}
          rows={2}
          disabled={busy}
          className="w-full resize-none rounded-md border hairline bg-base px-2.5 py-2 text-[12.5px] text-ink placeholder:text-mute/50 focus:outline-none focus:ring-1 focus:ring-accent/50 disabled:opacity-60"
          placeholder="Tell the Muse what to write… (@ to attach a file)"
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

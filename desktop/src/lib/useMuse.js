import { useEffect, useMemo, useRef, useState } from 'react'
import * as api from './api.js'

// THE MUSE's state, apart from any one surface (4.0). The composer in the dock, the
// reply card above it and the conversation drawer all read this one hook, so moving
// between them never loses a reply in flight.
//
// The server is agentic: given a chapter id it reads the story files itself and stages
// edits to chapters and bible files (server/app/muse.py). Nothing it does is saved until
// the author accepts it.

// Imperative bridge so the rest of the app can drive the Muse:
//   setDraft(text)                       pre-fill the composer (proactive nudge)
//   focus()                              put the caret in the composer (Ctrl/⌘+I)
//   ask(text, {chip, chapterId}) → ids   send (inline edit, Fix buttons); resolves with
//                                        the proposal ids the turn staged
//   refreshPending()                     re-read what is waiting for review
export const museApi = { setDraft: null, focus: null, ask: null, refreshPending: null }

export const CHIP_PROMPTS = {
  continue: 'Continue the scene from where I left off.',
  rewrite:  'Rewrite my last sentence as proper novel English.',
  scene:    'Write a new scene that follows the current chapter.',
  canon:    'Is the last thing I wrote consistent with the bible?'
}

export function latestAssistant(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'assistant' && messages[i].text && !messages[i].local) return messages[i].text
  }
  return ''
}

export function useMuse({ series, chapter, book }) {
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState([])     // staged changes waiting in this book
  const [busy, setBusy] = useState(false)
  const [streaming, setStreaming] = useState('')
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [usage, setUsage] = useState(null)       // last reply {input, output}
  const [spent, setSpent] = useState({ input: 0, output: 0 })   // this session
  const [fresh, setFresh] = useState(false)      // a reply arrived that the author hasn't dismissed
  const abortRef = useRef(null)
  const queuedRef = useRef(null)                 // an ask() waiting for its chapter to open

  // `series/book/ch-NN` — tells the server which story to read. Null when nothing is open.
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
    setFresh(false)
    if (!chapterId) return
    // A change may have been staged while this tab was closed, or in another tab: ask
    // the server what is still pending (2.9.3).
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

  const send = async (text, chip) => {
    if (!text.trim() || busy) return []
    setError('')
    setStatus('')
    setFresh(true)
    setMessages((m) => [...m, { role: 'user', text }])
    setDraft('')
    setBusy(true)
    setStreaming('')

    const payloadMessages = [
      ...messages.filter((m) => !m.local).map((m) => ({ role: m.role, content: m.text })),
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
        // The server staged a change for review. Nothing was written (2.9, D45).
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

  const stop = () => {
    abortRef.current?.abort()
    if (streaming) setMessages((m) => [...m, { role: 'assistant', text: streaming + '…' }])
    setStreaming('')
    setStatus('')
    setBusy(false)
  }

  // ask(): send from outside the composer. If it is about another chapter, that chapter
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
    museApi.refreshPending = refreshPending
    museApi.setDraft = (t) => { setDraft(t); museApi.focus?.() }
    return () => { museApi.ask = null; museApi.refreshPending = null; museApi.setDraft = null }
  })

  const discard = async (id) => {
    try { await api.discardProposal(id) } catch { /* gone is gone */ }
    refreshPending()
  }

  return {
    chapterId, files, messages, draft, setDraft, pending, refreshPending, discard,
    busy, streaming, status, error, usage, spent, fresh, dismiss: () => setFresh(false),
    latest: latestAssistant(messages) || streaming,
    send, stop
  }
}

export const kTokens = (n) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : `${n}`)

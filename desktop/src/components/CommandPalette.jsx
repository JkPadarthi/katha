import React, { useEffect, useMemo, useRef, useState } from 'react'
import * as api from '../lib/api.js'
import Overlay from '../ui/Overlay.jsx'

// Cmd+K / Ctrl+K palette — the IDE muscle memory. Empty query lists commands +
// the book's chapters; typing runs an FTS5 search across chapters and bible.
const MOD_LABEL =
  (typeof navigator !== 'undefined' && /Mac|iPhone|iPad/i.test(navigator.platform))
    ? '⌘K'
    : 'Ctrl K'

// Render the backend's `<mark>…</mark>` snippet as highlighted spans.
function Snippet({ html }) {
  const nodes = useMemo(() => {
    const parts = html.split(/<mark>|<\/mark>/)
    return parts.map((p, i) =>
      i % 2 === 1
        ? <mark key={i} className="rounded-[2px] bg-accent/20 text-accent">{p}</mark>
        : <span key={i}>{p}</span>
    )
  }, [html])
  return <>{nodes}</>
}

export default function CommandPalette({ onClose, onJump, onOpenHit, archive, series, commands = [] }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState(null)   // null = idle, [] = none, [...] = hits
  const inputRef = useRef(null)

  useEffect(() => inputRef.current?.focus(), [])

  // Debounced FTS search. `alive` lives in the effect scope so a slow older
  // request can never overwrite the results of a newer query.
  useEffect(() => {
    const term = q.trim()
    if (!term) { setHits(null); return }
    setHits(null)
    let alive = true
    const t = setTimeout(() => {
      api.search(term)
        .then((r) => { if (alive) setHits(r.hits || []) })
        .catch(() => { if (alive) setHits([]) })
    }, 180)
    return () => { alive = false; clearTimeout(t) }
  }, [q])

  const chapters = useMemo(() => {
    const s = archive?.find((x) => x.name === series?.series)
    const b = s?.books?.find((x) => x.id === series?.book)
    return b?.chapters || []
  }, [archive, series])
  const showChapters = !q.trim()
  // Typing filters the commands too (3.1): "sweep" finds Canon sweep, "hist" finds
  // Revision history — the palette is how an IDE reaches what has no button.
  const matched = useMemo(() => {
    const term = q.trim().toLowerCase()
    if (!term) return commands
    return commands.filter((c) => c.label.toLowerCase().includes(term))
  }, [q, commands])
  const runFirst = () => {
    if (matched.length) { matched[0].run(); onClose(); return }
    const h = Array.isArray(hits) && hits[0]
    if (h) {
      if (onOpenHit) onOpenHit(h)
      else if (h.kind === 'chapter') onJump(h.doc_id)
      onClose()
    }
  }

  return (
    <Overlay onClose={onClose} width={560} padTop="18vh" z={50}>
      <div className="flex items-center gap-2 border-b hairline px-3">
        <span className="text-[13px] text-mute">{MOD_LABEL}</span>
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); runFirst() } }}
          placeholder="Search chapters and canon…"
          className="w-full bg-transparent py-2.5 text-[15px] text-ink placeholder:text-mute/50 focus:outline-none"
        />
      </div>

      <ul className="max-h-[340px] overflow-y-auto p-1.5">
        {matched.map((cmd) => (
          <li key={cmd.id}>
            <button
              onClick={() => { cmd.run(); onClose() }}
              className="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-[14px] hover:bg-panel-2"
            >
              <span className="text-ink">{cmd.label}</span>
              {cmd.hint && <span className="text-[12px] text-mute/60">{cmd.hint}</span>}
            </button>
          </li>
        ))}

        {showChapters && chapters.map((c) => (
          <li key={c.id}>
            <button
              onClick={() => { onJump(c.id); onClose() }}
              className="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-[14px] hover:bg-panel-2"
            >
              <span className="text-ink">{c.title}</span>
              <span className="text-[12px] text-mute/60">chapter</span>
            </button>
          </li>
        ))}

        {!showChapters && hits === null && (
          <li className="px-2.5 py-3 text-center text-[14px] text-mute">Searching…</li>
        )}

        {!showChapters && Array.isArray(hits) && hits.map((h) => (
          <li key={`${h.kind}-${h.book_id}-${h.doc_id}`}>
            <button
              onClick={() => {
                if (onOpenHit) onOpenHit(h)
                else if (h.kind === 'chapter') onJump(h.doc_id)
                onClose()
              }}
              className="flex w-full flex-col gap-0.5 rounded-lg px-2.5 py-1.5 text-left hover:bg-panel-2"
            >
              <span className="flex w-full items-center justify-between gap-2">
                <span className="truncate text-[14px] text-ink">{h.title}</span>
                <span className="shrink-0 text-[12px] text-mute/60">
                  {h.kind === 'chapter' ? 'chapter' : 'bible'}
                </span>
              </span>
              {h.snippet && (
                <span className="line-clamp-2 text-[13px] leading-snug text-mute">
                  <Snippet html={h.snippet} />
                </span>
              )}
            </button>
          </li>
        ))}

        {!showChapters && Array.isArray(hits) && hits.length === 0 && !matched.length && (
          <li className="px-2.5 py-3 text-center text-[14px] text-mute">No roads lead there.</li>
        )}
      </ul>
    </Overlay>
  )
}

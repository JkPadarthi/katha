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

export default function CommandPalette({ onClose, onJump, archive, commands = [] }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState(null)   // null = idle, [] = none, [...] = hits
  const inputRef = useRef(null)

  useEffect(() => inputRef.current?.focus(), [])

  // Debounced FTS search.
  useEffect(() => {
    const term = q.trim()
    if (!term) { setHits(null); return }
    setHits(null)
    const t = setTimeout(() => {
      let alive = true
      api.search(term)
        .then((r) => alive && setHits(r.hits || []))
        .catch(() => alive && setHits([]))
      return () => { alive = false }
    }, 180)
    return () => clearTimeout(t)
  }, [q])

  const chapters = useMemo(
    () => (archive && archive[0]?.books?.[0]?.chapters) || [],
    [archive]
  )
  const showChapters = !q.trim()

  return (
    <Overlay onClose={onClose} width={560} padTop="18vh" z={50}>
      <div className="flex items-center gap-2 border-b hairline px-3">
        <span className="text-[11px] text-mute">{MOD_LABEL}</span>
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search chapters and canon…"
          className="w-full bg-transparent py-2.5 text-[13px] text-ink placeholder:text-mute/50 focus:outline-none"
        />
      </div>

      <ul className="max-h-[340px] overflow-y-auto p-1.5">
        {showChapters && commands.map((cmd) => (
          <li key={cmd.id}>
            <button
              onClick={() => { cmd.run(); onClose() }}
              className="flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-left text-[12.5px] hover:bg-panel-2"
            >
              <span className="text-ink">{cmd.label}</span>
              {cmd.hint && <span className="text-[10px] uppercase tracking-wide text-mute/60">{cmd.hint}</span>}
            </button>
          </li>
        ))}

        {showChapters && chapters.map((c) => (
          <li key={c.id}>
            <button
              onClick={() => { onJump(c.id); onClose() }}
              className="flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-left text-[12.5px] hover:bg-panel-2"
            >
              <span className="text-ink">{c.title}</span>
              <span className="text-[10px] uppercase tracking-wide text-mute/60">chapter</span>
            </button>
          </li>
        ))}

        {!showChapters && hits === null && (
          <li className="px-2.5 py-3 text-center text-[12px] text-mute">Searching…</li>
        )}

        {!showChapters && Array.isArray(hits) && hits.map((h) => (
          <li key={`${h.kind}-${h.book_id}-${h.doc_id}`}>
            <button
              onClick={() => { if (h.kind === 'chapter') { onJump(h.doc_id); onClose() } }}
              className={
                'flex w-full flex-col gap-0.5 rounded-md px-2.5 py-1.5 text-left ' +
                (h.kind === 'chapter' ? 'hover:bg-panel-2' : 'opacity-80')
              }
            >
              <span className="flex w-full items-center justify-between gap-2">
                <span className="truncate text-[12.5px] text-ink">{h.title}</span>
                <span className="shrink-0 text-[10px] uppercase tracking-wide text-mute/60">
                  {h.kind === 'chapter' ? 'chapter' : 'bible'}
                </span>
              </span>
              {h.snippet && (
                <span className="line-clamp-2 text-[11px] leading-snug text-mute">
                  <Snippet html={h.snippet} />
                </span>
              )}
            </button>
          </li>
        ))}

        {!showChapters && Array.isArray(hits) && hits.length === 0 && (
          <li className="px-2.5 py-3 text-center text-[12px] text-mute">No roads lead there.</li>
        )}
      </ul>
    </Overlay>
  )
}

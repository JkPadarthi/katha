import React, { useEffect, useMemo, useRef, useState } from 'react'
import * as api from '../api.js'

// Cmd+K / Ctrl+K palette — the IDE muscle memory. Now searches the real
// archive via FTS5 (0.2.2): type to query chapters + bible, jump on select.
const MOD_LABEL =
  (typeof navigator !== 'undefined' && /Mac|iPhone|iPad/i.test(navigator.platform))
    ? '⌘K'
    : 'Ctrl K'

// Turn the backend's `<mark>…</mark>` snippet into highlighted spans.
function Snippet({ html }) {
  const nodes = useMemo(() => {
    const parts = html.split(/<mark>|<\/mark>/)
    return parts.map((p, i) =>
      i % 2 === 1 ? (
        <mark key={i} className="rounded-[2px] bg-gold/20 text-gold">{p}</mark>
      ) : (
        <span key={i}>{p}</span>
      )
    )
  }, [html])
  return <>{nodes}</>
}

export default function CommandPalette({ onClose, onJump, archive }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState(null)   // null = idle, [] = no hits, [...] = hits
  const inputRef = useRef(null)

  useEffect(() => inputRef.current?.focus(), [])

  // Debounced FTS5 search against the archive.
  useEffect(() => {
    const term = q.trim()
    if (!term) {
      setHits(null)
      return
    }
    setHits(null)
    const t = setTimeout(() => {
      let alive = true
      api
        .search(term)
        .then((r) => alive && setHits(r.hits || []))
        .catch(() => alive && setHits([]))
      return () => { alive = false }
    }, 180)
    return () => clearTimeout(t)
  }, [q])

  // Empty query → list the chapters of the loaded book (fast jump, no FTS).
  const chapters = useMemo(
    () => (archive && archive[0]?.books?.[0]?.chapters) || [],
    [archive]
  )

  const showChapters = !q.trim()

  return (
    <div
      className="absolute inset-0 z-50 flex items-start justify-center bg-black/50 pt-[18vh]"
      onMouseDown={onClose}
    >
      <div
        onMouseDown={(e) => e.stopPropagation()}
        className="w-[540px] overflow-hidden rounded-lg border hairline bg-panel shadow-2xl shadow-black/60"
      >
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
          {showChapters &&
            chapters.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => { onJump(c.id); onClose() }}
                  className="flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-left text-[12.5px] hover:bg-panel-2"
                >
                  <span className="text-ink">{c.title}</span>
                  <span className="text-[10px] tracking-wide text-mute/60 uppercase">chapter</span>
                </button>
              </li>
            ))}

          {!showChapters && hits === null && (
            <li className="px-2.5 py-3 text-center text-[12px] text-mute">Searching…</li>
          )}

          {!showChapters && Array.isArray(hits) && hits.map((h) => (
            <li key={`${h.kind}-${h.book_id}-${h.doc_id}`}>
              <button
                onClick={() => {
                  if (h.kind === 'chapter') { onJump(h.doc_id); onClose() }
                  // bible hits: display-only until the bible reader lands (0.3)
                }}
                className={
                  'flex w-full flex-col gap-0.5 rounded-md px-2.5 py-1.5 text-left ' +
                  (h.kind === 'chapter' ? 'hover:bg-panel-2' : 'opacity-80')
                }
              >
                <span className="flex w-full items-center justify-between gap-2">
                  <span className="truncate text-[12.5px] text-ink">{h.title}</span>
                  <span className="shrink-0 text-[10px] tracking-wide text-mute/60 uppercase">
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
      </div>
    </div>
  )
}

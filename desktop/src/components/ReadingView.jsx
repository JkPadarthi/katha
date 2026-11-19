import React, { useMemo, useState } from 'react'
import { proseBlocks } from '../lib/prose.js'

// READING MODE — the page as book. Renders the chapter's markdown as prose
// (headings, blockquotes, paragraphs), lets the reader select a passage to
// annotate, and lists the chapter's margin notes underneath. Annotations are
// persisted by the parent (Editor) to a ch-NN.notes.md sidecar on the Pi.

function Blocks({ text }) {
  // Paragraph breaks follow the manuscript's own convention (D50) — see lib/prose.js.
  const blocks = useMemo(() => proseBlocks(text), [text])
  return blocks.map((b, i) => {
    const t = b.trim()
    if (!t) return null
    if (t.startsWith('## ')) {
      return <h3 key={i} className="mb-3 mt-8 font-serif text-[22px] font-semibold text-ink">{t.slice(3)}</h3>
    }
    if (t.startsWith('# ')) {
      return <h2 key={i} className="mb-3 mt-8 font-serif text-[26px] font-semibold text-ink">{t.slice(2)}</h2>
    }
    if (t.startsWith('>')) {
      return (
        <blockquote key={i} className="my-5 border-l-2 border-accent/40 pl-4 italic text-mute">
          {t.replace(/^>\s?/gm, '')}
        </blockquote>
      )
    }
    return <p key={i} className="mb-[0.85em] whitespace-pre-wrap">{t}</p>
  })
}

export default function ReadingView({ body, notes, onAddNote, onNoteBody, onDeleteNote, onCommitNotes }) {
  const [sel, setSel] = useState(null) // { text, x, y }

  const onMouseUp = () => {
    const s = typeof window !== 'undefined' ? window.getSelection() : null
    const text = s ? s.toString().trim() : ''
    if (!text || !s.rangeCount) {
      setSel(null)
      return
    }
    const rect = s.getRangeAt(0).getBoundingClientRect()
    setSel({ text, x: rect.left + rect.width / 2, y: rect.top })
  }

  const add = () => {
    if (!sel) return
    onAddNote(sel.text)
    setSel(null)
    if (typeof window !== 'undefined' && window.getSelection) window.getSelection().removeAllRanges()
  }

  return (
    <div>
      <div onMouseUp={onMouseUp} className="prose-page text-ink">
        <Blocks text={body} />
      </div>

      {sel && (
        <button
          onMouseDown={(e) => e.preventDefault()}
          onClick={add}
          style={{ position: 'fixed', left: sel.x, top: Math.max(8, sel.y - 44), transform: 'translateX(-50%)' }}
          className="float z-50 h-9 rounded-lg px-3 text-[13px] font-medium text-accent hover:bg-accent/10"
        >
          Add margin note
        </button>
      )}

      {notes.length > 0 && (
        <div className="mt-12 border-t hairline pt-6">
          <div className="mb-3 text-[13px] font-semibold text-ink">
            Margin notes
          </div>
          <ul className="space-y-3">
            {notes.map((n, i) => (
              <li key={i} className="rounded-xl border hairline bg-panel px-4 py-3">
                {n.quote && (
                  <div className="mb-2 whitespace-pre-wrap border-l-2 border-accent/40 pl-3 font-serif text-[14px] italic text-mute">
                    {n.quote}
                  </div>
                )}
                <textarea
                  value={n.body}
                  onChange={(e) => onNoteBody(i, e.target.value)}
                  onBlur={onCommitNotes}
                  rows={2}
                  placeholder="Your note…"
                  className="w-full resize-none rounded-lg border hairline bg-base px-3 py-2 text-[14px] text-ink placeholder:text-mute/60 focus:outline-none focus:ring-2 focus:ring-accent/20"
                />
                <button
                  onClick={() => onDeleteNote(i)}
                  className="mt-1 h-8 rounded-lg px-2 text-[12.5px] text-mute hover:bg-err/10 hover:text-err"
                >
                  delete
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

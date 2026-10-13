import React, { useMemo, useState } from 'react'

// READING MODE — the page as book. Renders the chapter's markdown as prose
// (headings, blockquotes, paragraphs), lets the reader select a passage to
// annotate, and lists the chapter's margin notes underneath. Annotations are
// persisted by the parent (Page) to a ch-NN.notes.md sidecar on the Pi.

function Blocks({ text }) {
  const blocks = useMemo(() => (text || '').split(/\n\s*\n/), [text])
  return blocks.map((b, i) => {
    const t = b.trim()
    if (!t) return null
    if (t.startsWith('## ')) {
      return <h3 key={i} className="mb-2 mt-6 font-serif text-[19px] font-semibold text-ink">{t.slice(3)}</h3>
    }
    if (t.startsWith('# ')) {
      return <h2 key={i} className="mb-2 mt-6 font-serif text-[22px] font-semibold text-ink">{t.slice(2)}</h2>
    }
    if (t.startsWith('>')) {
      return (
        <blockquote key={i} className="my-3 border-l-2 border-gold/40 pl-3 font-serif text-[16px] italic text-mute">
          {t.replace(/^>\s?/gm, '')}
        </blockquote>
      )
    }
    return <p key={i} className="mb-3 whitespace-pre-wrap">{t}</p>
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
      <div onMouseUp={onMouseUp} className="font-serif text-[17px] leading-[1.95] text-ink/95">
        <Blocks text={body} />
      </div>

      {sel && (
        <button
          onMouseDown={(e) => e.preventDefault()}
          onClick={add}
          style={{ position: 'fixed', left: sel.x, top: Math.max(8, sel.y - 36), transform: 'translateX(-50%)' }}
          className="z-50 rounded-md border border-gold/40 bg-panel px-2.5 py-1 text-[10.5px] font-medium text-gold shadow-lg shadow-black/40 hover:bg-gold/10"
        >
          ✎ Add note
        </button>
      )}

      {notes.length > 0 && (
        <div className="mt-10 border-t hairline pt-4">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-mute/60">
            Margin notes
          </div>
          <ul className="space-y-2">
            {notes.map((n, i) => (
              <li key={i} className="rounded-md border hairline bg-panel-2/40 px-3 py-2">
                {n.quote && (
                  <div className="mb-1 border-l-2 border-gold/40 pl-2 font-serif text-[12px] italic text-mute whitespace-pre-wrap">
                    {n.quote}
                  </div>
                )}
                <textarea
                  value={n.body}
                  onChange={(e) => onNoteBody(i, e.target.value)}
                  onBlur={onCommitNotes}
                  rows={2}
                  placeholder="Your note…"
                  className="w-full resize-none rounded border hairline bg-base px-2 py-1 text-[12.5px] text-ink placeholder:text-mute/50 focus:outline-none focus:ring-1 focus:ring-gold/50"
                />
                <button
                  onClick={() => onDeleteNote(i)}
                  className="mt-1 text-[10px] text-mute hover:text-red-300"
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

import React, { useEffect, useMemo, useState } from 'react'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Button } from '../ui/Button.jsx'

// Per-hunk review of a change the Muse staged (3.0, D48) — to a chapter or a bible
// file (3.1, D54).
//
// The all-or-nothing version of this asked one question with thirty answers in it: the
// Muse moved ~138 words in 30 places and the author got a single Accept. Here every place
// that changed is its own decision — the way an AI IDE reviews an edit — and nothing is
// written until Accept. Hunks left out stay pending on the server, so a partial accept is
// not a way to lose the rest of the change.
//
// The pane walks the *base* text (what the file says now) and renders, in reading
// order: untouched prose, and one block per hunk with its old and new prose. What the
// author reads is what the file will say where they have ticked.
//
// `inline` renders it over the page itself instead of in a modal — the chapter you are
// writing, with the Muse's changes marked in place (3.1, D60). `siblings` are the other
// files with changes waiting in this book, so a change that spans files (a rename
// everywhere) is reviewed file by file without leaving the pane.

const BLANK = (s) => (s || '').replace(/[ \t]+/g, ' ')

// A hunk that is only whitespace (a paragraph break the Muse moved) is a real difference,
// but it has no prose to show — say so in words instead of rendering nothing.
function shape(h) {
  const before = BLANK(h.before)
  const after = BLANK(h.after)
  if (!before.trim() && after.trim()) return 'added a paragraph break'
  if (before.trim() && !after.trim()) return 'removed a paragraph break'
  return ''
}

const typingIn = (e) => {
  const t = e.target
  return t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.isContentEditable)
}

export function fileLabel(path) {
  if (!path) return ''
  if (path.startsWith('chapters/')) return path.slice(9).replace(/\.md$/, '')
  return path.replace(/^bible\//, 'bible · ')
}

export default function ProposalReview({
  id,
  kind = 'chapter',
  path = '',
  original = '',
  hunks = [],
  stale = false,
  dropped = [],
  siblings = [],     // [{id, path, hunk_count, stale}] every pending file in this book
  inline = false,
  busy,
  onAccept,          // (ids | null) => void   null = every hunk
  onAcceptAllFiles,  // () => void  accept every non-stale file, whole
  onDiscard,
  onSwitch,          // (id) => void
  onClose
}) {
  const [skipped, setSkipped] = useState(() => new Set())
  const [at, setAt] = useState(0)

  // A different file is a different set of decisions.
  useEffect(() => { setSkipped(new Set()); setAt(0) }, [id])

  const accepted = useMemo(
    () => hunks.filter((h) => !skipped.has(h.id)),
    [hunks, skipped]
  )
  const pending = hunks.length - accepted.length
  const accept = () => onAccept(accepted.length === hunks.length ? null : accepted.map((h) => h.id))

  const move = (dir) =>
    setAt((n) => (hunks.length ? (n + dir + hunks.length) % hunks.length : 0))

  useEffect(() => {
    const el = document.getElementById(`hunk-${hunks[at]?.id}`)
    if (el && at) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [at, hunks])

  useEffect(() => {
    const onKey = (e) => {
      if (typingIn(e)) return
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        if (!busy && !stale && accepted.length) accept()
      }
      if (e.key === 'n' || e.key === 'N') move(1)
      if (e.key === 'p' || e.key === 'P') move(-1)
      if (inline && e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [accepted, hunks, onAccept, busy, stale, inline])

  // The text between hunks is the author's, untouched: walk the base by offsets.
  const segments = useMemo(() => {
    const out = []
    let pos = 0
    for (const h of hunks) {
      if (h.base_start > pos) out.push({ kind: 'same', text: original.slice(pos, h.base_start) })
      out.push({ kind: 'hunk', hunk: h })
      pos = h.base_end
    }
    if (pos < original.length) out.push({ kind: 'same', text: original.slice(pos) })
    return out
  }, [original, hunks])

  const resultWords = useMemo(() => {
    // what the file will say, in words, if the ticked hunks are accepted
    let n = 0
    for (const s of segments) {
      const text = s.kind === 'same' ? s.text : (skipped.has(s.hunk.id) ? s.hunk.before : s.hunk.after)
      n += text.split(/\s+/).filter(Boolean).length
    }
    return n
  }, [segments, skipped])

  const others = siblings.filter((s) => s.id !== id)
  const what = kind === 'bible' ? 'this bible file' : 'your chapter'
  const prose = kind === 'bible' ? 'font-sans text-[13px] leading-[1.7]' : 'font-serif text-[14.5px] leading-[1.85]'

  const header = (
    <OverlayHeader
      icon="◆"
      title={`The Muse's changes · ${fileLabel(path) || 'revision'}`}
      onClose={onClose}
      extra={
        busy ? (
          <span className="flex items-center gap-1.5 text-[10.5px] text-mute">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
            saving
          </span>
        ) : (
          <span className="text-[10.5px] text-mute">
            {hunks.length} {hunks.length === 1 ? 'change' : 'changes'}
            {pending ? ` · ${pending} set aside` : ' · all included'}
          </span>
        )
      }
    />
  )

  const body = (
    <div className="flex h-full flex-col">
      {header}

      {siblings.length > 1 && (
        <div className="flex shrink-0 items-center gap-1.5 overflow-x-auto border-b hairline px-4 py-2">
          <span className="shrink-0 text-[9.5px] uppercase tracking-wider text-mute/70">
            {siblings.length} files
          </span>
          {siblings.map((s) => (
            <button
              key={s.id}
              onClick={() => s.id !== id && onSwitch && onSwitch(s.id)}
              disabled={busy}
              className={
                'shrink-0 rounded-full border px-2.5 py-0.5 text-[10.5px] transition-colors ' +
                (s.id === id
                  ? 'border-accent/60 bg-accent/10 text-accent'
                  : 'hairline text-mute hover:text-ink')
              }
              title={s.stale ? 'This file changed since the Muse read it' : s.path}
            >
              {fileLabel(s.path)}
              {typeof s.hunk_count === 'number' ? ` · ${s.hunk_count}` : ''}
              {s.stale ? ' ⚠' : ''}
            </button>
          ))}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {stale && (
          <div className="mb-3 rounded-md border border-err/40 bg-err/5 px-3 py-2">
            <div className="text-[11px] text-ink">
              <span className="text-err">This change is based on an earlier version of {what}.</span>
              {' '}It has been saved since the Muse read it, and this change was a full rewrite
              that can't be replayed onto the new text — so accepting is closed. Ask the Muse
              to revise the current text, or discard this change.
            </div>
          </div>
        )}
        {dropped.length > 0 && (
          <div className="mb-3 rounded-md border border-warn/40 bg-warn/5 px-3 py-2 text-[11px] text-ink">
            <span className="text-warn">
              {dropped.length} of the Muse's edits no longer apply
            </span>{' '}
            — you changed that text yourself, and your version wins:
            <ul className="mt-1 list-disc pl-4 text-[10.5px] text-mute">
              {dropped.slice(0, 5).map((d, i) => (
                <li key={i} className="truncate">“{(d.old_text || '').slice(0, 90)}”</li>
              ))}
            </ul>
          </div>
        )}
        <div className="mb-3 flex items-center justify-between gap-3 rounded-md border border-accent/30 bg-accent/5 px-3 py-2">
          <div className="text-[11px] text-ink">
            Nothing is applied until you accept. Unticked changes stay here, waiting.
          </div>
          <div className="flex shrink-0 gap-1.5">
            <Button size="sm" onClick={() => setSkipped(new Set())} disabled={busy || !pending}>
              Include all
            </Button>
            <Button size="sm" onClick={() => setSkipped(new Set(hunks.map((h) => h.id)))}
                    disabled={busy || pending === hunks.length}>
              Set all aside
            </Button>
          </div>
        </div>

        <div className={inline ? 'mx-auto max-w-[72ch]' : ''}>
          {segments.map((s, i) => {
            if (s.kind === 'same') {
              return (
                <span key={`t${i}`} className={'whitespace-pre-wrap text-mute/80 ' + prose}>
                  {s.text}
                </span>
              )
            }
            const h = s.hunk
            const out = skipped.has(h.id)
            const note = shape(h)
            const n = hunks.findIndex((x) => x.id === h.id)
            return (
              <div
                key={`h${h.id}`}
                id={`hunk-${h.id}`}
                className={
                  'my-2 rounded-md border px-3 py-2 transition-colors ' +
                  (out ? 'border-line bg-panel-2/60 opacity-70' : 'border-accent/40 bg-panel-2') +
                  (n === at ? ' ring-1 ring-accent/40' : '')
                }
              >
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="text-[9.5px] uppercase tracking-wider text-mute/70">
                    change {n + 1} of {hunks.length}
                  </span>
                  {note && <span className="text-[9.5px] text-mute/70">· {note}</span>}
                  <span className="min-w-0 flex-1" />
                  <button
                    onClick={() => setSkipped((prev) => {
                      const next = new Set(prev)
                      if (next.has(h.id)) next.delete(h.id)
                      else next.add(h.id)
                      return next
                    })}
                    disabled={busy}
                    className={
                      'rounded-sm px-2 py-0.5 text-[10.5px] transition-colors ' +
                      (out ? 'text-mute hover:text-ink' : 'bg-accent/20 text-accent')
                    }
                  >
                    {out ? '✗ set aside' : '✓ included'}
                  </button>
                </div>
                {h.before.trim() && (
                  <div className={'whitespace-pre-wrap text-err/80 line-through ' + prose}>
                    {h.before}
                  </div>
                )}
                {h.after.trim() && (
                  <div className={'mt-0.5 whitespace-pre-wrap text-ink ' + prose}>
                    {h.after}
                  </div>
                )}
              </div>
            )
          })}
          {!hunks.length && (
            <div className="text-[11.5px] text-mute/60">Nothing left to review in this file.</div>
          )}
        </div>
      </div>

      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t hairline px-4 py-2.5">
        <span className="text-[10px] text-mute/60">
          n / p to move · Ctrl/⌘+Enter to accept · Esc to close
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] text-mute/60">{resultWords} words if you accept</span>
          <Button
            size="md"
            onClick={async () => {
              try { await onDiscard() } catch { /* gone is gone */ }
            }}
            disabled={busy}
          >
            Discard
          </Button>
          {others.length > 0 && onAcceptAllFiles && (
            <Button size="md" onClick={onAcceptAllFiles} disabled={busy}
                    title="Accept every change in every file that is waiting">
              Accept all {siblings.length} files
            </Button>
          )}
          <Button
            variant="accent"
            onClick={accept}
            disabled={busy || !accepted.length || stale}
          >
            {accepted.length === hunks.length
              ? `Accept all ${hunks.length}`
              : `Accept ${accepted.length} of ${hunks.length}`}
          </Button>
        </div>
      </div>
    </div>
  )

  if (inline) {
    return <div className="absolute inset-0 z-20 bg-base">{body}</div>
  }
  return (
    <Overlay onClose={onClose} width={880} padTop="6vh" height="86vh">
      {body}
    </Overlay>
  )
}

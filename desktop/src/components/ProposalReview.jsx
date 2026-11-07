import React, { useEffect, useMemo, useState } from 'react'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Button } from '../ui/Button.jsx'

// Per-hunk review of a whole-chapter revision (3.0, D48).
//
// The all-or-nothing version of this asked one question with thirty answers in it: the
// Muse moved ~138 words in 30 places and the author got a single Accept. Here every place
// that changed is its own decision — the way an AI IDE reviews an edit — and nothing is
// written until Accept. Hunks left out stay pending on the server, so a partial accept is
// not a way to lose the rest of the revision.
//
// The pane walks the *base* text (what the chapter says now) and renders, in reading
// order: untouched prose, and one block per hunk with its old and new prose. What the
// author reads is what the chapter will say where they have ticked.

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

export default function ProposalReview({
  id,
  original = '',
  hunks = [],
  stale = false,
  busy,
  onAccept,          // (ids | null) => void   null = every hunk
  onDiscard,
  onClose
}) {
  const [skipped, setSkipped] = useState(() => new Set())
  const [at, setAt] = useState(0)

  const accepted = useMemo(
    () => hunks.filter((h) => !skipped.has(h.id)),
    [hunks, skipped]
  )
  const pending = hunks.length - accepted.length

  // The overlay is a fixed-height card; with `flex h-full flex-col` around the children the
  // middle can shrink and scroll (without it the body just grows and gets clipped — the
  // review could not be scrolled at all).
  const move = (dir) =>
    setAt((n) => (hunks.length ? (n + dir + hunks.length) % hunks.length : 0))

  useEffect(() => {
    if (!at) return
    const el = document.getElementById(`hunk-${hunks[at]?.id}`)
    if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [at, hunks])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        onAccept(accepted.length === hunks.length ? null : accepted.map((h) => h.id))
      }
      if (e.key === 'n' || e.key === 'N') move(1)
      if (e.key === 'p' || e.key === 'P') move(-1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [accepted, hunks, onAccept])

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
    // what the chapter will say, in words, if these hunks are accepted
    let n = 0
    for (const s of segments) n += (s.kind === 'same' ? s.text : s.hunk.after).split(/\s+/).filter(Boolean).length
    return n
  }, [segments])

  return (
    <Overlay onClose={onClose} width={880} padTop="6vh" height="86vh">
      {/* The house pattern for a fixed-height overlay: a full-height flex column, so the
          middle pane can shrink and scroll while the header and footer stay put. */}
      <div className="flex h-full flex-col">
      <OverlayHeader
        icon="◆"
        title="The Muse's revision"
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

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {stale && (
          <div className="mb-3 rounded-md border border-err/40 bg-err/5 px-3 py-2">
            <div className="text-[11px] text-ink">
              <span className="text-err">This revision is based on an earlier version of your chapter.</span>
              {' '}You have saved since the Muse read it, and accepting would overwrite prose it
              never saw — so accepting is closed. Ask the Muse to revise the current chapter
              (it reads what is on the page now), or discard this revision.
            </div>
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

        {segments.map((s, i) => {
          if (s.kind === 'same') {
            return (
              <span key={`t${i}`} className="whitespace-pre-wrap font-serif text-[14.5px] leading-[1.55] text-mute/80">
                {s.text}
              </span>
            )
          }
          const h = s.hunk
          const out = skipped.has(h.id)
          const note = shape(h)
          return (
            <div
              key={`h${h.id}`}
              id={`hunk-${h.id}`}
              className={
                'my-2 rounded-md border px-3 py-2 transition-colors ' +
                (out ? 'border-line bg-panel-2/60 opacity-70' : 'border-accent/40 bg-panel-2')
              }
            >
              <div className="mb-1.5 flex items-center gap-2">
                <span className="text-[9.5px] uppercase tracking-wider text-mute/70">
                  change {hunks.findIndex((x) => x.id === h.id) + 1} of {hunks.length}
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
                <div className="font-serif text-[14.5px] leading-[1.55] text-err/80 line-through">
                  {h.before}
                </div>
              )}
              {h.after.trim() && (
                <div className="mt-0.5 font-serif text-[14.5px] leading-[1.55] text-ink">
                  {h.after}
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="flex items-center justify-between border-t hairline px-4 py-2.5">
        <span className="text-[10px] text-mute/60">
          n / p to move between changes · Ctrl/⌘+Enter to accept · Esc to close
        </span>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-mute/60">{resultWords} words if you accept</span>
          <Button
            size="md"
            onClick={async () => {
              try { await onDiscard() } catch { /* gone is gone */ }
              onClose()
            }}
            disabled={busy}
          >
            Discard the revision
          </Button>
          <Button
            variant="accent"
            onClick={() => onAccept(accepted.length === hunks.length ? null : accepted.map((h) => h.id))}
            disabled={busy || !accepted.length || stale}
          >
            {accepted.length === hunks.length
              ? `Accept all ${hunks.length}`
              : `Accept ${accepted.length} of ${hunks.length}`}
          </Button>
        </div>
      </div>
      </div>
    </Overlay>
  )
}

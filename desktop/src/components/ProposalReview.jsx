import React, { useEffect, useMemo, useState } from 'react'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Button } from '../ui/Button.jsx'
import Icon from '../ui/Icon.jsx'

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
// writing, with the Muse's changes marked in place (3.1, D60; on a phone too since 4.0). `siblings` are the other
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

// The whitespace a hunk's two sides share at either edge (a paragraph break the word
// diff swept in) belongs to the text around it, not to the change: render it once,
// outside the marks, so a one-word change never draws across three lines.
export function edges(before, after) {
  let lead = 0
  while (lead < before.length && lead < after.length && before[lead] === after[lead] && /\s/.test(before[lead])) lead++
  let trail = 0
  while (trail < before.length - lead && trail < after.length - lead &&
         before[before.length - 1 - trail] === after[after.length - 1 - trail] &&
         /\s/.test(before[before.length - 1 - trail])) trail++
  return {
    lead: before.slice(0, lead),
    before: before.slice(lead, before.length - trail),
    after: after.slice(lead, after.length - trail),
    trail: before.slice(before.length - trail)
  }
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
  const prose = kind === 'bible' ? 'font-sans text-[15px] leading-[1.75]' : 'prose-page'

  const toggle = (hid) => setSkipped((prev) => {
    const next = new Set(prev)
    if (next.has(hid)) next.delete(hid)
    else next.add(hid)
    return next
  })

  // 4.0 (D63): the changes are marked IN the prose, where they will land — struck
  // through what goes, highlighted what comes — each with its own include toggle,
  // instead of a stack of before/after cards.
  const text = (
    <div className={'whitespace-pre-wrap text-ink ' + prose}>
      {segments.map((s, i) => {
        if (s.kind === 'same') {
          // A chapter file starts with its `# Title` line: show it as the title it is.
          const m = i === 0 && kind === 'chapter' && s.text.match(/^# (.*)\n?/)
          if (m) {
            return (
              <React.Fragment key={`t${i}`}>
                <span className="block text-[30px] font-semibold leading-[1.15] tracking-[-0.01em] max-md:text-[25px]">{m[1]}</span>
                <span>{s.text.slice(m[0].length)}</span>
              </React.Fragment>
            )
          }
          return <span key={`t${i}`}>{s.text}</span>
        }
        const h = s.hunk
        const out = skipped.has(h.id)
        const note = shape(h)
        const n = hunks.findIndex((x) => x.id === h.id)
        const e = edges(h.before, h.after)
        return (
          <span key={`h${h.id}`}>
            {e.lead}
            <span
              id={`hunk-${h.id}`}
              className={'rounded-md box-decoration-clone ' + (n === at ? 'bg-accent/8' : '')}
            >
            {out ? (
              <span className="decoration-mute/60 underline decoration-dashed underline-offset-4">{e.before}</span>
            ) : (
              <>
                {e.before.trim() && <span className="text-del line-through decoration-1">{e.before}</span>}
                {e.before.trim() && e.after.trim() && ' '}
                {e.after.trim() && <span className="rounded-[3px] bg-add-bg px-0.5 text-add box-decoration-clone">{e.after}</span>}
                {!e.after.trim() && e.after}
              </>
            )}
            <button
              onClick={() => { toggle(h.id); setAt(n) }}
              disabled={busy}
              aria-pressed={!out}
              aria-label={`Change ${n + 1} of ${hunks.length}${note ? ' (' + note + ')' : ''}: ${out ? 'set aside' : 'included'}`}
              title={out ? 'Set aside — click to include this change' : 'Included — click to set it aside'}
              className={
                'mx-1 inline-flex h-6 -translate-y-px items-center gap-1 rounded-full px-2 align-middle font-sans text-[11.5px] font-medium leading-none transition-colors ' +
                (out ? 'border hairline text-mute hover:text-ink' : 'bg-accent text-onaccent hover:brightness-110')
              }
            >
              {out ? <>{n + 1} · set aside</> : <><Icon name="check" size={12} stroke={2.4} />{n + 1}</>}
              {note && <span className="font-normal opacity-80">· {note}</span>}
            </button>
            </span>
            {e.trail}
          </span>
        )
      })}
      {!hunks.length && (
        <div className="font-sans text-[14px] text-mute">Nothing left to review in this file.</div>
      )}
    </div>
  )

  const notices = (
    <>
      {stale && (
        <div className="mb-4 rounded-xl border border-err/40 bg-err/5 px-4 py-3 text-[13.5px] leading-relaxed text-ink">
          <span className="font-medium text-err">This change is based on an earlier version of {what}.</span>{' '}
          It has been saved since the Muse read it, and this change was a full rewrite that
          can't be replayed onto the new text — so accepting is closed. Ask the Muse to revise
          the current text, or discard this change.
        </div>
      )}
      {dropped.length > 0 && (
        <div className="mb-4 rounded-xl border border-warn/40 bg-warn/5 px-4 py-3 text-[13.5px] text-ink">
          <span className="font-medium text-warn">
            {dropped.length} of the Muse's edits no longer apply
          </span>{' '}
          — you changed that text yourself, and your version wins:
          <ul className="mt-1 list-disc pl-5 text-[13px] text-mute">
            {dropped.slice(0, 5).map((d, i) => (
              <li key={i} className="truncate">“{(d.old_text || '').slice(0, 90)}”</li>
            ))}
          </ul>
        </div>
      )}
    </>
  )

  const files = siblings.length > 1 && (
    <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
      {siblings.map((s) => (
        <button
          key={s.id}
          onClick={() => s.id !== id && onSwitch && onSwitch(s.id)}
          disabled={busy}
          aria-current={s.id === id ? 'true' : undefined}
          className={
            'h-8 shrink-0 rounded-full px-3 text-[12.5px] transition-colors ' +
            (s.id === id ? 'bg-accent/12 font-medium text-accent' : 'border hairline text-mute hover:text-ink')
          }
          title={s.stale ? 'This file changed since the Muse read it' : s.path}
        >
          {fileLabel(s.path)}
          {typeof s.hunk_count === 'number' ? ` · ${s.hunk_count}` : ''}
          {s.stale ? ' · out of date' : ''}
        </button>
      ))}
    </div>
  )

  const summary = (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-mute">
      <span className="font-medium text-ink">
        {hunks.length} {hunks.length === 1 ? 'change' : 'changes'} in {fileLabel(path) || 'this file'}
      </span>
      <span>{pending ? `${pending} set aside` : 'all included'}</span>
      <span className="flex-1" />
      <button onClick={() => setSkipped(new Set())} disabled={busy || !pending}
              className="h-8 rounded-lg px-2 hover:bg-panel-2 hover:text-ink disabled:opacity-40">
        Include all
      </button>
      <button onClick={() => setSkipped(new Set(hunks.map((h) => h.id)))} disabled={busy || pending === hunks.length}
              className="h-8 rounded-lg px-2 hover:bg-panel-2 hover:text-ink disabled:opacity-40">
        Set all aside
      </button>
    </div>
  )

  const keys = (
    <span className="text-[12.5px] text-mute max-md:hidden">
      <kbd className="font-sans">n</kbd> / <kbd className="font-sans">p</kbd> move · <kbd className="font-sans">⌘↵</kbd> accept · Esc close
    </span>
  )

  const actions = (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <span className="mr-auto text-[12.5px] text-mute">{resultWords} words after</span>
      <Button size="md" onClick={async () => { try { await onDiscard() } catch { /* gone is gone */ } }} disabled={busy}>
        Discard
      </Button>
      {others.length > 0 && onAcceptAllFiles && (
        <Button size="md" onClick={onAcceptAllFiles} disabled={busy} title="Accept every change in every file that is waiting">
          Accept all {siblings.length} files
        </Button>
      )}
      <Button variant="primary" size="md" onClick={accept} disabled={busy || !accepted.length || stale}>
        {busy ? 'Saving…' : accepted.length === hunks.length ? `Accept all ${hunks.length}` : `Accept ${accepted.length} of ${hunks.length}`}
      </Button>
    </div>
  )

  if (inline) {
    // Over the page itself: the chapter you are writing, with the changes marked where
    // they land, and the decision in the dock's place at the bottom.
    return (
      <div className="absolute inset-0 z-30 flex flex-col bg-base" role="region" aria-label="Review the Muse's changes">
        <div className="measure shrink-0 space-y-2 pb-2 pt-6 max-md:pt-3">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-accent" aria-hidden="true" />
            <span className="text-[13px] text-mute">The Muse's changes — nothing is saved until you accept</span>
            <span className="flex-1" />
            {keys}
            <button onClick={onClose} aria-label="Close the review" title="Close (Esc) — the changes keep waiting"
                    className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-mute hover:bg-panel-2 hover:text-ink">
              <Icon name="x" />
            </button>
          </div>
          {files}
          {summary}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="measure pb-48 pt-4">
            {notices}
            {text}
          </div>
        </div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center bg-gradient-to-t from-base from-40% to-transparent px-3 pb-[max(12px,env(safe-area-inset-bottom))] pt-10 md:px-6 md:pb-6">
          <div className="dock-width float pointer-events-auto w-full rounded-2xl px-4 py-3">{actions}</div>
        </div>
      </div>
    )
  }
  return (
    <Overlay onClose={onClose} width={860} padTop="6vh" height="86vh" label="Review the Muse's changes">
      <div className="flex h-full min-h-0 flex-col">
        <OverlayHeader
          title={`The Muse's changes · ${fileLabel(path) || 'revision'}`}
          onClose={onClose}
          extra={keys}
        />
        <div className="shrink-0 space-y-2 border-b hairline px-5 py-3">
          {files}
          {summary}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 md:px-10">
          {notices}
          {text}
        </div>
        <div className="shrink-0 border-t hairline px-5 py-3" style={{ paddingBottom: 'max(12px, env(safe-area-inset-bottom))' }}>
          {actions}
        </div>
      </div>
    </Overlay>
  )
}

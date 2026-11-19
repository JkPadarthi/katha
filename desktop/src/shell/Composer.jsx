import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import Icon from '../ui/Icon.jsx'
import { museApi, CHIP_PROMPTS } from '../lib/useMuse.js'
import { countWords } from '../lib/text.js'
import { useMediaQuery } from '../lib/useMediaQuery.js'

// The one place the author talks to the Muse (4.0, D63). With text selected on the page
// it edits that passage (the inline edit, D57); otherwise it is the conversation. `@`
// attaches a chapter or bible file (D56).

const CHIPS = [
  { id: 'continue', label: 'Continue' },
  { id: 'scene', label: 'New scene' },
  { id: 'canon', label: 'Canon check' },
  { id: 'rewrite', label: 'Polish last line' }
]

// The @-mention under the caret, if any: {start, query}.
function mentionAt(text, caret) {
  const upto = text.slice(0, caret)
  const m = upto.match(/(^|[\s(])@([\w./-]*)$/)
  if (!m) return null
  return { start: caret - m[2].length - 1, query: m[2].toLowerCase() }
}

export default function Composer({ muse, selection, onInline, onRewrite, inlineBusy, onOpenThread, threadOpen, disabled }) {
  const { draft, setDraft, busy, files } = muse
  const [mention, setMention] = useState(null)   // {start, query}
  const [pick, setPick] = useState(0)
  const [useSel, setUseSel] = useState(true)     // send to the selection, not the chat
  const taRef = useRef(null)
  const narrow = useMediaQuery('(max-width: 767px)')
  const caretRef = useRef(null)                  // where the caret goes after a mention pick

  const selWords = selection?.text ? countWords(selection.text) : 0
  const onSelection = selWords > 0 && useSel
  // A new selection is always offered to the composer again.
  useEffect(() => { setUseSel(true) }, [selection?.text])

  useEffect(() => {
    museApi.focus = () => taRef.current?.focus()
    return () => { museApi.focus = null }
  })

  const matches = useMemo(() => {
    if (!mention) return []
    const q = mention.query
    return files.filter((f) => !q || f.token.toLowerCase().includes(q) || f.label.toLowerCase().includes(q)).slice(0, 8)
  }, [mention, files])

  // grow with the text, up to six lines
  useLayoutEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 168) + 'px'
  }, [draft])

  // Place the caret after a picked mention *before* the next keystroke is handled — a
  // requestAnimationFrame lost the race to fast typing and spliced the words (3.2).
  useLayoutEffect(() => {
    const c = caretRef.current
    const ta = taRef.current
    if (c == null || !ta) return
    caretRef.current = null
    ta.focus()
    ta.setSelectionRange(c, c)
  }, [draft])

  const onChange = (e) => {
    setDraft(e.target.value)
    setMention(mentionAt(e.target.value, e.target.selectionStart))
    setPick(0)
  }

  const takeMention = (f) => {
    if (!mention || !f) return
    const ta = taRef.current
    const caret = ta ? ta.selectionStart : draft.length
    const next = draft.slice(0, mention.start) + '@' + f.token + ' ' + draft.slice(caret)
    caretRef.current = mention.start + f.token.length + 2
    setDraft(next)
    setMention(null)
  }

  const submit = () => {
    const text = draft.trim()
    if (!text || busy || disabled) return
    setMention(null)
    if (onSelection) {
      setDraft('')
      onInline(text)
    } else {
      muse.send(draft)
    }
  }

  const onKey = (e) => {
    if (mention && matches.length) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setPick((i) => (i + 1) % matches.length); return }
      if (e.key === 'ArrowUp') { e.preventDefault(); setPick((i) => (i - 1 + matches.length) % matches.length); return }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); takeMention(matches[pick]); return }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setMention(null); return }
    }
    if (e.key === 'Escape') { e.stopPropagation(); taRef.current?.blur(); return }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const placeholder = disabled
    ? 'Open a chapter to talk to the Muse'
    : onSelection
      ? `What should change in the ${selWords} selected word${selWords === 1 ? '' : 's'}?`
      : narrow ? 'Ask the Muse…' : 'Ask the Muse — @ attaches a file'

  return (
    <div className="relative">
      {mention && matches.length > 0 && (
        <ul
          role="listbox"
          aria-label="Attach a file"
          className="float absolute bottom-full left-0 right-0 z-20 mb-2 max-h-64 overflow-y-auto rounded-xl p-1"
        >
          {matches.map((f, i) => (
            <li key={f.token} role="option" aria-selected={i === pick}>
              <button
                onMouseDown={(e) => { e.preventDefault(); takeMention(f) }}
                className={
                  'flex min-h-9 w-full items-center gap-2 rounded-lg px-3 text-left text-[13.5px] ' +
                  (i === pick ? 'bg-panel-2 text-ink' : 'text-mute')
                }
              >
                <span className="text-accent">@</span>
                <span className="truncate">{f.label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {selWords > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <button
            onClick={() => setUseSel((v) => !v)}
            aria-pressed={useSel}
            className={
              'inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[12.5px] transition-colors ' +
              (useSel ? 'bg-accent/12 text-accent' : 'border hairline text-mute hover:text-ink')
            }
            title={useSel ? 'Sending edits the selection — click to chat instead' : 'Click to edit the selection'}
          >
            <Icon name="pen" size={14} />
            {useSel ? `Editing selection · ${selWords} words` : 'Chat (selection ignored)'}
          </button>
          {onRewrite && (
            <button
              onClick={onRewrite}
              className="inline-flex h-8 items-center gap-1.5 rounded-full border hairline px-3 text-[12.5px] text-ink hover:bg-panel-2"
              title="Rewrite the selection in a chosen style, and compare"
            >
              Rewrite…
            </button>
          )}
        </div>
      )}

      <div className="flex items-end gap-2">
        <label htmlFor="muse-composer" className="sr-only">Ask the Muse</label>
        <textarea
          id="muse-composer"
          ref={taRef}
          value={draft}
          onChange={onChange}
          onKeyDown={onKey}
          onBlur={() => setTimeout(() => setMention(null), 120)}
          rows={1}
          disabled={disabled}
          placeholder={placeholder}
          className="max-h-[168px] min-h-11 min-w-0 flex-1 resize-none bg-transparent py-2.5 text-[15px] leading-6 text-ink placeholder:text-mute/80 focus:outline-none disabled:opacity-60 max-md:text-[16px]"
        />
        {onOpenThread && (
          <button
            onClick={onOpenThread}
            aria-label={threadOpen ? 'Hide the conversation' : 'Show the conversation'}
            aria-pressed={!!threadOpen}
            title={threadOpen ? 'Hide the conversation' : 'Show the conversation'}
            className={
              'inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-colors ' +
              (threadOpen ? 'bg-accent/12 text-accent' : 'text-mute hover:bg-panel-2 hover:text-ink')
            }
          >
            <Icon name="chat" />
          </button>
        )}
        {busy || inlineBusy ? (
          <button
            onClick={muse.stop}
            aria-label="Stop the Muse"
            title="Stop"
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-err/40 text-err hover:bg-err/10"
          >
            <Icon name="stop" />
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={!draft.trim() || disabled}
            aria-label={onSelection ? 'Edit the selection' : 'Send'}
            title={onSelection ? 'Edit the selection (Enter)' : 'Send (Enter)'}
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-ink text-[var(--color-base)] transition-opacity disabled:opacity-30"
          >
            <Icon name="send" />
          </button>
        )}
      </div>

      {!draft && !onSelection && !disabled && (
        <div className="mt-1 flex gap-1.5 overflow-x-auto pb-0.5">
          {CHIPS.map((c) => (
            <button
              key={c.id}
              disabled={busy}
              onClick={() => { setDraft(CHIP_PROMPTS[c.id]); taRef.current?.focus() }}
              className="h-8 shrink-0 rounded-full border hairline px-3 text-[12.5px] text-mute transition-colors hover:border-accent/50 hover:text-ink disabled:opacity-50"
              title={CHIP_PROMPTS[c.id]}
            >
              {c.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

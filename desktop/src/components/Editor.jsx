import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import * as api from '../lib/api.js'
import { getSetting, setSetting } from '../lib/settings.js'
import { countWords, clockNow } from '../lib/text.js'
import Icon from '../ui/Icon.jsx'
import ReadingView from './ReadingView.jsx'

// THE EDITOR — the quiet center. Loads a chapter and autosaves via PUT (md
// write + revision snapshot on the server). Owns Edit/Read modes and the
// chapter's margin notes; exposes apply operations to the rest of the app via
// the module-level `editorApi` bridge.
// Ghost text (3.1, D59): after a pause at the end of a line, the Muse offers one
// sentence in grey; Tab takes it, anything else dismisses it. Opt-in (Settings).
const GHOST_DELAY = 1400
const GHOST_MIN_CHARS = 40

export default function Editor({ chapter, series, focus, onSelection, onHistory, ghost = false }) {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [savedAt, setSavedAt] = useState('')
  const [revision, setRevision] = useState(0)
  const [drafts, setDrafts] = useState(0)
  const [saving, setSaving] = useState(false)
  const [mode, setMode] = useState(() => getSetting('mode', 'edit'))
  const [notes, setNotes] = useState([])
  const taRef = useRef(null)
  const titleRef = useRef(null)
  // The title is a textarea so a long one wraps instead of running off the page; it
  // grows to fit its text, on every edit and whenever the window changes width.
  useLayoutEffect(() => {
    const fit = () => {
      const el = titleRef.current
      if (!el) return
      el.style.height = 'auto'
      el.style.height = el.scrollHeight + 'px'
    }
    fit()
    window.addEventListener('resize', fit)
    return () => window.removeEventListener('resize', fit)
  })
  const mirrorRef = useRef(null)
  const [suggest, setSuggest] = useState(null)     // {at, text} ghost text, or null
  const ghostRef = useRef({ timer: null, abort: null })
  const lastSelectionRef = useRef({ start: 0, end: 0, text: '' })
  // What is currently on disk for this chapter. Autosave only fires when the
  // buffer differs from this — so merely opening a chapter never writes a
  // revision, and a failed load can never blank the file.
  const savedRef = useRef({ key: '', body: '', title: '' })
  // The latest debounced-but-unsaved edit, so switching chapters (or closing
  // the app) flushes it instead of dropping the last few keystrokes.
  const pendingRef = useRef(null)
  const chapterKey = chapter && series ? `${series.series}/${series.book}/${chapter.id}` : ''

  useEffect(() => { setSetting('mode', mode) }, [mode])

  // Load chapter content when the selection changes.
  useEffect(() => {
    // Flush the chapter we are leaving before invalidating anything.
    const pending = pendingRef.current
    if (pending && pending.key && pending.key !== chapterKey) {
      pendingRef.current = null
      api
        .saveChapter(pending.series, pending.book, pending.chapter, pending.body, pending.title)
        .catch(() => { /* the debounce failed; nothing else to do */ })
    }
    // A new chapter invalidates both the old selection offsets and the saved
    // baseline — nothing may be written until this chapter's text has loaded.
    lastSelectionRef.current = { start: 0, end: 0, text: '' }
    if (onSelection) onSelection({ start: 0, end: 0, text: '' })
    savedRef.current = { key: '', body: '', title: '' }
    if (!chapter || !series) return
    let alive = true
    setBody('')
    setTitle(chapter.title || '')
    setSavedAt('loading')
    api
      .getChapter(series.series, series.book, chapter.id)
      .then((c) => {
        if (!alive) return
        const lines = (c.content || '').split('\n')
        if (lines[0] && lines[0].startsWith('# ')) lines.shift()
        const loadedBody = lines.join('\n').trim()
        const loadedTitle = c.title || chapter.title || ''
        setBody(loadedBody)
        setTitle(loadedTitle)
        setRevision(c.revision || 0)
        savedRef.current = { key: chapterKey, body: loadedBody, title: loadedTitle }
        setSavedAt('loaded')
      })
      .catch(() => {
        if (!alive) return
        setBody('')
        // savedRef stays invalidated: an unreadable chapter must not be
        // overwritten with whatever the empty buffer contains.
        setSavedAt('offline — not saving')
      })
    return () => { alive = false }
  }, [chapterKey])

  // Load this chapter's annotations.
  useEffect(() => {
    if (!chapter || !series) return
    let alive = true
    api
      .getNotes(series.series, series.book, chapter.id)
      .then((n) => alive && setNotes(n.notes || []))
      .catch(() => alive && setNotes([]))
    return () => { alive = false }
  }, [chapter?.id, series?.series, series?.book])

  // Autosave (debounced, edit-only). The guard is the saved-baseline diff:
  // opening a chapter or a failed GET leaves savedRef.key empty, so nothing
  // is written until a real edit happens on successfully loaded content.
  useEffect(() => {
    if (!chapterKey || !chapter || !series) return
    const saved = savedRef.current
    if (saved.key !== chapterKey) { pendingRef.current = null; return }
    if (body === saved.body && title === saved.title) { pendingRef.current = null; return }
    const t = setTimeout(() => {
      pendingRef.current = null
      api
        .saveChapter(series.series, series.book, chapter.id, body, title)
        .then((c) => {
          savedRef.current = { key: chapterKey, body, title }
          setRevision(c.revision)
          setDrafts((d) => d + 1)
          setSavedAt('saved · ' + clockNow())
        })
        .catch(() => setSavedAt('offline'))
    }, 900)
    pendingRef.current = {
      key: chapterKey,
      series: series.series,
      book: series.book,
      chapter: chapter.id,
      body,
      title,
      timer: t
    }
    return () => clearTimeout(t)
  }, [body, title, chapterKey])

  // --- ghost text -----------------------------------------------------------
  const dropGhost = () => {
    const g = ghostRef.current
    clearTimeout(g.timer)
    if (g.abort) g.abort.abort()
    g.abort = null
    setSuggest(null)
  }

  useEffect(() => {
    dropGhost()
    if (!ghost || mode !== 'edit' || !chapterKey || savedRef.current.key !== chapterKey) return
    const g = ghostRef.current
    g.timer = setTimeout(async () => {
      const ta = taRef.current
      if (!ta || document.activeElement !== ta) return
      const at = ta.selectionStart
      if (at !== ta.selectionEnd) return
      const next = body.charAt(at)
      if (next && next !== '\n') return                   // only at the end of a line
      const before = body.slice(0, at)
      if (before.trim().length < GHOST_MIN_CHARS) return
      const ac = new AbortController()
      g.abort = ac
      try {
        const text = await api.museComplete({ before, chapterId: chapterKey, signal: ac.signal })
        if (ac.signal.aborted || !text) return
        if (taRef.current?.selectionStart !== at) return
        setSuggest({ at, text })
      } catch { /* no suggestion is fine */ }
    }, GHOST_DELAY)
    return () => clearTimeout(g.timer)
  }, [body, ghost, mode, chapterKey])

  // keep the ghost layer scrolled with the page
  const syncMirror = () => {
    if (mirrorRef.current && taRef.current) mirrorRef.current.scrollTop = taRef.current.scrollTop
  }
  useEffect(syncMirror, [suggest])

  const onEditorKey = (e) => {
    if (!suggest) return
    if (e.key === 'Tab' && !e.shiftKey) {
      e.preventDefault()
      const { at, text } = suggest
      setSuggest(null)
      setBody((b) => b.slice(0, at) + text + b.slice(at))
      requestAnimationFrame(() => {
        const ta = taRef.current
        if (ta) ta.setSelectionRange(at + text.length, at + text.length)
      })
      return
    }
    if (e.key === 'Escape') e.stopPropagation()
    if (!['Shift', 'Meta', 'Control', 'Alt'].includes(e.key)) dropGhost()
  }

  // Flush the last pending edit if the editor unmounts (app closed/route gone).
  useEffect(() => () => {
    const p = pendingRef.current
    if (p) {
      api
        .saveChapter(p.series, p.book, p.chapter, p.body, p.title)
        .catch(() => { /* best-effort */ })
    }
  }, [])

  const words = countWords(body)

  const saveNow = () => {
    if (!chapter || !series || saving) return
    // Never write a chapter we failed to load.
    if (savedRef.current.key !== chapterKey) {
      setSavedAt('offline — not saving')
      return
    }
    if (pendingRef.current?.timer) clearTimeout(pendingRef.current.timer)
    pendingRef.current = null
    setSaving(true)
    api
      .saveChapter(series.series, series.book, chapter.id, body, title)
      .then((c) => {
        savedRef.current = { key: chapterKey, body, title }
        setRevision(c.revision)
        setDrafts((d) => d + 1)
        setSavedAt('saved · ' + clockNow())
      })
      .catch(() => setSavedAt('offline'))
      .finally(() => setSaving(false))
  }

  // --- annotations --------------------------------------------------------
  const commitNotes = (list = notes) => {
    if (!chapter || !series) return
    api.saveNotes(series.series, series.book, chapter.id, list).catch(() => {})
  }
  const addNote = (quote) => {
    const next = [...notes, { quote, body: '', created_at: '' }]
    setNotes(next)
    commitNotes(next)
  }
  const setNoteBody = (i, text) =>
    setNotes((ns) => ns.map((n, idx) => (idx === i ? { ...n, body: text } : n)))
  const deleteNote = (i) => {
    const next = notes.filter((_, idx) => idx !== i)
    setNotes(next)
    commitNotes(next)
  }

  // --- selection + apply bridge -------------------------------------------
  const captureSelection = () => {
    const ta = taRef.current
    if (!ta) return
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const text = start !== end ? ta.value.slice(start, end) : ''
    lastSelectionRef.current = { start, end, text }
    // Always report — an empty selection is how App clears the rewrite banner.
    if (onSelection) onSelection({ start, end, text })
  }

  useEffect(() => {
    editorApi.replaceSelection = (newText) => {
      const { start, end } = lastSelectionRef.current
      setBody(body.slice(0, start) + newText + body.slice(end))
      requestAnimationFrame(() => {
        const ta = taRef.current
        if (!ta) return
        const cursor = start + newText.length
        ta.focus()
        ta.setSelectionRange(cursor, cursor)
      })
    }

    editorApi.insertAtCursor = (newText) => {
      const ta = taRef.current
      const cursor = ta ? ta.selectionStart : body.length
      const before = body.slice(0, cursor)
      const after = body.slice(cursor)
      const lead = before.length > 0 && !before.endsWith('\n\n') ? '\n\n' : ''
      const trail = after.length > 0 && !after.startsWith('\n') ? '\n' : ''
      const text = lead + newText + trail
      setBody(before + text + after)
      requestAnimationFrame(() => {
        if (!ta) return
        const c = cursor + text.length
        ta.focus()
        ta.setSelectionRange(c, c)
      })
    }

    editorApi.appendToChapter = (newText) => {
      const sep = body.length > 0 && !body.endsWith('\n\n') ? '\n\n' : ''
      const text = sep + newText
      setBody(body + text)
      requestAnimationFrame(() => {
        const ta = taRef.current
        if (!ta) return
        ta.focus()
        ta.setSelectionRange(body.length + text.length, body.length + text.length)
      })
    }

    // Replace the whole chapter in the buffer (it will autosave like typing).
    editorApi.replaceAll = (newText, newTitle) => {
      setBody(newText)
      if (typeof newTitle === 'string' && newTitle) setTitle(newTitle)
      requestAnimationFrame(() => {
        const ta = taRef.current
        if (!ta) return
        ta.focus()
        ta.setSelectionRange(newText.length, newText.length)
      })
    }

    // Load text the SERVER just saved — an accepted Muse change, a restored revision.
    // It is already on disk with its own revision, so it becomes the saved baseline:
    // going through replaceAll made autosave write the same text again a second later,
    // which burned a revision and made every change still waiting go stale (3.1).
    editorApi.loadSaved = (newBody, newTitle, newRevision) => {
      const p = pendingRef.current
      if (p?.timer) clearTimeout(p.timer)
      pendingRef.current = null
      const t = typeof newTitle === 'string' && newTitle ? newTitle : title
      savedRef.current = { key: chapterKey, body: newBody, title: t }
      setBody(newBody)
      setTitle(t)
      if (newRevision) setRevision(newRevision)
      setSavedAt('saved · ' + clockNow())
    }

    // Write any debounced edit now — before the Muse reads the file (inline edit).
    editorApi.flush = async () => {
      const p = pendingRef.current
      if (!p) return
      clearTimeout(p.timer)
      pendingRef.current = null
      const c = await api.saveChapter(p.series, p.book, p.chapter, p.body, p.title)
      if (p.key === chapterKey) {
        savedRef.current = { key: p.key, body: p.body, title: p.title }
        setRevision(c.revision)
        setSavedAt('saved · ' + clockNow())
      }
    }

    editorApi.current = () => ({ title, body, key: chapterKey })

    return () => {
      editorApi.replaceSelection = null
      editorApi.insertAtCursor = null
      editorApi.appendToChapter = null
      editorApi.replaceAll = null
      editorApi.loadSaved = null
      editorApi.flush = null
      editorApi.current = null
    }
  }, [body, title, chapterKey])

  const reading = mode === 'read'

  // One measure everywhere (4.0, D63): the column is centred by padding, not by a
  // narrower box, so the scrollbar stays at the window's edge and the textarea, its
  // ghost layer, the title and the reading view all share the same left edge.
  return (
    <main className="page-surface relative flex h-full min-h-0 flex-col">
      <div className={'measure shrink-0 ' + (focus ? 'pt-16' : 'pt-8 max-md:pt-4')}>
        {reading ? (
          <h1 className="font-serif text-[30px] font-semibold leading-[1.15] tracking-[-0.01em] text-ink max-md:text-[25px]">
            {title || chapter?.title || ''}
          </h1>
        ) : (
          <>
            <label htmlFor="chapter-title" className="sr-only">Chapter title</label>
            <textarea
              id="chapter-title"
              ref={titleRef}
              rows={1}
              value={title}
              onChange={(e) => setTitle(e.target.value.replace(/\n/g, ' '))}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); taRef.current?.focus() } }}
              spellCheck={false}
              className="block w-full resize-none overflow-hidden border-none bg-transparent font-serif text-[30px] font-semibold leading-[1.15] tracking-[-0.01em] text-ink placeholder:text-mute/40 focus:outline-none max-md:text-[25px]"
              placeholder="Chapter title"
            />
          </>
        )}

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-mute">
          <span>{words} words</span>
          <span aria-hidden="true">·</span>
          <span>{savedAt || '…'}</span>
          <span aria-hidden="true">·</span>
          <span>rev {revision}{drafts ? ` · ${drafts} draft${drafts > 1 ? 's' : ''}` : ''}</span>
          <span className="ml-auto flex items-center gap-0.5">
            {onHistory && chapter && (
              <button
                onClick={onHistory}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-[13px] text-mute transition-colors hover:bg-panel-2 hover:text-ink"
                title="Revision history — every save, restorable"
              >
                <Icon name="history" size={15} /> History
              </button>
            )}
            <button
              onClick={() => setMode((m) => (m === 'edit' ? 'read' : 'edit'))}
              className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-[13px] text-mute transition-colors hover:bg-panel-2 hover:text-ink"
              title={reading ? 'Back to editing' : 'Read as a book, and keep margin notes'}
            >
              <Icon name={reading ? 'pen' : 'read'} size={15} /> {reading ? 'Edit' : 'Read'}
            </button>
            {!reading && (
              <button
                onClick={saveNow}
                disabled={saving}
                className="inline-flex h-8 items-center rounded-lg px-2 text-[13px] font-medium text-accent transition-colors hover:bg-accent/10 disabled:opacity-40"
                title="Save now — it also saves itself as you write"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            )}
          </span>
        </div>
      </div>

      <div className={'relative min-h-0 flex-1 ' + (reading ? 'overflow-y-auto' : 'flex flex-col')}>
        {reading ? (
          <div className="measure pb-64 pt-6">
            <ReadingView
              body={body}
              notes={notes}
              onAddNote={addNote}
              onNoteBody={setNoteBody}
              onDeleteNote={deleteNote}
              onCommitNotes={() => commitNotes()}
            />
          </div>
        ) : (
          <div className="relative flex min-h-0 flex-1">
            {/* The ghost layer: the same text, invisible, with the suggestion in grey at
                the caret. It sits behind the (transparent) textarea and scrolls with it. */}
            {suggest && (
              <div
                ref={mirrorRef}
                aria-hidden="true"
                className="measure prose-page pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words pb-64 pt-6"
                style={{ scrollbarGutter: 'stable' }}
              >
                <span className="text-transparent">{body.slice(0, suggest.at)}</span>
                <span className="text-mute/70">{suggest.text}</span>
                <span className="ml-2 rounded border hairline px-1.5 align-middle font-sans text-[11px] text-mute">Tab</span>
              </div>
            )}
            <label htmlFor="chapter-body" className="sr-only">Chapter text</label>
            <textarea
              id="chapter-body"
              ref={taRef}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              onSelect={captureSelection}
              onKeyUp={captureSelection}
              onMouseUp={captureSelection}
              onKeyDown={onEditorKey}
              onScroll={syncMirror}
              onBlur={dropGhost}
              spellCheck={false}
              style={{ scrollbarGutter: 'stable' }}
              className="measure prose-page relative min-h-0 w-full flex-1 resize-none border-none bg-transparent pb-64 pt-6 text-ink caret-accent placeholder:text-mute/50 focus:outline-none"
              placeholder="The page is blank. The story begins here."
            />
          </div>
        )}
      </div>
    </main>
  )
}

// Shared module object so the Muse + rewrite flow can apply text to the editor.
export const editorApi = {
  replaceSelection: null, insertAtCursor: null, appendToChapter: null, replaceAll: null,
  loadSaved: null, flush: null, current: null
}

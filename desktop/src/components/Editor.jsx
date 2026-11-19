import React, { useEffect, useRef, useState } from 'react'
import * as api from '../lib/api.js'
import { getSetting, setSetting } from '../lib/settings.js'
import { countWords, clockNow } from '../lib/text.js'
import { Button } from '../ui/Button.jsx'
import ReadingView from './ReadingView.jsx'

// THE EDITOR — the quiet center. Loads a chapter and autosaves via PUT (md
// write + revision snapshot on the server). Owns Edit/Read modes and the
// chapter's margin notes; exposes apply operations to the rest of the app via
// the module-level `editorApi` bridge.
export default function Editor({ chapter, series, focus, onSelection }) {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [savedAt, setSavedAt] = useState('')
  const [revision, setRevision] = useState(0)
  const [drafts, setDrafts] = useState(0)
  const [saving, setSaving] = useState(false)
  const [mode, setMode] = useState(() => getSetting('mode', 'edit'))
  const [notes, setNotes] = useState([])
  const taRef = useRef(null)
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

    // Replace the whole chapter — how an accepted Muse proposal lands (2.9, D45).
    // Deliberately not replaceSelection: accepting a revision must not depend on
    // whatever happens to be selected when the author clicks Accept.
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

    return () => {
      editorApi.replaceSelection = null
      editorApi.insertAtCursor = null
      editorApi.appendToChapter = null
      editorApi.replaceAll = null
    }
  }, [body])

  const reading = mode === 'read'
  // Focus mode gives the page the whole window — edit and read alike. Normal
  // mode fills the middle pane.
  const measure = focus ? 'w-full px-8 xl:px-12' : 'px-10'

  return (
    <main className="page-surface relative flex h-full min-h-0 flex-col bg-base">
      <div className={'shrink-0 pb-2 ' + (focus ? measure + ' pt-14' : measure + ' pt-6')}>
        {reading ? (
          <h1 className={'font-serif font-semibold text-ink ' + (focus ? 'text-[30px]' : 'text-[26px]')}>
            {title || chapter?.title || ''}
          </h1>
        ) : (
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            spellCheck={false}
            className={'w-full border-none bg-transparent font-serif font-semibold text-ink placeholder:text-mute/40 focus:outline-none ' + (focus ? 'text-[30px]' : 'text-[26px]')}
            placeholder="Chapter title"
          />
        )}

        <div className="mt-1 flex items-center gap-3 text-[10.5px] text-mute/70">
          <span>{words} words</span>
          <span>·</span>
          <span>{savedAt || '…'}</span>
          <span>·</span>
          <span>rev {revision}{drafts ? ` · ${drafts} draft${drafts > 1 ? 's' : ''}` : ''}</span>
          <span className="ml-auto flex items-center gap-2">
            <button
              onClick={() => setMode((m) => (m === 'edit' ? 'read' : 'edit'))}
              className="rounded-md border hairline px-2.5 py-0.5 text-[10.5px] font-medium text-mute transition-colors hover:text-ink"
              title={reading ? 'Back to editing' : 'Read as book'}
            >
              {reading ? 'Edit' : 'Read'}
            </button>
            {!reading && (
              <Button variant="accent" size="sm" onClick={saveNow} disabled={saving}>
                {saving ? '…' : 'Save'}
              </Button>
            )}
          </span>
        </div>
      </div>

      <div className={'min-h-0 flex-1 pb-16 ' + (reading ? 'overflow-y-auto ' : 'flex flex-col ') + measure}>
        {reading ? (
          <ReadingView
            body={body}
            notes={notes}
            onAddNote={addNote}
            onNoteBody={setNoteBody}
            onDeleteNote={deleteNote}
            onCommitNotes={() => commitNotes()}
          />
        ) : (
          <textarea
            ref={taRef}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onSelect={captureSelection}
            onKeyUp={captureSelection}
            onMouseUp={captureSelection}
            spellCheck={false}
            className={'min-h-0 w-full flex-1 resize-none border-none bg-transparent font-serif text-ink/95 placeholder:text-mute/40 focus:outline-none ' + (focus ? 'text-[17.5px] leading-[1.95]' : 'text-[16px] leading-[1.85]')}
            placeholder="The page is blank. The story begins here."
          />
        )}
      </div>
    </main>
  )
}

// Shared module object so the Muse + rewrite flow can apply text to the editor.
export const editorApi = { replaceSelection: null, insertAtCursor: null, appendToChapter: null, replaceAll: null }

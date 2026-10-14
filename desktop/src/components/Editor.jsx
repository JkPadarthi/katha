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

  useEffect(() => { setSetting('mode', mode) }, [mode])

  // Load chapter content when the selection changes.
  useEffect(() => {
    if (!chapter || !series) return
    let alive = true
    setBody('')
    setTitle(chapter.title)
    api
      .getChapter(series.series, series.book, chapter.id)
      .then((c) => {
        if (!alive) return
        const lines = (c.content || '').split('\n')
        if (lines[0] && lines[0].startsWith('# ')) lines.shift()
        setBody(lines.join('\n').trim())
        setRevision(c.revision || 0)
        setSavedAt('loaded')
      })
      .catch(() => setBody(''))
    return () => { alive = false }
  }, [chapter?.id, series?.series, series?.book])

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

  // Autosave (debounced).
  useEffect(() => {
    if (!chapter || !series || !(body || title)) return
    const t = setTimeout(() => {
      api
        .saveChapter(series.series, series.book, chapter.id, body, title)
        .then((c) => {
          setRevision(c.revision)
          setDrafts((d) => d + 1)
          setSavedAt('saved · ' + clockNow())
        })
        .catch(() => setSavedAt('offline'))
    }, 900)
    return () => clearTimeout(t)
  }, [body, title, chapter?.id, series?.series, series?.book])

  const words = countWords(body)

  const saveNow = () => {
    if (!chapter || !series || saving) return
    setSaving(true)
    api
      .saveChapter(series.series, series.book, chapter.id, body, title)
      .then((c) => {
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
    if (text && onSelection) onSelection({ start, end, text })
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

    return () => {
      editorApi.replaceSelection = null
      editorApi.insertAtCursor = null
      editorApi.appendToChapter = null
    }
  }, [body])

  const reading = mode === 'read'
  const measure = focus ? 'mx-auto w-full max-w-[68ch] px-6' : 'px-10'

  return (
    <main className="page-surface relative flex min-h-0 flex-col bg-base">
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

      <div className={'min-h-0 flex-1 overflow-y-auto pb-16 ' + measure}>
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
            className={'h-full min-h-[60vh] w-full resize-none border-none bg-transparent font-serif text-ink/95 placeholder:text-mute/40 focus:outline-none ' + (focus ? 'text-[17.5px] leading-[1.95]' : 'text-[16px] leading-[1.85]')}
            placeholder="The page is blank. The story begins here."
          />
        )}
      </div>
    </main>
  )
}

// Shared module object so the Muse + rewrite flow can apply text to the editor.
export const editorApi = { replaceSelection: null, insertAtCursor: null, appendToChapter: null }

import React, { useEffect, useRef, useState } from 'react'
import * as api from '../api.js'

// THE PAGE — the quiet center. Loads real content from the FastAPI archive
// (0.2.1) and autosaves via PUT → md write + revision snapshot on disk.
// 0.3.3 — selection capture + rewrite trigger; App.jsx owns the rewrite
// pipeline + diff overlay, this just hands selection up + accepts replacements.
export default function Page({ chapter, series, onSelection, onReplaceRequested }) {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [savedAt, setSavedAt] = useState('')
  const [revision, setRevision] = useState(0)
  const [drafts, setDrafts] = useState(0)
  const [saving, setSaving] = useState(false)
  const taRef = useRef(null)
  const lastSelectionRef = useRef({ start: 0, end: 0, text: '' })

  // Load chapter content from the archive when the selection changes.
  useEffect(() => {
    if (!chapter || !series) return
    let alive = true
    setBody('')
    setTitle(chapter.title)
    api
      .getChapter(series.series, series.book, chapter.id)
      .then((c) => {
        if (!alive) return
        // Split leading '# Title' heading from the markdown body.
        const lines = (c.content || '').split('\n')
        if (lines[0] && lines[0].startsWith('# ')) {
          lines.shift()
        }
        setBody(lines.join('\n').trim())
        setRevision(c.revision || 0)
        setSavedAt('loaded')
      })
      .catch(() => setBody(''))
    return () => { alive = false }
  }, [chapter?.id, series?.series, series?.book])

  // Autosave → PUT to the archive (writes md + revision on the Pi).
  useEffect(() => {
    if (!chapter || !series || !(body || title)) return
    const t = setTimeout(() => {
      api
        .saveChapter(series.series, series.book, chapter.id, body)
        .then((c) => {
          setRevision(c.revision)
          setDrafts((d) => d + 1)
          setSavedAt('saved · ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))
        })
        .catch(() => setSavedAt('offline'))
    }, 900)
    return () => clearTimeout(t)
  }, [body, title, chapter?.id, series?.series, series?.book])

  const words = body.trim() ? body.trim().split(/\s+/).length : 0

  // Manual save — immediate PUT (no debounce), banks a revision on demand.
  const handleManualSave = () => {
    if (!chapter || !series || saving) return
    setSaving(true)
    api
      .saveChapter(series.series, series.book, chapter.id, body)
      .then((c) => {
        setRevision(c.revision)
        setDrafts((d) => d + 1)
        setSavedAt('saved · ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))
      })
      .catch(() => setSavedAt('offline'))
      .finally(() => setSaving(false))
  }

  // Track selection in the textarea so the rewrite button knows what to send.
  // selectionchange fires on any cursor move (incl. typing) — we only fire
  // onSelection when there's a non-empty range.
  const captureSelection = () => {
    const ta = taRef.current
    if (!ta) return
    const start = ta.selectionStart
    const end = ta.selectionEnd
    const text = start !== end ? ta.value.slice(start, end) : ''
    lastSelectionRef.current = { start, end, text }
    if (text && onSelection) onSelection({ start, end, text })
  }

  // Accept a rewrite: replace the last-known selection range with new text.
  // Called from App.jsx via ref-style callback prop (see replaceSelection).
  useEffect(() => {
    if (!onReplaceRequested) return
    // App stores the replace fn on a module-level object that Page reads.
    pageApi.replaceSelection = (newText) => {
      const { start, end } = lastSelectionRef.current
      const before = body.slice(0, start)
      const after = body.slice(end)
      setBody(before + newText + after)
      // Restore selection/cursor to the new text.
      requestAnimationFrame(() => {
        const ta = taRef.current
        if (!ta) return
        const cursor = start + newText.length
        ta.focus()
        ta.setSelectionRange(cursor, cursor)
      })
    }
    return () => { pageApi.replaceSelection = null }
  }, [onReplaceRequested, body])

  return (
    <main className="page-surface relative flex min-h-0 flex-col bg-base">
      <div className="shrink-0 px-10 pt-6 pb-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          spellCheck={false}
          className="w-full border-none bg-transparent font-serif text-[26px] font-semibold text-ink placeholder:text-mute/40 focus:outline-none"
          placeholder="Chapter title"
        />
        <div className="mt-1 flex items-center gap-3 text-[10.5px] text-mute/70">
          <span>{words} words</span>
          <span>·</span>
          <span>{savedAt || '…'}</span>
          <span>·</span>
          <span>rev {revision}{drafts ? ` · ${drafts} draft${drafts > 1 ? 's' : ''}` : ''}</span>
          <span className="ml-auto flex items-center gap-2">
            <span className="flex items-center gap-1.5">
              <span className="h-1 w-1 rounded-full bg-ok" />
              autosave
            </span>
            <button
              onClick={handleManualSave}
              disabled={saving}
              className="rounded-md border border-gold/40 px-2.5 py-0.5 text-[10.5px] font-medium text-ink transition-colors hover:bg-gold/10 disabled:opacity-40"
            >
              {saving ? '…' : 'Save'}
            </button>
          </span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-10 pb-16">
        <textarea
          ref={taRef}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onSelect={captureSelection}
          onKeyUp={captureSelection}
          onMouseUp={captureSelection}
          spellCheck={false}
          className="h-full min-h-[60vh] w-full resize-none border-none bg-transparent font-serif text-[16px] leading-[1.85] text-ink/95 placeholder:text-mute/40 focus:outline-none"
          placeholder="The page is blank. The story begins here."
        />
      </div>
    </main>
  )
}

// Tiny shared module object so App can call into Page's `replaceSelection`.
// Single-page-app, no router — this is fine.
export const pageApi = { replaceSelection: null }

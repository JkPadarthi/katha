import React, { useEffect, useState } from 'react'
import * as api from '../api.js'

// THE PAGE — the quiet center. Loads real content from the FastAPI archive
// (0.2.1) and autosaves via PUT → md write + revision snapshot on disk.
export default function Page({ chapter, series }) {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [savedAt, setSavedAt] = useState('')
  const [revision, setRevision] = useState(0)
  const [drafts, setDrafts] = useState(0)

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

  return (
    <main className="page-surface flex min-h-0 flex-col bg-base">
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
          <span className="ml-auto flex items-center gap-1.5">
            <span className="h-1 w-1 rounded-full bg-ok" />
            autosave
          </span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-10 pb-16">
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          spellCheck={false}
          className="h-full min-h-[60vh] w-full resize-none border-none bg-transparent font-serif text-[16px] leading-[1.85] text-ink/95 placeholder:text-mute/40 focus:outline-none"
          placeholder="The page is blank. The story begins here."
        />
      </div>
    </main>
  )
}

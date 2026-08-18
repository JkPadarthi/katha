import React, { useEffect, useState } from 'react'
import { sampleProse } from '../data.js'

// THE PAGE — the quiet center. Markdown textarea backed by autosave
// (localStorage in 0.1; the FastAPI archive takes over in 0.2).
export default function Page({ chapter }) {
  const [title, setTitle] = useState(chapter.title)
  const [body, setBody] = useState(sampleProse)
  const [savedAt, setSavedAt] = useState('just now')
  const [drafts] = useState(12)

  useEffect(() => setTitle(chapter.title), [chapter.id, chapter.title])

  // Debounced autosave stub — proves the loop before the server exists.
  useEffect(() => {
    const t = setTimeout(() => {
      try {
        localStorage.setItem(`katha:${chapter.id}`, body)
        setSavedAt('saved · ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))
      } catch { /* preview mode */ }
    }, 800)
    return () => clearTimeout(t)
  }, [body, chapter.id])

  const words = body.trim() ? body.trim().split(/\s+/).length : 0

  return (
    <main className="page-surface flex min-h-0 flex-col bg-base">
      {/* Page header: title + status line */}
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
          <span>{savedAt}</span>
          <span>·</span>
          <span>{drafts} drafts</span>
          <span className="ml-auto flex items-center gap-1.5">
            <span className="h-1 w-1 rounded-full bg-ok" />
            autosave
          </span>
        </div>
      </div>

      {/* The blank page */}
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
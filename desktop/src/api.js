// Katha API client — talks to the FastAPI archive.
// The server serves this app AND the API from the same origin (the Pi, one
// port), so every request is a same-origin `/api/...`. In dev, Vite proxies
// `/api` to the local server (see vite.config.js). No base-URL juggling.

export const BASE = ''

async function req(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  })
  if (!res.ok) {
    const err = new Error(`${res.status} ${res.statusText} — ${path}`)
    err.status = res.status
    throw err
  }
  return res.json()
}

export function health() {
  return req('/health')
}

// Returns the archive in the shape the Rail already expects:
//   [{ series, books: [{ id, title, chapters: [{id,title,words}], bible }] }]
export async function loadArchive() {
  const tree = await req('/books')          // [{series, title, books:[{id,title,chapter_count}]}]
  const archive = []
  for (const s of tree) {
    const series = { name: s.series, title: s.title || s.series, books: [] }
    for (const b of s.books) {
      const chapters = await req(`/books/${s.series}/${b.id}/chapters`)
      let bible = {}
      try {
        bible = await req(`/books/${s.series}/${b.id}/bible`).then((x) => x.files)
        bible = Object.entries(bible).map(([path]) => ({
          id: path,                       // bible-relative path, e.g. characters/kael.md
          title: path.split('/').pop()    // basename for display
        }))
      } catch { /* bible optional */ }
      series.books.push({
        id: b.id,
        title: b.title,
        chapters: chapters.chapters.map((c) => ({
          id: c.id,
          title: c.title,
          words: c.words
        })),
        bible
      })
    }
    archive.push(series)
  }
  return archive
}

export function getChapter(series, bookId, chapterId) {
  return req(`/books/${series}/${bookId}/chapters/${chapterId}`)
}

export function saveChapter(series, bookId, chapterId, content, title) {
  return req(`/books/${series}/${bookId}/chapters/${chapterId}`, {
    method: 'PUT',
    body: JSON.stringify({ content, title: title || null })
  })
}

export function search(query, limit = 20) {
  return req(`/search?q=${encodeURIComponent(query)}&limit=${limit}`)
}

// --- Muse (0.3 Muse, D16/D17/D19) ------------------------------------------
// Server streams SSE `data: <chunk>\n\n` events terminated by `data: [DONE]\n\n`.
// Chunks are single-pass escaped (`\n` → `\n` literal, `\` → `\\`) — unescape
// must match tokens in one pass or escaped backslashes corrupt. A failed
// upstream arrives as `data: [ERROR] <message>` before [DONE]. onDelta
// receives the cumulative *visible* text so far.

function unescapeSse(s) {
  return s.replace(/\\n|\\\\/g, (m) => (m === '\\n' ? '\n' : '\\'))
}

async function streamSse(path, body, { onDelta, onStatus, signal }) {
  const res = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal
  })
  if (!res.ok || !res.body) {
    throw new Error(`${res.status} ${res.statusText} — ${path}`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buf = ''
  let acc = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    // SSE events are separated by blank lines.
    let idx
    while ((idx = buf.indexOf('\n\n')) !== -1) {
      const event = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      for (const line of event.split('\n')) {
        if (!line.startsWith('data:')) continue
        // SSE `data: ` prefix is 6 chars (data: + 1 space). Preserve any
        // leading whitespace in the payload itself — it's part of the prose.
        const payload = line.length > 5 && line[5] === ' '
          ? line.slice(6)
          : line.slice(5)
        if (payload.startsWith('[STATUS]')) {
          if (onStatus) onStatus(payload.slice(8).trim())
          continue
        }
        if (payload.startsWith('[ERROR]')) {
          throw new Error(payload.slice(7).trim() || 'Muse error')
        }
        if (payload.trim() === '[DONE]') return acc
        acc += unescapeSse(payload)
      }
      if (onDelta) onDelta(acc)
    }
  }
  return acc
}

export function museChat({ messages, chapterId, chip, onDelta, onStatus, signal }) {
  return streamSse('/muse/chat', {
    messages,
    chapter_id: chapterId || null,
    chip: chip || null
  }, { onDelta, onStatus, signal })
}

export function museRewrite({ text, style, chapterId, onDelta, signal }) {
  return streamSse('/muse/rewrite', {
    text,
    style: style || 'novel',
    chapter_id: chapterId || null
  }, { onDelta, signal })
}

export function museModels() {
  return req('/muse/models')
}

// --- canon sweep (0.4) ----------------------------------------------------

export function getBible(series, bookId) {
  return req(`/books/${series}/${bookId}/bible`)
}

export function saveBible(series, bookId, name, content) {
  // `name` may be a nested path (characters/kael.md) — encodeURI keeps '/'.
  return req(`/books/${series}/${bookId}/bible/${encodeURI(name)}`, {
    method: 'PUT',
    body: JSON.stringify({ content })
  })
}

// target: 'report' (whole-book audit) | 'bible' (proposed rewrite of one file)
export function museSweep({ series, bookId, target, bibleName, onDelta, signal }) {
  return streamSse('/muse/sweep', {
    series,
    book_id: bookId,
    target: target || 'report',
    bible_name: bibleName || null
  }, { onDelta, signal })
}

// --- reading-mode notes (1.0) ---------------------------------------------

export function getNotes(series, bookId, chapterId) {
  return req(`/books/${series}/${bookId}/chapters/${chapterId}/notes`)
}

export function saveNotes(series, bookId, chapterId, notes) {
  return req(`/books/${series}/${bookId}/chapters/${chapterId}/notes`, {
    method: 'PUT',
    body: JSON.stringify({
      notes: (notes || []).map((n) => ({
        quote: n.quote || '',
        body: n.body || '',
        created_at: n.created_at || null
      }))
    })
  })
}

// --- writing rituals (1.0) ------------------------------------------------

export function getStats(goal) {
  return req('/stats' + (goal ? `?goal=${goal}` : ''))
}

// --- delivery: EPUB export (1.0) ------------------------------------------

export async function exportEpub(series, bookId, filename) {
  const res = await fetch(`/api/books/${series}/${bookId}/export.epub`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — export`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || 'katha.epub'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

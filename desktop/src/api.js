// Katha API client — talks to the FastAPI archive (0.2.1).
// Base URL: Tailscale address of Bharat by default (works from the web
// preview on the same machine too, since Bharat == this host). Override
// with VITE_KATHA_API for other origins (e.g. packaged desktop later).
const BASE =
  import.meta.env.VITE_KATHA_API ||
  (import.meta.env.DEV
    ? 'http://localhost:4901'
    : 'http://100.86.68.51:4901')

async function req(path, options = {}) {
  const res = await fetch(`${BASE}/api${path}`, {
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
        bible = Object.entries(bible).map(([title, _]) => ({ id: title, title }))
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

export function saveChapter(series, bookId, chapterId, content) {
  return req(`/books/${series}/${bookId}/chapters/${chapterId}`, {
    method: 'PUT',
    body: JSON.stringify({ content })
  })
}

export function search(query, limit = 20) {
  return req(`/search?q=${encodeURIComponent(query)}&limit=${limit}`)
}

// --- Muse (0.3 Muse, D16/D17/D19) ------------------------------------------
// Server streams SSE `data: <chunk>\n\n` lines terminated by `data: [DONE]\n\n`.
// Newlines inside `chunk` are escaped as `\n` literals — we un-escape them
// on the client before appending to the assistant text. The onDelta callback
// receives the cumulative *visible* text so far (the simplest UX contract).

function unescapeSse(s) {
  return s.replace(/\\n/g, '\n').replace(/\\\\/g, '\\')
}

export function museChat({ messages, chapterId, chip, onDelta, signal }) {
  // POST and read the SSE stream chunk-by-chunk.
  return (async () => {
    const res = await fetch(`${BASE}/api/muse/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages, chapter_id: chapterId || null, chip: chip || null }),
      signal
    })
    if (!res.ok || !res.body) {
      throw new Error(`${res.status} ${res.statusText} — muse/chat`)
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
          if (payload.trim() === '[DONE]') return acc
          acc += unescapeSse(payload)
        }
        if (onDelta) onDelta(acc)
      }
    }
    return acc
  })()
}

export function museRewrite({ text, style, chapterId, onDelta, signal }) {
  return (async () => {
    const res = await fetch(`${BASE}/api/muse/rewrite`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, style: style || 'novel', chapter_id: chapterId || null }),
      signal
    })
    if (!res.ok || !res.body) {
      throw new Error(`${res.status} ${res.statusText} — muse/rewrite`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buf = ''
    let acc = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const event = buf.slice(0, idx)
        buf = buf.slice(idx + 2)
        for (const line of event.split('\n')) {
          if (!line.startsWith('data:')) continue
          const payload = line.length > 5 && line[5] === ' '
            ? line.slice(6)
            : line.slice(5)
          if (payload.trim() === '[DONE]') return acc
          acc += unescapeSse(payload)
        }
        if (onDelta) onDelta(acc)
      }
    }
    return acc
  })()
}

export function museModels() {
  return req('/muse/models')
}

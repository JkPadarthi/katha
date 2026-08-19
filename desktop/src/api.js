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

/**
 * Where to land when the app opens or reloads (3.0.8, D52).
 *
 * Before this, a refresh always opened the *first* chapter — so the author's last three hours
 * of work sat at the bottom of the rail while the prologue filled the screen. Two rules, in
 * this order:
 *
 *   1. the chapter they were last in, if it still exists (resume where you left off);
 *   2. otherwise the chapter most recently written — "the latest", not "the first".
 *
 * Pure functions, no React and no storage, so they can be checked on their own.
 */

function chaptersOf(archive, series, book) {
  const s = (archive || []).find((x) => x.name === series)
  const b = (s?.books || []).find((x) => x.id === book)
  return b?.chapters || []
}

/** The series+book to open: the remembered one if it survives, else the first that has chapters. */
export function pickSeries({ archive = [], remembered = null }) {
  const withChapters = archive.filter((s) => (s.books || []).some((b) => (b.chapters || []).length))
  const pool = withChapters.length ? withChapters : archive
  if (remembered) {
    const s = pool.find((x) => x.name === remembered.series
      && (x.books || []).some((b) => b.id === remembered.book))
    if (s) return { series: s.name, book: remembered.book }
  }
  const s0 = pool[0]
  if (!s0 || !s0.books || !s0.books[0]) return null
  return { series: s0.name, book: s0.books[0].id }
}

/** The chapter to open: the remembered one if it is still there, else the newest written. */
export function pickChapter({ archive = [], series = null, book = null, remembered = null }) {
  const chapters = chaptersOf(archive, series, book)
  if (!chapters.length) return null
  if (remembered && remembered.series === series && remembered.book === book
      && chapters.some((c) => c.id === remembered.id)) {
    return remembered.id
  }
  return newestChapter(chapters)
}

/** The most recently written chapter (ISO `updated_at`), falling back to list order. */
export function newestChapter(chapters = []) {
  if (!chapters.length) return null
  const stamped = chapters.filter((c) => c.updated_at)
  if (!stamped.length) return chapters[0].id
  // Parse rather than compare strings: Python's isoformat omits the microseconds when they
  // are exactly zero, so the strings are not always the same width.
  const stamp = (c) => {
    const t = Date.parse(c.updated_at)
    return Number.isNaN(t) ? -Infinity : t
  }
  return stamped.reduce((best, c) => (stamp(c) > stamp(best) ? c : best)).id
}

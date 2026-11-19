import { useCallback, useEffect, useMemo, useState } from 'react'
import * as api from './api.js'
import { getSetting, setSetting } from './settings.js'
import { pickChapter, pickSeries, newestChapter } from './resume.js'

// Where the author is: the archive tree, the open book and chapter, and the moves
// between them (4.0 — lifted out of App.jsx unchanged in behaviour).
export function useBook() {
  const [archive, setArchive] = useState(null)
  const [series, setSeries] = useState(null)          // {series, book}
  const [activeChapter, setActiveChapter] = useState(null)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    let alive = true
    setLoadError('')
    api
      .loadArchive()
      .then((a) => {
        if (!alive) return
        setArchive(a)
        // Land where the author actually was: the chapter they last had open, else the
        // one written most recently — never simply the first in the list (3.0.8, D52).
        const remembered = getSetting('lastChapter', null)
        const target = pickSeries({ archive: a, remembered })
        if (target) {
          setSeries(target)
          setActiveChapter(pickChapter({ archive: a, ...target, remembered }))
        }
        // An empty archive is a legitimate state, not a failure: `archive` stays [].
      })
      .catch((err) => { if (alive) setLoadError(`${err.message || err}`) })
    return () => { alive = false }
  }, [])

  // Remember where the author is, so a refresh resumes there.
  useEffect(() => {
    if (series && activeChapter) {
      setSetting('lastChapter', { series: series.series, book: series.book, id: activeChapter })
    }
  }, [series, activeChapter])

  // Re-fetch the tree without disturbing the current selection.
  const refresh = useCallback(async () => {
    try { setArchive(await api.loadArchive()) } catch { /* keep the existing tree */ }
  }, [])

  const book = useMemo(
    () => (archive && series ? archive.find((s) => s.name === series.series)?.books?.find((b) => b.id === series.book) : null),
    [archive, series]
  )
  const chapter = useMemo(
    () => book?.chapters?.find((c) => c.id === activeChapter) || null,
    [book, activeChapter]
  )
  const chapterKey = series && chapter ? `${series.series}/${series.book}/${chapter.id}` : null

  const selectBook = (seriesName, bookId, tree = archive) => {
    if (!tree) return
    const s = tree.find((x) => x.name === seriesName)
    const b = s?.books.find((x) => x.id === bookId) || s?.books[0]
    if (!b) return
    setSeries({ series: s.name, book: b.id })
    setActiveChapter(b.chapters[0]?.id || null)
  }

  const newChapter = async (kind = 'chapter') => {
    if (!series) return null
    // A prologue is chapter 0 — opt-in per book (D39).
    const prologue = kind === 'prologue'
    try {
      const c = await api.createChapter(series.series, series.book, prologue ? 'Prologue' : 'Untitled', '', prologue ? 0 : null)
      await refresh()
      setActiveChapter(c.id)
      return c
    } catch { return null /* the archive refresh will surface any failure */ }
  }

  const onBookCreated = async (b) => {
    if (!b) return
    await refresh()
    setSeries({ series: b.series, book: b.id })
    setActiveChapter(b.chapters?.[0]?.id || null)
  }

  // Deleting moves the files to the trash (D33). Forget them at once, and if what was
  // open went, land on whatever is left — or on the empty-archive panel.
  const onDeleted = async (manifest) => {
    if (manifest.kind === 'bible') { refresh(); return }
    const wasActive = manifest.kind === 'chapter' && manifest.chapter_id === activeChapter
    const tookOpenBook = manifest.kind === 'book' || manifest.kind === 'series'
    await refresh()
    if (!wasActive && !tookOpenBook) return
    try {
      const tree = await api.loadArchive()
      const s = tree.find((x) => x.name === manifest.series) || tree.find((x) => x.books.some((b) => b.chapters.length))
      const b = s?.books.find((x) => x.id === manifest.book_id && x.chapters.length) ||
                s?.books.find((x) => x.chapters.length)
      if (s && b) {
        setSeries({ series: s.name, book: b.id })
        setActiveChapter(b.chapters[0] ? newestChapter(b.chapters) : null)
      } else {
        setSeries(null)
        setActiveChapter(null)
      }
    } catch { /* the refresh above already surfaced any failure */ }
  }

  // A search hit carries its own series/book — open that one. Returns the hit's kind.
  const openHit = (hit) => {
    const s = archive?.find((x) => x.name === hit.series)
    const b = s?.books?.find((x) => x.id === hit.book_id) || s?.books?.[0]
    setSeries({ series: hit.series, book: b?.id || hit.book_id })
    if (hit.kind === 'chapter') setActiveChapter(hit.doc_id)
    return hit.kind
  }

  return {
    archive, series, book, chapter, chapterKey, activeChapter, loadError,
    setActiveChapter, refresh, selectBook, newChapter, onBookCreated, onDeleted, openHit
  }
}

import React, { useEffect, useState } from 'react'
import * as api from '../lib/api.js'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Button } from '../ui/Button.jsx'

// Deleting the author's own prose is the one operation that must never be a
// surprise. This dialog asks the server what would *actually* go — books,
// chapters, revisions, notes, Muse threads, words, files — prints those numbers,
// and offers one red button. The files move to the archive's trash, so
// Settings → Trash can bring them back; the dialog says so, because that is the
// thing that makes a deliberate click safe.
//
// One dialog covers every kind (chapter, book, bible file, whole series): the
// only thing that changes is what the server is asked and what it is called.

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

function facts(impact) {
  if (!impact) return []
  const out = []
  if (impact.books != null) out.push(plural(impact.books, 'book'))
  if (impact.chapters != null) out.push(plural(impact.chapters, 'chapter'))
  if (impact.words) out.push(`${impact.words.toLocaleString()} words`)
  if (impact.revisions) out.push(plural(impact.revisions, 'revision snapshot'))
  if (impact.notes) out.push(plural(impact.notes, 'margin note'))
  if (impact.threads) out.push(plural(impact.threads, 'Muse thread'))
  if (impact.bible_files) out.push(plural(impact.bible_files, 'bible file'))
  out.push(plural(impact.files, 'file'))
  return out
}

const bytes = (n) => (n >= 1024 * 1024 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

const KINDS = {
  chapter: { title: 'Delete chapter', verb: 'Delete chapter', what: '' },
  book: { title: 'Delete book', verb: 'Delete book', what: ' — the whole book' },
  bible: { title: 'Delete bible file', verb: 'Delete file', what: ' — this bible file' },
  series: { title: 'Delete series', verb: 'Delete series', what: ' — every book in it' }
}

export default function ConfirmDeleteDialog({ target, onClose, onDeleted, onDeleteSeries }) {
  const [impact, setImpact] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const kind = KINDS[target.kind] ? target.kind : 'book'
  const meta = KINDS[kind]

  useEffect(() => {
    let dead = false
    setImpact(null)
    setError('')
    const load =
      kind === 'chapter'
        ? api.chapterImpact(target.series, target.book, target.chapter)
        : kind === 'bible'
          ? api.bibleImpact(target.series, target.book, target.path)
          : kind === 'series'
            ? api.seriesImpact(target.series)
            : api.bookImpact(target.series, target.book)
    load
      .then((i) => { if (!dead) setImpact(i) })
      .catch((e) => { if (!dead) setError(e.message || 'could not inspect that') })
    return () => { dead = true }
  }, [kind, target.series, target.book, target.chapter, target.path])

  const confirm = async () => {
    setBusy(true)
    setError('')
    try {
      const manifest =
        kind === 'chapter'
          ? await api.deleteChapter(target.series, target.book, target.chapter)
          : kind === 'bible'
            ? await api.deleteBible(target.series, target.book, target.path)
            : kind === 'series'
              ? await api.deleteSeries(target.series)
              : await api.deleteBook(target.series, target.book)
      onDeleted(manifest)
    } catch (e) {
      setError(e.message || 'the delete failed')
      setBusy(false)
    }
  }

  return (
    <Overlay onClose={onClose} width={440} padTop="22vh" z={55} dismissable={!busy}>
      <OverlayHeader title={meta.title} onClose={onClose} />
      <div className="space-y-3 px-4 py-4">
        <p className="text-[12.5px] text-ink">
          <span className="font-medium">{target.label}</span>
          {meta.what} will be moved out of the archive.
        </p>

        {impact ? (
          <ul className="flex flex-wrap gap-1.5">
            {facts(impact).map((f) => (
              <li
                key={f}
                className="rounded-md border hairline bg-panel-2 px-2 py-0.5 text-[10.5px] text-mute"
              >
                {f}
              </li>
            ))}
            <li className="rounded-md border hairline bg-panel-2 px-2 py-0.5 text-[10.5px] text-mute">
              {bytes(impact.bytes)}
            </li>
          </ul>
        ) : (
          !error && <p className="text-[11px] text-mute">Checking what would go…</p>
        )}

        <p className="text-[11px] leading-relaxed text-mute">
          Nothing is erased: it lands in the trash and can be brought back from{' '}
          <span className="text-ink">Settings → Trash</span>. The rail and search
          will forget it immediately.
        </p>

        {kind === 'book' && onDeleteSeries && (
          <button
            onClick={onDeleteSeries}
            disabled={busy}
            className="text-left text-[10.5px] text-mute/70 underline decoration-dotted hover:text-err disabled:opacity-40"
          >
            …or delete the entire series instead — every book in “{target.seriesTitle || 'this series'}”
          </button>
        )}

        {error && <p className="text-[11px] text-err">{error}</p>}

        <div className="flex items-center justify-end gap-2 pt-1">
          <Button onClick={onClose} disabled={busy}>Cancel</Button>
          <Button
            onClick={confirm}
            disabled={busy || !impact}
            className="border border-err/50 text-err hover:bg-err/10"
            title="Move it to the trash (recoverable)"
          >
            {busy ? 'Deleting…' : meta.verb}
          </Button>
        </div>
      </div>
    </Overlay>
  )
}

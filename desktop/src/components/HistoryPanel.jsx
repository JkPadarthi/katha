import React, { useEffect, useMemo, useState } from 'react'
import { diffWordsWithSpace } from 'diff'
import * as api from '../lib/api.js'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Button } from '../ui/Button.jsx'

// The TIME MACHINE (D9, browsable since 3.1). Every save of a chapter is a full
// snapshot (ch-01.<n>.md); this lists them, shows any one against the chapter as it
// stands, and restores it. Restoring is a normal save — so it is itself a new
// revision, and undoing a restore is restoring the one before it. Nothing is lost.

function splitTitle(text) {
  const lines = (text || '').split('\n')
  if (lines[0] && lines[0].startsWith('# ')) {
    const title = lines.shift().slice(2).trim()
    return { title, body: lines.join('\n').trim() }
  }
  return { title: '', body: (text || '').trim() }
}

function when(iso) {
  try {
    const d = new Date(iso)
    return d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

export default function HistoryPanel({ series, chapter, current, onRestored, onClose }) {
  const [revs, setRevs] = useState(null)
  const [sel, setSel] = useState(null)        // revision number
  const [snap, setSnap] = useState(null)      // {title, body, words, created_at}
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .listRevisions(series.series, series.book, chapter.id)
      .then((r) => {
        if (!alive) return
        const list = [...(r || [])].sort((a, b) => b.number - a.number)
        setRevs(list)
        if (list.length) setSel(list[0].number)
      })
      .catch((e) => alive && setError(e.message || 'could not load history'))
    return () => { alive = false }
  }, [series.series, series.book, chapter.id])

  useEffect(() => {
    if (sel == null) return
    let alive = true
    setSnap(null)
    api
      .getRevision(series.series, series.book, chapter.id, sel)
      .then((r) => alive && setSnap({ ...splitTitle(r.content), words: r.words, created_at: r.created_at }))
      .catch((e) => alive && setError(e.message || 'could not load that revision'))
    return () => { alive = false }
  }, [sel, series.series, series.book, chapter.id])

  // Read as "what restoring would change": from the chapter now → to the snapshot.
  const parts = useMemo(
    () => (snap ? diffWordsWithSpace(current?.body || '', snap.body || '') : []),
    [snap, current]
  )
  const same = snap && (current?.body || '').trim() === (snap.body || '').trim() &&
    (!snap.title || snap.title === current?.title)

  const restore = async () => {
    if (!snap) return
    setBusy(true)
    setError('')
    try {
      const saved = await api.saveChapter(
        series.series, series.book, chapter.id, snap.body, snap.title || current?.title || ''
      )
      onRestored(saved)
      onClose()
    } catch (e) {
      setError(e.message || 'restore failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Overlay onClose={onClose} width={900} height="82vh" padTop="7vh" dismissable={!busy}>
      <div className="flex h-full flex-col">
        <OverlayHeader
          icon="⟲"
          title={`History · ${chapter.title || chapter.id}`}
          onClose={onClose}
          extra={
            <span className="text-[10.5px] text-mute">
              {revs ? `${revs.length} revision${revs.length === 1 ? '' : 's'}` : '…'}
            </span>
          }
        />
        <div className="flex min-h-0 flex-1">
          <ul className="w-[180px] shrink-0 overflow-y-auto border-r hairline py-1">
            {(revs || []).map((r, i) => (
              <li key={r.number}>
                <button
                  onClick={() => setSel(r.number)}
                  className={
                    'flex w-full flex-col items-start px-3 py-1.5 text-left transition-colors ' +
                    (sel === r.number ? 'bg-panel-2 text-ink' : 'text-mute hover:bg-panel-2/60 hover:text-ink')
                  }
                >
                  <span className="text-[11.5px]">
                    rev {r.number}{i === 0 ? ' · latest' : ''}
                  </span>
                  <span className="text-[10px] text-mute/70">
                    {when(r.created_at)} · {r.words} words
                  </span>
                </button>
              </li>
            ))}
            {revs && !revs.length && (
              <li className="px-3 py-2 text-[11px] text-mute/60">No saved revisions yet.</li>
            )}
          </ul>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {error && (
              <div className="mb-3 rounded-md border border-err/30 bg-err/10 px-3 py-2 text-[11px] text-err">
                {error}
              </div>
            )}
            {!snap ? (
              <div className="text-[11.5px] text-mute/60">{sel == null ? '' : 'Loading…'}</div>
            ) : (
              <>
                <div className="mb-3 text-[10.5px] text-mute">
                  {same
                    ? 'This revision is identical to the chapter as it stands.'
                    : <>Restoring would change the chapter like this — <span className="text-err/80 line-through">removed</span>, <span className="text-ok">added</span>.</>}
                  {snap.title && snap.title !== current?.title && (
                    <span className="ml-1">Title: “{snap.title}”.</span>
                  )}
                </div>
                <div className="whitespace-pre-wrap font-serif text-[14.5px] leading-[1.85] text-mute/90">
                  {parts.map((p, i) => (
                    <span
                      key={i}
                      className={p.added ? 'bg-ok/10 text-ok' : p.removed ? 'text-err/80 line-through' : ''}
                    >
                      {p.value}
                    </span>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center justify-between border-t hairline px-4 py-2.5">
          <span className="text-[10px] text-mute/60">
            Restoring saves this revision as a new one — nothing is ever overwritten.
          </span>
          <Button variant="accent" onClick={restore} disabled={busy || !snap || same}>
            {busy ? 'Restoring…' : sel != null ? `Restore rev ${sel}` : 'Restore'}
          </Button>
        </div>
      </div>
    </Overlay>
  )
}

import React, { useEffect, useMemo, useState } from 'react'
import * as api from '../lib/api.js'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Button } from '../ui/Button.jsx'

// The CANON SWEEP — a whole-book continuity pass.
//
// The report is a list of located issues (`- [ch-03] …`), and every issue has a Fix
// button that hands it to the Muse, which stages edits for review like any other change
// (3.1, D60). A bible update is a staged change too: the Muse drafts the file, and it
// opens in the same per-hunk review as everything else (D54). Nothing is written until
// the author accepts.

const ISSUE_RE = /^\s*[-*]\s*\[([^\]]+)\]\s*(.+)$/

// Turn the markdown report into renderable rows.
export function parseReport(text) {
  const rows = []
  for (const line of (text || '').split('\n')) {
    const m = line.match(ISSUE_RE)
    if (m) {
      const refs = m[1].split(',').map((r) => r.trim()).filter(Boolean)
      rows.push({ kind: 'issue', refs, text: m[2].trim() })
    } else if (/^\s*#{1,6}\s/.test(line)) {
      rows.push({ kind: 'heading', text: line.replace(/^\s*#+\s*/, '') })
    } else if (line.trim()) {
      rows.push({ kind: 'text', text: line })
    }
  }
  return rows
}

export default function SweepPanel({ series, onClose, onFix, onReview }) {
  const [report, setReport] = useState('')
  const [reportBusy, setReportBusy] = useState(false)
  const [error, setError] = useState('')
  const [bible, setBible] = useState({})          // name → content
  const [drafting, setDrafting] = useState(null)  // { name, text } while the Muse drafts
  const [note, setNote] = useState('')
  const [usage, setUsage] = useState(null)

  useEffect(() => {
    let alive = true
    api
      .getBible(series.series, series.book)
      .then((b) => alive && setBible(b.files || {}))
      .catch(() => {})
    return () => { alive = false }
  }, [series.series, series.book])

  const rows = useMemo(() => parseReport(report), [report])

  const runReport = async () => {
    setError('')
    setReport('')
    setReportBusy(true)
    try {
      const full = await api.museSweep({
        series: series.series,
        bookId: series.book,
        target: 'report',
        onDelta: (acc) => setReport(acc),
        onUsage: setUsage
      })
      setReport(full)
    } catch (e) {
      setError(e.message || 'sweep failed')
    } finally {
      setReportBusy(false)
    }
  }

  const propose = async (name) => {
    setError('')
    setNote('')
    setDrafting({ name, text: '' })
    let staged = ''
    try {
      await api.museSweep({
        series: series.series,
        bookId: series.book,
        target: 'bible',
        bibleName: name,
        onDelta: (acc) => setDrafting({ name, text: acc }),
        onProposal: (id) => { staged = id },
        onStatus: (s) => setNote(s),
        onUsage: setUsage
      })
    } catch (e) {
      setError(e.message || 'bible sweep failed')
    } finally {
      setDrafting(null)
    }
    if (staged && onReview) onReview(staged)
    else if (!staged) setNote((n) => n || 'The Muse produced no change for that file.')
  }

  const bibleNames = Object.keys(bible).sort()
  const busy = reportBusy || !!drafting

  return (
    <Overlay onClose={onClose} width={780} height="76vh" padTop="7vh" dismissable={!drafting}>
      <div className="flex h-full flex-col">
        <OverlayHeader
          icon="⚑"
          title="Canon sweep"
          onClose={onClose}
          extra={
            <span className="flex items-center gap-2">
              {usage && !busy && (
                <span className="text-[12px] text-mute/60">
                  {usage.input} in · {usage.output} out
                </span>
              )}
              <Button variant="accent" size="sm" onClick={runReport} disabled={busy}>
                {reportBusy ? 'sweeping…' : 'Run sweep'}
              </Button>
            </span>
          }
        />

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {error && (
            <div className="mb-3 rounded-lg border border-err/30 bg-err/10 px-3 py-2 text-[13px] text-err">
              {error}
            </div>
          )}

          <div className="mb-2 text-[11.5px] text-mute/70">Continuity report</div>
          {report ? (
            <div className="space-y-1">
              {rows.map((r, i) => {
                if (r.kind === 'heading') {
                  return (
                    <div key={i} className="pt-2 text-[13.5px] font-medium text-ink">{r.text}</div>
                  )
                }
                if (r.kind === 'text') {
                  return (
                    <div key={i} className="whitespace-pre-wrap text-[14px] leading-relaxed text-mute">{r.text}</div>
                  )
                }
                return (
                  <div key={i} className="flex items-start gap-2 rounded-lg border hairline px-2.5 py-1.5">
                    <div className="min-w-0 flex-1 text-[14px] leading-relaxed text-ink/95">
                      <span className="mr-1.5 inline-flex flex-wrap gap-1 align-middle">
                        {r.refs.map((ref) => (
                          <span key={ref} className="rounded bg-panel-2 px-1.5 py-px text-[12px] text-accent/90">
                            {ref}
                          </span>
                        ))}
                      </span>
                      {r.text}
                    </div>
                    {onFix && !reportBusy && (
                      <Button
                        size="sm"
                        onClick={() => onFix(r)}
                        title="Ask the Muse to fix this — its edits come to you for review"
                      >
                        Fix
                      </Button>
                    )}
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="text-[13.5px] text-mute/60">
              {reportBusy
                ? 'Reading the whole book…'
                : 'Run a sweep to audit canon, timeline, and character continuity across the manuscript.'}
            </div>
          )}

          <div className="mb-2 mt-5 text-[11.5px] text-mute/70">Bible updates</div>
          {note && <div className="mb-2 text-[13px] text-mute">{note}</div>}
          {drafting && (
            <div className="mb-2 rounded-lg border border-accent/30 bg-accent/5 px-3 py-2">
              <div className="mb-1 flex items-center gap-1.5 text-[12.5px] text-mute">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                drafting {drafting.name} — it opens for review when done
              </div>
              <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap font-sans text-[13.5px] text-mute/80">
                {drafting.text}
              </pre>
            </div>
          )}
          <ul className="space-y-1">
            {bibleNames.map((name) => (
              <li key={name} className="flex items-center justify-between rounded-lg border hairline px-2.5 py-1.5">
                <span className="truncate text-[14px] text-ink">{name}</span>
                <Button size="sm" onClick={() => propose(name)} disabled={busy}>
                  Propose update
                </Button>
              </li>
            ))}
            {bibleNames.length === 0 && (
              <li className="text-[13.5px] text-mute/60">No bible files yet.</li>
            )}
          </ul>
        </div>
      </div>
    </Overlay>
  )
}

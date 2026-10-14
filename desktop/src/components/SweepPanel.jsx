import React, { useEffect, useState } from 'react'
import * as api from '../lib/api.js'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Button } from '../ui/Button.jsx'
import DiffOverlay from './DiffOverlay.jsx'

// The CANON SWEEP — a whole-book continuity pass. Streams a read-only audit,
// and can separately propose rewrites of individual bible files, reviewed in
// the same diff overlay as rewrites. Nothing is written until Accept.
export default function SweepPanel({ series, onClose }) {
  const [report, setReport] = useState('')
  const [reportBusy, setReportBusy] = useState(false)
  const [error, setError] = useState('')
  const [bible, setBible] = useState({})          // name → content
  const [proposal, setProposal] = useState(null)  // { name, text }
  const [propBusy, setPropBusy] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .getBible(series.series, series.book)
      .then((b) => alive && setBible(b.files || {}))
      .catch(() => {})
    return () => { alive = false }
  }, [series.series, series.book])

  const runReport = async () => {
    setError('')
    setReport('')
    setReportBusy(true)
    try {
      const full = await api.museSweep({
        series: series.series,
        bookId: series.book,
        target: 'report',
        onDelta: (acc) => setReport(acc)
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
    setProposal({ name, text: '' })
    setPropBusy(true)
    try {
      const full = await api.museSweep({
        series: series.series,
        bookId: series.book,
        target: 'bible',
        bibleName: name,
        onDelta: (acc) => setProposal({ name, text: acc })
      })
      setProposal({ name, text: full })
    } catch (e) {
      setError(e.message || 'bible sweep failed')
      setProposal(null)
    } finally {
      setPropBusy(false)
    }
  }

  const acceptProposal = async () => {
    if (!proposal) return
    try {
      const res = await api.saveBible(series.series, series.book, proposal.name, proposal.text)
      setBible(res.files || {})
    } catch (e) {
      setError(e.message || 'save failed')
    }
    setProposal(null)
  }

  const bibleNames = Object.keys(bible).sort()

  return (
    <>
      <Overlay onClose={onClose} width={760} height="70vh" padTop="8vh" dismissable={!proposal}>
        <div className="flex h-full flex-col">
          <OverlayHeader
            icon="⚑"
            title="Canon sweep"
            onClose={onClose}
            extra={
              <Button variant="accent" size="sm" onClick={runReport} disabled={reportBusy}>
                {reportBusy ? 'sweeping…' : 'Run sweep'}
              </Button>
            }
          />

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            {error && (
              <div className="mb-3 rounded-md border border-err/30 bg-err/10 px-3 py-2 text-[11px] text-err">
                {error}
              </div>
            )}

            <div className="mb-2 text-[9.5px] uppercase tracking-wider text-mute/70">Continuity report</div>
            {report ? (
              <pre className="whitespace-pre-wrap font-sans text-[12.5px] leading-relaxed text-ink/95">{report}</pre>
            ) : (
              <div className="text-[11.5px] text-mute/60">
                {reportBusy
                  ? 'Reading the whole book…'
                  : 'Run a sweep to audit canon, timeline, and character continuity across the manuscript.'}
              </div>
            )}

            <div className="mb-2 mt-5 text-[9.5px] uppercase tracking-wider text-mute/70">Bible updates</div>
            <ul className="space-y-1">
              {bibleNames.map((name) => (
                <li key={name} className="flex items-center justify-between rounded-md border hairline px-2.5 py-1.5">
                  <span className="truncate text-[12px] text-ink">{name}</span>
                  <Button size="sm" onClick={() => propose(name)} disabled={propBusy}>
                    Propose update
                  </Button>
                </li>
              ))}
              {bibleNames.length === 0 && (
                <li className="text-[11.5px] text-mute/60">No bible files yet.</li>
              )}
            </ul>
          </div>
        </div>
      </Overlay>

      {proposal && (
        <DiffOverlay
          showStyles={false}
          original={bible[proposal.name] || ''}
          proposed={proposal.text}
          busy={propBusy}
          onAccept={acceptProposal}
          onRetry={() => propose(proposal.name)}
          onClose={() => setProposal(null)}
        />
      )}
    </>
  )
}

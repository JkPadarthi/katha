import React, { useEffect, useState } from 'react'
import * as api from '../api.js'
import DiffOverlay from './DiffOverlay.jsx'

// The CANON SWEEP — a whole-book continuity pass. It streams a read-only
// audit (contradictions, timeline drift, character inconsistencies), and can
// separately propose rewrites of individual bible files, which the author
// reviews in the same word-diff overlay used for rewrites — nothing is
// written until Accept.
export default function Sweep({ series, onClose }) {
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

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !proposal) onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, proposal])

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

  const bibleNames = Object.keys(bible)

  return (
    <>
      <div
        className="absolute inset-0 z-40 flex items-start justify-center bg-black/60 pt-[8vh]"
        onClick={onClose}
      >
        <div
          onClick={(e) => e.stopPropagation()}
          className="w-[760px] max-w-[92vw] overflow-hidden rounded-lg border hairline bg-panel shadow-2xl shadow-black/60"
        >
          <div className="flex items-center justify-between border-b hairline px-4 py-2.5">
            <div className="flex items-center gap-2">
              <span className="text-[12px] text-gold">⚑</span>
              <span className="text-[12px] font-medium text-ink">Canon sweep</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={runReport}
                disabled={reportBusy}
                className="rounded-md border border-gold/40 px-2.5 py-1 text-[10.5px] font-medium text-gold hover:bg-gold/10 disabled:opacity-40"
              >
                {reportBusy ? 'sweeping…' : 'Run sweep'}
              </button>
              <button onClick={onClose} className="text-[14px] text-mute hover:text-ink" title="Close (Esc)">
                ×
              </button>
            </div>
          </div>

          <div className="max-h-[62vh] overflow-y-auto px-4 py-3">
            {error && (
              <div className="mb-3 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-300">
                {error}
              </div>
            )}

            <div className="mb-2 text-[9.5px] uppercase tracking-wider text-mute/70">
              Continuity report
            </div>
            {report ? (
              <pre className="whitespace-pre-wrap font-sans text-[12.5px] leading-relaxed text-ink/95">{report}</pre>
            ) : (
              <div className="text-[11.5px] text-mute/60">
                {reportBusy
                  ? 'Reading the whole book…'
                  : 'Run a sweep to audit canon, timeline, and character continuity across the manuscript.'}
              </div>
            )}

            <div className="mb-2 mt-5 text-[9.5px] uppercase tracking-wider text-mute/70">
              Bible updates
            </div>
            <ul className="space-y-1">
              {bibleNames.map((name) => (
                <li
                  key={name}
                  className="flex items-center justify-between rounded-md border hairline px-2.5 py-1.5"
                >
                  <span className="text-[12px] text-ink">{name}</span>
                  <button
                    onClick={() => propose(name)}
                    disabled={propBusy}
                    className="rounded border hairline px-2 py-0.5 text-[10.5px] text-mute hover:text-gold disabled:opacity-40"
                  >
                    Propose update
                  </button>
                </li>
              ))}
              {bibleNames.length === 0 && (
                <li className="text-[11.5px] text-mute/60">No bible files yet.</li>
              )}
            </ul>
          </div>
        </div>
      </div>

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

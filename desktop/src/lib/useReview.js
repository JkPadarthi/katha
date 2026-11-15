import { useState } from 'react'
import * as api from './api.js'
import { museApi } from './useMuse.js'

// The review of what the Muse staged (2.9 → 3.1 → 4.0). Nothing is written until the
// author accepts; accepting is a normal save on the server (revision snapshot and all).
// `landSaved(saved)` puts a saved file back where the author sees it.
export function useReview({ series, landSaved, refreshArchive }) {
  const [proposal, setProposal] = useState(null)
  const [busy, setBusy] = useState(false)

  const pendingInBook = async () => {
    try {
      const r = await api.listProposals()
      return (r.proposals || []).filter((p) => series && p.series === series.series && p.book === series.book)
    } catch {
      return []
    }
  }

  // Open a staged change: the text the Muse was looking at (`base_content`), the hunks
  // cut from it, and every other file waiting in this book.
  const open = async (id) => {
    if (!series) return
    try {
      const [p, siblings] = await Promise.all([api.getProposal(id), pendingInBook()])
      setProposal({
        id,
        kind: p.kind || 'chapter',
        path: p.path || '',
        chapter: p.chapter || '',
        original: p.base_content ?? '',
        hunks: p.hunks || [],
        stale: !!p.stale,
        dropped: p.dropped || [],
        siblings
      })
    } catch {
      setProposal(null)   // gone or unreadable: no half-open review
      museApi.refreshPending?.()
    }
  }

  // After a decision: stay on the file if hunks remain, else the next file waiting, else close.
  const after = async (id) => {
    const left = await pendingInBook()
    museApi.refreshPending?.()
    const next = left.find((p) => p.id === id) || left[0]
    if (next && proposal) await open(next.id)
    else setProposal(null)
  }

  // `ids` narrows it to the changes the author ticked; the rest stay pending.
  const accept = async (ids = null) => {
    if (!proposal) return
    setBusy(true)
    try {
      landSaved(await api.acceptProposal(proposal.id, ids))
      await after(proposal.id)
      await refreshArchive()
    } catch {
      /* leave the review open — the author can accept again */
    } finally {
      setBusy(false)
    }
  }

  // Every file waiting in this book, whole — from the review or straight from the dock.
  const acceptAll = async () => {
    setBusy(true)
    try {
      for (const p of await pendingInBook()) {
        if (p.stale) continue
        try { landSaved(await api.acceptProposal(p.id, null)) } catch { /* keep going */ }
      }
      await after(proposal?.id)
      await refreshArchive()
    } finally {
      setBusy(false)
    }
  }

  const discard = async () => {
    if (!proposal) return
    try { await api.discardProposal(proposal.id) } catch { /* gone is gone */ }
    await after(proposal.id)
  }

  return { proposal, busy, open, accept, acceptAll, discard, close: () => setProposal(null) }
}

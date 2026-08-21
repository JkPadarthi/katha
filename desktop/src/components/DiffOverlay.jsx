import React, { useEffect, useMemo, useState } from 'react'
import { diffWordsWithSpace } from 'diff'

// THE FLAGSHIP — word-level diff between the user's original selection and the
// Muse's proposed rewrite. Accept writes the proposed text into the Page;
// Retry re-calls museRewrite with the same selection; Style cycles the
// rewrite prompt (novel → scene → clean → novel…).

const STYLES = ['novel', 'scene', 'clean']

export default function DiffOverlay({
  original,
  proposed,
  busy,
  onAccept,
  onRetry,
  onClose,
  style,
  onStyleChange
}) {
  // Word-level diff with whitespace preserved (so spaces between words show
  // up correctly).
  const parts = useMemo(() => diffWordsWithSpace(original || '', proposed || ''), [original, proposed])
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) onAccept()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onAccept, onClose])

  const copyProposed = async () => {
    try {
      await navigator.clipboard.writeText(proposed || '')
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard might be blocked; ignore */ }
  }

  return (
    <div
      className="absolute inset-0 z-40 flex items-start justify-center bg-black/60 pt-[10vh]"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-[760px] max-w-[92vw] overflow-hidden rounded-lg border hairline bg-panel shadow-2xl shadow-black/60"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b hairline px-4 py-2.5">
          <div className="flex items-center gap-2">
            <span className="text-[12px] text-gold">✎</span>
            <span className="text-[12px] font-medium text-ink">Rewrite</span>
            {busy && (
              <span className="ml-2 flex items-center gap-1.5 text-[10.5px] text-mute">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-gold" />
                streaming
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex gap-0.5 rounded-md border hairline p-0.5">
              {STYLES.map((s) => (
                <button
                  key={s}
                  onClick={() => onStyleChange(s)}
                  disabled={busy}
                  className={
                    'rounded-sm px-2 py-0.5 text-[10.5px] transition-colors ' +
                    (style === s
                      ? 'bg-gold/20 text-gold'
                      : 'text-mute hover:text-ink disabled:opacity-40')
                  }
                >
                  {s}
                </button>
              ))}
            </div>
            <button
              onClick={onClose}
              className="text-[14px] text-mute hover:text-ink"
              title="Close (Esc)"
            >
              ×
            </button>
          </div>
        </div>

        {/* Diff body — side-by-side: original | proposed, with inline word-level marks */}
        <div className="grid grid-cols-2 gap-px bg-hairline">
          <div className="bg-panel-2 px-4 py-3">
            <div className="mb-1.5 text-[9.5px] uppercase tracking-wider text-mute/70">original</div>
            <div className="font-serif text-[14px] leading-[1.7] text-mute">
              {parts.map((p, i) =>
                p.removed ? (
                  <span key={i} className="bg-red-500/15 text-red-300 line-through decoration-red-400/40">
                    {p.value}
                  </span>
                ) : p.added ? null : (
                  <span key={i}>{p.value}</span>
                )
              )}
            </div>
          </div>
          <div className="bg-base px-4 py-3">
            <div className="mb-1.5 text-[9.5px] uppercase tracking-wider text-mute/70">proposed</div>
            <div className="font-serif text-[14px] leading-[1.7] text-ink">
              {parts.map((p, i) =>
                p.added ? (
                  <span key={i} className="rounded-[2px] bg-gold/20 text-gold">
                    {p.value}
                  </span>
                ) : p.removed ? null : (
                  <span key={i}>{p.value}</span>
                )
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t hairline px-4 py-2.5">
          <div className="flex items-center gap-2">
            <button
              onClick={copyProposed}
              disabled={!proposed || busy}
              className="rounded border hairline px-2.5 py-1 text-[10.5px] text-mute hover:text-ink disabled:opacity-40"
            >
              {copied ? '✓ copied' : 'copy proposed'}
            </button>
            <span className="text-[10px] text-mute/60">
              Esc to dismiss · Ctrl/⌘+Enter to accept
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onRetry}
              disabled={busy}
              className="rounded border hairline px-3 py-1 text-[11px] text-mute hover:text-ink disabled:opacity-40"
            >
              Retry
            </button>
            <button
              onClick={onAccept}
              disabled={!proposed || busy}
              className="rounded-md bg-gold px-3 py-1 text-[11px] font-semibold text-base hover:brightness-110 disabled:opacity-40"
            >
              Accept
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

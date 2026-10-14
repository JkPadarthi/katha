import React, { useEffect, useMemo, useState } from 'react'
import { diffWordsWithSpace } from 'diff'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Button } from '../ui/Button.jsx'

// Word-level diff between the author's selection and the Muse's proposal.
// Accept writes the proposal into the editor; Retry re-calls rewrite; the style
// toggle switches the rewrite prompt. `showStyles=false` reuses this shell for
// the bible-diff approval in the canon sweep.

const STYLES = ['novel', 'scene', 'clean']

export default function DiffOverlay({
  original,
  proposed,
  busy,
  onAccept,
  onRetry,
  onClose,
  style,
  onStyleChange,
  showStyles = true
}) {
  const parts = useMemo(() => diffWordsWithSpace(original || '', proposed || ''), [original, proposed])
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) onAccept()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onAccept])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(proposed || '')
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard may be blocked */ }
  }

  return (
    <Overlay onClose={onClose} width={780} padTop="10vh">
      <OverlayHeader
        icon="✎"
        title="Rewrite"
        onClose={onClose}
        extra={
          showStyles ? (
            <div className="flex gap-0.5 rounded-md border hairline p-0.5">
              {STYLES.map((s) => (
                <button
                  key={s}
                  onClick={() => onStyleChange(s)}
                  disabled={busy}
                  className={
                    'rounded-sm px-2 py-0.5 text-[10.5px] transition-colors ' +
                    (style === s ? 'bg-accent/20 text-accent' : 'text-mute hover:text-ink disabled:opacity-40')
                  }
                >
                  {s}
                </button>
              ))}
            </div>
          ) : busy ? (
            <span className="flex items-center gap-1.5 text-[10.5px] text-mute">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
              streaming
            </span>
          ) : null
        }
      />

      {/* Side-by-side word-level diff */}
      <div className="grid grid-cols-2 gap-px bg-line">
        <div className="bg-panel-2 px-4 py-3">
          <div className="mb-1.5 text-[9.5px] uppercase tracking-wider text-mute/70">original</div>
          <div className="font-serif text-[14px] leading-[1.7] text-mute">
            {parts.map((p, i) =>
              p.removed
                ? <span key={i} className="bg-err/15 text-err line-through">{p.value}</span>
                : p.added ? null : <span key={i}>{p.value}</span>
            )}
          </div>
        </div>
        <div className="bg-base px-4 py-3">
          <div className="mb-1.5 text-[9.5px] uppercase tracking-wider text-mute/70">proposed</div>
          <div className="font-serif text-[14px] leading-[1.7] text-ink">
            {parts.map((p, i) =>
              p.added
                ? <span key={i} className="rounded-[2px] bg-accent/20 text-accent">{p.value}</span>
                : p.removed ? null : <span key={i}>{p.value}</span>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between border-t hairline px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={copy} disabled={!proposed || busy}>
            {copied ? '✓ copied' : 'copy proposed'}
          </Button>
          <span className="text-[10px] text-mute/60">Esc to dismiss · Ctrl/⌘+Enter to accept</span>
        </div>
        <div className="flex items-center gap-2">
          <Button size="md" onClick={onRetry} disabled={busy}>Retry</Button>
          <Button variant="primary" onClick={onAccept} disabled={!proposed || busy}>Accept</Button>
        </div>
      </div>
    </Overlay>
  )
}

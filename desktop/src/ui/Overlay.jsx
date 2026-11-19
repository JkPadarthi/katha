import React, { useEffect } from 'react'
import Icon from './Icon.jsx'

// One modal shell for every panel (4.0): a backdrop, Esc + backdrop-click to close,
// and a sized card. On a phone every panel is a full-screen sheet — the same content,
// never a squeezed desktop dialog. `dismissable` guards accidental closes (mid-save).
export default function Overlay({
  children,
  onClose,
  width = 760,
  height,
  align = 'start',      // 'start' (top) | 'center'
  padTop = '10vh',
  z = 40,
  dismissable = true,
  label
}) {
  useEffect(() => {
    if (!dismissable) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, dismissable])

  return (
    <div
      className="absolute inset-0 flex justify-center bg-black/40 backdrop-blur-[1px] max-md:pt-0!"
      style={{
        alignItems: align === 'start' ? 'flex-start' : 'center',
        paddingTop: align === 'start' ? padTop : undefined,
        zIndex: z
      }}
      onMouseDown={dismissable ? onClose : undefined}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={label}
        onMouseDown={(e) => e.stopPropagation()}
        className="float sheet-in flex flex-col overflow-hidden rounded-2xl max-md:h-full! max-md:max-h-none! max-md:w-full! max-md:max-w-none! max-md:rounded-none max-md:border-0"
        style={{
          width,
          maxWidth: '94vw',
          maxHeight: align === 'start' ? `calc(100% - ${padTop} - 3vh)` : '92%',
          paddingTop: 'env(safe-area-inset-top)',
          ...(height ? { height } : {})
        }}
      >
        {children}
      </div>
    </div>
  )
}

// Shared panel header: a title, optional extras, and a close button.
export function OverlayHeader({ icon, title, extra, onClose }) {
  return (
    <div className="flex min-h-14 shrink-0 flex-wrap items-center justify-between gap-2 border-b hairline px-5 py-2">
      <div className="flex min-w-0 items-center gap-2.5">
        {icon && <span className="text-[14px] text-accent" aria-hidden="true">{icon}</span>}
        <h2 className="truncate text-[15px] font-semibold text-ink">{title}</h2>
      </div>
      <div className="flex items-center gap-2">
        {extra}
        <button
          onClick={onClose}
          aria-label="Close"
          title="Close (Esc)"
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-mute hover:bg-panel-2 hover:text-ink"
        >
          <Icon name="x" />
        </button>
      </div>
    </div>
  )
}

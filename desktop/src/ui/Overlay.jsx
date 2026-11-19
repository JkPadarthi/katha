import React, { useEffect } from 'react'

// One modal shell for every panel: a backdrop, Esc + backdrop-click to close,
// and a sized card. `dismissable` guards accidental closes (e.g. mid-save).
export default function Overlay({
  children,
  onClose,
  width = 760,
  height,
  align = 'start',      // 'start' (top) | 'center'
  padTop = '10vh',
  z = 40,
  dismissable = true
}) {
  useEffect(() => {
    if (!dismissable) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, dismissable])

  return (
    <div
      className="absolute inset-0 flex justify-center bg-black/55"
      style={{
        alignItems: align === 'start' ? 'flex-start' : 'center',
        paddingTop: align === 'start' ? padTop : undefined,
        zIndex: z
      }}
      onMouseDown={dismissable ? onClose : undefined}
    >
      <div
        onMouseDown={(e) => e.stopPropagation()}
        className="overflow-hidden rounded-lg border hairline bg-panel shadow-2xl shadow-black/50"
        style={{ width, maxWidth: '94vw', ...(height ? { height } : {}) }}
      >
        {children}
      </div>
    </div>
  )
}

// Shared panel header: an icon, a title, optional extras, and a close button.
export function OverlayHeader({ icon, title, extra, onClose }) {
  return (
    <div className="flex items-center justify-between border-b hairline px-4 py-2.5">
      <div className="flex items-center gap-2">
        {icon && <span className="text-[12px] text-accent">{icon}</span>}
        <span className="text-[12px] font-medium text-ink">{title}</span>
      </div>
      <div className="flex items-center gap-2">
        {extra}
        <button
          onClick={onClose}
          className="text-[15px] leading-none text-mute hover:text-ink"
          title="Close (Esc)"
        >
          ×
        </button>
      </div>
    </div>
  )
}

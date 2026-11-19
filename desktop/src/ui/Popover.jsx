import React, { useEffect, useRef } from 'react'

// A menu anchored under a button on desktop, a bottom sheet on a phone (4.0).
// Closes on Esc, on a click outside, and (via the caller) when an item is picked.
export default function Popover({ open, onClose, align = 'left', width = 340, children, label }) {
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target) && !e.target.closest?.('[data-popover-anchor]')) onClose()
    }
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    document.addEventListener('mousedown', onDoc)
    window.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      window.removeEventListener('keydown', onKey, true)
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30 md:hidden" aria-hidden="true" />
      <div
        ref={ref}
        role="dialog"
        aria-label={label}
        className={
          'float sheet-in z-50 flex flex-col overflow-hidden ' +
          // phone: a bottom sheet
          'fixed inset-x-0 bottom-0 max-h-[85dvh] rounded-t-2xl pb-[env(safe-area-inset-bottom)] ' +
          // desktop: anchored under the trigger
          'md:absolute md:inset-x-auto md:bottom-auto md:top-[calc(100%+6px)] md:max-h-[75vh] md:rounded-xl md:pb-0 ' +
          (align === 'right' ? 'md:right-0' : 'md:left-0')
        }
        style={{ '--pw': `${width}px` }}
      >
        <div className="md:w-[var(--pw)] flex min-h-0 flex-1 flex-col">{children}</div>
      </div>
    </>
  )
}

export function MenuItem({ icon, children, hint, onClick, active = false, danger = false, disabled = false }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={
        'flex min-h-10 w-full items-center gap-3 rounded-lg px-3 text-left text-[14px] transition-colors disabled:opacity-40 max-md:min-h-12 ' +
        (active ? 'bg-accent/10 text-ink ' : danger ? 'text-err hover:bg-err/10 ' : 'text-ink hover:bg-panel-2 ')
      }
    >
      {icon}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {hint && <span className="shrink-0 text-[12px] text-mute">{hint}</span>}
    </button>
  )
}

export function MenuLabel({ children, action }) {
  return (
    <div className="flex items-center justify-between px-3 pb-1 pt-3 text-[12px] font-medium text-mute">
      <span>{children}</span>
      {action}
    </div>
  )
}

export function MenuDivider() {
  return <div className="mx-2 my-1.5 h-px bg-line" />
}

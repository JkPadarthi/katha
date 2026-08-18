import React from 'react'

// Hermes-style frameless chrome: a quiet strip, the gold ● as the brand
// mark (a nod to the seed), and window controls that work in Electron.
export default function TitleBar() {
  const k = window.katha

  return (
    <div className="titlebar flex h-9 shrink-0 items-center justify-between border-b hairline bg-base px-3">
      <div className="flex items-center gap-2">
        <span className="text-gold text-[10px]">●</span>
        <span className="text-[11px] font-medium tracking-wide text-mute">Katha</span>
      </div>

      <div className="hidden text-[11px] text-mute/70 select-none md:block">
        {k?.isElectron ? 'desktop' : 'browser preview'} · Phase 0.1
      </div>

      <div className="flex items-center gap-1">
        <button
          onClick={() => k?.minimize()}
          className="flex h-6 w-8 items-center justify-center rounded text-mute hover:bg-panel-2 hover:text-ink"
          title="Minimize"
        >
          <span className="text-[10px]">─</span>
        </button>
        <button
          onClick={() => k?.maximize()}
          className="flex h-6 w-8 items-center justify-center rounded text-mute hover:bg-panel-2 hover:text-ink"
          title="Maximize"
        >
          <span className="text-[10px]">□</span>
        </button>
        <button
          onClick={() => k?.close()}
          className="flex h-6 w-8 items-center justify-center rounded text-mute hover:bg-err/80 hover:text-white"
          title="Close"
        >
          <span className="text-[10px]">✕</span>
        </button>
      </div>
    </div>
  )
}
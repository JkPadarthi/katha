import React from 'react'

// Settings — per-machine prefs in localStorage. Deliberately small: the
// server address is gone (the PWA is same-origin), so this is just the
// writing-ritual goal and the optional proactive nudge.
export default function Settings({ goal, onGoal, nudge, onNudge, onClose }) {
  return (
    <div
      className="absolute inset-0 z-50 flex items-start justify-center bg-black/50 pt-[16vh]"
      onMouseDown={onClose}
    >
      <div
        onMouseDown={(e) => e.stopPropagation()}
        className="w-[440px] max-w-[92vw] overflow-hidden rounded-lg border hairline bg-panel shadow-2xl shadow-black/60"
      >
        <div className="flex items-center justify-between border-b hairline px-4 py-2.5">
          <span className="text-[12px] font-medium text-ink">Settings</span>
          <button onClick={onClose} className="text-[14px] text-mute hover:text-ink" title="Close">
            ×
          </button>
        </div>

        <div className="space-y-4 px-4 py-4">
          <label className="block">
            <span className="text-[11px] text-mute">Daily word goal</span>
            <input
              type="number"
              min="0"
              value={goal}
              onChange={(e) => onGoal(e.target.value)}
              placeholder="500"
              className="mt-1 w-full rounded-md border hairline bg-base px-2.5 py-1.5 text-[12.5px] text-ink placeholder:text-mute/50 focus:outline-none focus:ring-1 focus:ring-gold/50"
            />
            <span className="mt-1 block text-[10px] text-mute/60">
              Drives the streak in the rail. Blank uses the server default.
            </span>
          </label>

          <label className="flex items-center justify-between gap-4">
            <span className="text-[11px] text-mute">
              Proactive nudge
              <span className="mt-0.5 block text-[10px] text-mute/60">
                After a few quiet minutes, offer to have the Muse continue.
              </span>
            </span>
            <input
              type="checkbox"
              checked={!!nudge}
              onChange={(e) => onNudge(e.target.checked)}
              className="h-4 w-4 shrink-0 accent-gold"
            />
          </label>
        </div>
      </div>
    </div>
  )
}

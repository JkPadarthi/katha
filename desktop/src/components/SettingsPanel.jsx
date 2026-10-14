import React from 'react'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Field, TextInput } from '../ui/Field.jsx'

// Per-machine preferences (localStorage). The theme lives in the title-bar
// picker; this is the daily goal and the optional proactive nudge.
export default function SettingsPanel({ goal, onGoal, nudge, onNudge, onClose }) {
  return (
    <Overlay onClose={onClose} width={460} padTop="16vh" z={50}>
      <OverlayHeader title="Settings" onClose={onClose} />
      <div className="space-y-4 px-4 py-4">
        <Field label="Daily word goal" hint="Drives the streak in the rail. Blank uses the server default.">
          <TextInput
            type="number"
            min="0"
            value={goal}
            onChange={(e) => onGoal(e.target.value)}
            placeholder="500"
          />
        </Field>

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
            className="h-4 w-4 shrink-0 accent-accent"
          />
        </label>
      </div>
    </Overlay>
  )
}

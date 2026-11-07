import React, { useEffect, useState } from 'react'
import * as api from '../lib/api.js'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Field, TextInput } from '../ui/Field.jsx'
import { Button } from '../ui/Button.jsx'

// Per-machine preferences (localStorage), plus the archive's trash.
//
// The trash is the other half of delete (D33): anything removed from the rail
// waits here and can be put back exactly where it came from — every chapter file,
// revision snapshot, notes sidecar and Muse thread. Restoring refuses rather than
// overwrite a chapter that has since taken the same id, and says so.

const size = (n) =>
  n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`

const when = (iso) => (iso || '').replace('T', ' ').replace('Z', ' UTC')

export default function SettingsPanel({ goal, onGoal, nudge, onNudge, onClose, onRestored }) {
  const [trash, setTrash] = useState(null)     // null = still reading
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const load = async () => {
    try {
      const data = await api.listTrash()
      setTrash(data.entries || [])
    } catch (e) {
      setError(e.message || 'could not read the trash')
      setTrash([])
    }
  }

  useEffect(() => { load() }, [])

  const restore = async (entry) => {
    setBusy(entry)
    setError('')
    try {
      await api.restoreTrash(entry)
      await load()
      if (onRestored) await onRestored()
    } catch (e) {
      setError(e.message || 'could not restore that')
    } finally {
      setBusy('')
    }
  }

  return (
    <Overlay onClose={onClose} width={520} padTop="14vh" z={50}>
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

        {/* Trash — the revive half of delete */}
        <div className="border-t hairline pt-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-mute">Trash</span>
            {trash && trash.length > 0 && (
              <span className="text-[10px] text-mute/60">
                {trash.length} item{trash.length === 1 ? '' : 's'}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[10px] text-mute/60">
            Deleted chapters and books wait here. Restoring puts every file back where
            it was — nothing is ever erased.
          </p>

          <div className="mt-2 max-h-56 space-y-1 overflow-y-auto">
            {trash === null && <p className="text-[11px] text-mute/60">Reading the trash…</p>}
            {trash?.length === 0 && <p className="text-[11px] text-mute/60">Nothing in the trash.</p>}
            {(trash || []).map((e) => (
              <div
                key={e.entry}
                className="flex items-center gap-2 rounded-md border hairline bg-panel-2 px-2 py-1.5"
              >
                <span className="shrink-0 rounded border hairline px-1 text-[9.5px] uppercase tracking-wide text-mute/70">
                  {e.kind}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[11.5px] text-ink">{e.label}</span>
                  <span className="block truncate text-[10px] text-mute/60">
                    {e.series}/{e.book_id}
                    {e.chapter_id ? `/${e.chapter_id}` : ''} · {when(e.deleted_at)} ·{' '}
                    {e.files} file{e.files === 1 ? '' : 's'}, {size(e.bytes)}
                  </span>
                </span>
                <Button
                  size="sm"
                  variant="accent"
                  onClick={() => restore(e.entry)}
                  disabled={!!busy}
                  title="Put it back in the archive"
                >
                  {busy === e.entry ? 'Restoring…' : 'Restore'}
                </Button>
              </div>
            ))}
          </div>

          {error && <p className="mt-2 text-[11px] text-err">{error}</p>}
        </div>
      </div>
    </Overlay>
  )
}

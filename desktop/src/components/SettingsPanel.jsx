import React, { useEffect, useState } from 'react'
import * as api from '../lib/api.js'
import { signOut } from '../lib/api.js'
import { THEMES } from '../lib/useTheme.js'
import { Swatch } from './ThemePicker.jsx'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Field, TextInput } from '../ui/Field.jsx'
import { Button } from '../ui/Button.jsx'

// Per-machine preferences (localStorage), plus the archive's trash — and the two
// controls that belong here because they were only reachable from the title bar:
// the theme (a small popover up there) and the lock (hidden entirely on narrow
// screens, so a phone had no way to lock the archive at all).
//
// The trash is the other half of delete (D33): anything removed from the rail
// waits here and can be put back exactly where it came from — every chapter file,
// revision snapshot, notes sidecar and Muse thread. Restoring refuses rather than
// overwrite a chapter that has since taken the same id, and says so.

const size = (n) =>
  n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`

const when = (iso) => (iso || '').replace('T', ' ').replace('Z', ' UTC')

export default function SettingsPanel({ goal, onGoal, nudge, onNudge, onClose, onRestored, theme, onChooseTheme }) {
  const [trash, setTrash] = useState(null)     // null = still reading
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [confirmPurge, setConfirmPurge] = useState(null)   // entry id, or '*' for all

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

  // Erasing for real (D36). Delete is a move; this is the second, deliberate
  // step — so it always goes through the red confirm strip above the list.
  const purge = async (entry) => {
    setBusy(entry)
    setError('')
    try {
      if (entry === '*') await api.emptyTrash()
      else await api.purgeTrash(entry)
      setConfirmPurge(null)
      await load()
    } catch (e) {
      setError(e.message || 'could not erase that')
    } finally {
      setBusy('')
    }
  }

  return (
    <Overlay onClose={onClose} width={520} padTop="14vh" z={50}>
      <OverlayHeader title="Settings" onClose={onClose} />
      <div className="space-y-4 px-4 py-4">
        {/* Theme — the same choice as the title-bar picker, but somewhere it can
            be found (and reached on a phone). */}
        <div>
          <span className="text-[11px] text-mute">Theme</span>
          <div className="mt-1.5 flex gap-1.5">
            {THEMES.map((t) => (
              <button
                key={t.id}
                onClick={() => onChooseTheme(t.id)}
                title={t.hint}
                className={
                  'flex flex-1 items-center gap-1.5 rounded-md border px-2 py-1.5 text-left text-[11px] transition-colors ' +
                  (t.id === theme
                    ? 'border-accent/50 bg-panel-2 text-ink'
                    : 'hairline text-mute hover:bg-panel-2/60 hover:text-ink')
                }
              >
                <Swatch id={t.id} />
                <span className="min-w-0 flex-1 truncate">{t.label}</span>
                {t.id === theme && <span className="text-[9.5px] text-accent">✓</span>}
              </button>
            ))}
          </div>
          <p className="mt-1 text-[10px] text-mute/60">
            Follows the system until you choose one here; then it sticks on this device.
          </p>
        </div>

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
            <span className="flex items-center gap-2">
              {trash && trash.length > 0 && (
                <span className="text-[10px] text-mute/60">
                  {trash.length} item{trash.length === 1 ? '' : 's'}
                </span>
              )}
              {trash && trash.length > 0 && (
                <Button
                  size="sm"
                  onClick={() => setConfirmPurge('*')}
                  disabled={!!busy}
                  title="Erase everything in the trash — not recoverable"
                >
                  Empty trash
                </Button>
              )}
            </span>
          </div>
          <p className="mt-0.5 text-[10px] text-mute/60">
            Deleted chapters, books, bible files and whole series wait here. Restoring
            puts every file back where it was. Erasing is the only thing in Katha that
            destroys anything — and it asks first.
          </p>

          {confirmPurge && (
            <div className="mt-2 rounded-md border border-err/40 bg-err/5 px-2 py-2">
              <p className="text-[10.5px] text-ink">
                {confirmPurge === '*'
                  ? 'Erase everything in the trash for good?'
                  : 'Erase this entry for good?'}
                <span className="mt-0.5 block text-[10px] text-mute/70">
                  It will no longer be possible to restore.
                </span>
              </p>
              <div className="mt-1.5 flex justify-end gap-2">
                <Button size="sm" onClick={() => setConfirmPurge(null)} disabled={!!busy}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={() => purge(confirmPurge)}
                  disabled={!!busy}
                  className="border border-err/50 text-err hover:bg-err/10"
                >
                  {busy ? 'Erasing…' : confirmPurge === '*' ? 'Erase everything' : 'Erase for good'}
                </Button>
              </div>
            </div>
          )}

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
                <button
                  onClick={() => { setError(''); setConfirmPurge(e.entry) }}
                  disabled={!!busy}
                  title="Erase for good — not recoverable"
                  aria-label={`Erase ${e.label}`}
                  className="shrink-0 rounded px-1 py-0.5 text-[11px] leading-none text-mute/40 transition-colors hover:text-err disabled:opacity-40"
                >
                  ×
                </button>
              </div>
            ))}
          </div>

          {error && <p className="mt-2 text-[11px] text-err">{error}</p>}
        </div>

        {/* The door, from the inside. Same call as the title bar's `lock`. */}
        <div className="border-t hairline pt-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-mute">Session</span>
            <span className="text-[10px] text-mute/50">v{__APP_VERSION__}</span>
          </div>
          <p className="mt-0.5 text-[10px] text-mute/60">
            Katha sits behind one password. Locking signs this browser out — the
            archive asks for it again, and nothing is lost.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <Button size="sm" onClick={signOut} title="Sign out and lock the archive">
              Lock now
            </Button>
            <span className="text-[10px] text-mute/50">the same as lock in the title bar</span>
          </div>
        </div>
      </div>
    </Overlay>
  )
}

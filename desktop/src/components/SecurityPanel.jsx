import React, { useEffect, useState } from 'react'
import * as api from '../lib/api.js'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Field, TextInput } from '../ui/Field.jsx'
import { Button } from '../ui/Button.jsx'

// MUSE & SECURITY (3.2, D62) — the two settings that used to need SSH and an env file:
// which brain the Muse talks to (dialect, address, key, models) and the lock's
// password. Both are stored on the server, take effect immediately, and ask for the
// current password while the lock is on. The key is write-only: the server only
// ever says whether one is set and shows its last four characters.

const DIALECTS = {
  ollama: { label: 'Ollama (LAN)', base: 'http://100.x.y.z:11434', keyed: false },
  openai: { label: 'OpenAI-compatible gateway', base: 'https://openrouter.ai/api/v1', keyed: true },
  messages: { label: 'Messages gateway (Claude)', base: 'https://gateway.example/v1', keyed: true }
}

const Note = ({ kind = 'info', children }) => (
  <div
    className={
      'rounded-md border px-3 py-2 text-[11px] ' +
      (kind === 'err' ? 'border-err/30 bg-err/10 text-err'
        : kind === 'ok' ? 'border-ok/30 bg-ok/10 text-ink'
        : 'border-accent/30 bg-accent/5 text-ink')
    }
  >
    {children}
  </div>
)

// A titled group for more than one control. `Field` is a <label>, which names only its
// first control with *all* of its text — three provider buttons inside one read as a
// single button called "Provider Ollama OpenAI Messages" to a screen reader.
const Group = ({ label, hint, children }) => (
  <div role="group" aria-label={label}>
    <span className="text-[11px] text-mute">{label}</span>
    <div className="mt-1">{children}</div>
    {hint && <span className="mt-1 block text-[10px] text-mute/60">{hint}</span>}
  </div>
)

export default function SecurityPanel({ onClose }) {
  const [s, setS] = useState(null)              // server's view of the settings
  const [form, setForm] = useState(null)        // the Muse form
  const [current, setCurrent] = useState('')    // current password (shared by both forms)
  const [busy, setBusy] = useState('')
  const [museMsg, setMuseMsg] = useState(null)  // {kind, text}
  const [pw, setPw] = useState({ next: '', again: '' })
  const [pwMsg, setPwMsg] = useState(null)
  const [confirmOff, setConfirmOff] = useState(false)

  const adopt = (data) => {
    setS(data)
    setForm({
      api: data.muse.api,
      base: data.muse.base,
      key: '',
      removeKey: false,
      // The models in use now — so saving without touching them keeps them, even
      // when they came from the environment.
      agentModel: data.muse.agent_model,
      rewriteModel: data.muse.rewrite_model
    })
  }

  useEffect(() => {
    api.getSettings().then(adopt).catch((e) => setMuseMsg({ kind: 'err', text: e.message }))
  }, [])

  if (!s || !form) {
    return (
      <Overlay onClose={onClose} width={560} padTop="8vh" z={55}>
        <OverlayHeader icon="⚿" title="Muse & security" onClose={onClose} />
        <div className="px-4 py-6 text-[11.5px] text-mute">{museMsg?.text || 'Loading…'}</div>
      </Overlay>
    )
  }

  const locked = s.lock.enabled
  const d = DIALECTS[form.api] || DIALECTS.ollama
  const set = (patch) => setForm((f) => ({ ...f, ...patch }))

  const saveMuse = async () => {
    setBusy('muse')
    setMuseMsg(null)
    try {
      const out = await api.saveMuseSettings({
        api: form.api,
        base: form.base,
        key: form.removeKey ? '' : (form.key.trim() ? form.key.trim() : null),
        agentModel: form.agentModel,
        rewriteModel: form.rewriteModel,
        currentPassword: current
      })
      adopt(out)
      // Saved — now prove it, so a typo shows up here and not mid-chapter.
      const t = await api.testMuseConnection()
      setMuseMsg(t.ok
        ? { kind: 'ok', text: `Saved. ${t.model} answered: “${t.reply || '…'}”${out.note ? ' — ' + out.note : ''}` }
        : { kind: 'err', text: `Saved, but the connection test failed: ${t.detail}${out.note ? ' — ' + out.note : ''}` })
    } catch (e) {
      setMuseMsg({ kind: 'err', text: e.message })
    } finally {
      setBusy('')
    }
  }

  const testMuse = async () => {
    setBusy('test')
    setMuseMsg(null)
    try {
      const t = await api.testMuseConnection()
      setMuseMsg(t.ok
        ? { kind: 'ok', text: `${t.model} answered: “${t.reply || '…'}”` }
        : { kind: 'err', text: t.detail })
    } catch (e) {
      setMuseMsg({ kind: 'err', text: e.message })
    } finally {
      setBusy('')
    }
  }

  const resetMuse = async () => {
    setBusy('reset')
    setMuseMsg(null)
    try {
      adopt(await api.resetMuseSettings(current))
      setMuseMsg({ kind: 'info', text: 'Back to the server’s environment settings.' })
    } catch (e) {
      setMuseMsg({ kind: 'err', text: e.message })
    } finally {
      setBusy('')
    }
  }

  const savePassword = async (disable = false) => {
    setPwMsg(null)
    if (!disable) {
      if (pw.next.length < 8) return setPwMsg({ kind: 'err', text: 'Use at least 8 characters.' })
      if (pw.next !== pw.again) return setPwMsg({ kind: 'err', text: 'The two new passwords don’t match.' })
    }
    setBusy('pw')
    try {
      const out = await api.changePassword({ current, next: pw.next, disable })
      setS(out)
      setPw({ next: '', again: '' })
      setCurrent('')
      setConfirmOff(false)
      setPwMsg(disable
        ? { kind: 'info', text: 'The lock is off. Anyone who can reach this server can open the archive.' }
        : { kind: 'ok', text: locked
            ? 'Password changed. Every other device has been signed out; this one stays in.'
            : 'Password set — the archive is locked. This device stays signed in.' })
    } catch (e) {
      setPwMsg({ kind: 'err', text: e.message })
    } finally {
      setBusy('')
    }
  }

  return (
    <Overlay onClose={onClose} width={580} height="86vh" padTop="6vh" z={55} dismissable={!busy}>
      <div className="flex h-full flex-col">
        <OverlayHeader icon="⚿" title="Muse & security" onClose={onClose} />
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4">
          {locked ? (
            <Field label="Your current password"
                   hint="Needed to change anything on this page — it decides where your manuscript is sent and who can open it.">
              <TextInput type="password" autoComplete="current-password" value={current}
                         onChange={(e) => setCurrent(e.target.value)} />
            </Field>
          ) : (
            <Note kind="err">
              The archive has no password, so anyone who can reach this server can read it
              and change these settings. Set one below.
            </Note>
          )}

          {/* --- the Muse's brain --- */}
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[9.5px] uppercase tracking-wider text-mute/70">The Muse’s brain</span>
              <span className="text-[10px] text-mute/60">
                {s.muse.source === 'app' ? 'set in the app' : 'from the server’s environment'}
              </span>
            </div>

            <Group label="Provider">
              <div className="flex gap-1.5">
                {Object.entries(DIALECTS).map(([id, x]) => (
                  <button
                    key={id}
                    onClick={() => set(id === s.muse.api
                      // back to the provider in use: its models and address come back
                      ? { api: id, base: s.muse.base, agentModel: s.muse.agent_model, rewriteModel: s.muse.rewrite_model }
                      // another provider's model names would be wrong here: use its defaults
                      : { api: id, base: '', agentModel: '', rewriteModel: '' })}
                    className={
                      'flex-1 rounded-md border px-2 py-1.5 text-[11px] transition-colors ' +
                      (form.api === id ? 'border-accent/50 bg-panel-2 text-ink' : 'hairline text-mute hover:text-ink')
                    }
                  >
                    {x.label}
                  </button>
                ))}
              </div>
            </Group>

            <Field label="Address (base URL)"
                   hint={d.keyed ? 'Include the version segment, e.g. …/v1 — no trailing slash.' : 'The Ollama box on your network.'}>
              <TextInput value={form.base} onChange={(e) => set({ base: e.target.value })}
                         placeholder={d.base} spellCheck={false} autoComplete="off" />
            </Field>

            {d.keyed && (
              <Group label="API key"
                     hint={s.muse.key_set
                       ? `A key is set (${s.muse.key_hint}). Leave this blank to keep it. Changing the address without entering a key removes it.`
                       : 'Stored on the server only, never shown again.'}>
                <div className="flex items-center gap-2">
                  <TextInput type="password" autoComplete="off" value={form.key} aria-label="API key"
                             disabled={form.removeKey}
                             onChange={(e) => set({ key: e.target.value })}
                             placeholder={s.muse.key_set ? `•••• ${s.muse.key_hint}` : 'paste the key'} />
                  {s.muse.key_set && (
                    <label className="flex shrink-0 items-center gap-1 text-[10.5px] text-mute">
                      <input type="checkbox" checked={form.removeKey}
                             onChange={(e) => set({ removeKey: e.target.checked, key: '' })}
                             className="accent-accent" />
                      remove
                    </label>
                  )}
                </div>
              </Group>
            )}

            <div className="grid grid-cols-2 gap-2">
              <Field label="Chat model" hint="Must support tools.">
                <TextInput value={form.agentModel} onChange={(e) => set({ agentModel: e.target.value })}
                           placeholder="default for this provider"
                           spellCheck={false} />
              </Field>
              <Field label="Rewrite & sweep model">
                <TextInput value={form.rewriteModel} onChange={(e) => set({ rewriteModel: e.target.value })}
                           placeholder="default for this provider"
                           spellCheck={false} />
              </Field>
            </div>
            <p className="text-[10px] text-mute/60">
              Now using <span className="text-mute">{s.muse.agent_model}</span> for chat and{' '}
              <span className="text-mute">{s.muse.rewrite_model}</span> for rewrites and sweeps.
            </p>

            {museMsg && <Note kind={museMsg.kind}>{museMsg.text}</Note>}

            <div className="flex flex-wrap items-center justify-end gap-2">
              {s.muse.source === 'app' && (
                <Button onClick={resetMuse} disabled={!!busy || (locked && !current)}
                        title="Forget these and use the server's environment settings">
                  {busy === 'reset' ? 'Resetting…' : 'Use environment settings'}
                </Button>
              )}
              <Button onClick={testMuse} disabled={!!busy}>
                {busy === 'test' ? 'Testing…' : 'Test saved connection'}
              </Button>
              <Button variant="accent" onClick={saveMuse} disabled={!!busy || (locked && !current)}>
                {busy === 'muse' ? 'Saving…' : 'Save & test'}
              </Button>
            </div>
          </section>

          {/* --- the lock --- */}
          <section className="space-y-3 border-t hairline pt-4">
            <div className="flex items-center justify-between">
              <span className="text-[9.5px] uppercase tracking-wider text-mute/70">Password</span>
              <span className="text-[10px] text-mute/60">
                {locked ? (s.lock.source === 'app' ? 'locked · set in the app' : 'locked · from the environment') : 'no lock'}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label={locked ? 'New password' : 'Password'}>
                <TextInput type="password" autoComplete="new-password" value={pw.next}
                           onChange={(e) => setPw((p) => ({ ...p, next: e.target.value }))} />
              </Field>
              <Field label="Again">
                <TextInput type="password" autoComplete="new-password" value={pw.again}
                           onChange={(e) => setPw((p) => ({ ...p, again: e.target.value }))} />
              </Field>
            </div>
            <p className="text-[10px] text-mute/60">
              {locked
                ? 'Changing it signs out every other device. This one stays signed in.'
                : 'Setting one locks the archive: every device will need it to open Katha.'}
            </p>
            {pwMsg && <Note kind={pwMsg.kind}>{pwMsg.text}</Note>}
            {confirmOff && (
              <Note kind="err">
                Turn the lock off? Anyone who can reach this server will be able to read and
                change your books.{' '}
                <button onClick={() => savePassword(true)} className="font-semibold underline" disabled={!!busy}>
                  Yes, turn it off
                </button>{' '}
                · <button onClick={() => setConfirmOff(false)} className="underline">Keep it</button>
              </Note>
            )}
            <div className="flex items-center justify-end gap-2">
              {locked && !confirmOff && (
                <Button onClick={() => setConfirmOff(true)} disabled={!!busy || !current}
                        className="text-err">
                  Turn the lock off…
                </Button>
              )}
              <Button variant="accent" onClick={() => savePassword(false)}
                      disabled={!!busy || !pw.next || (locked && !current)}>
                {busy === 'pw' ? 'Saving…' : locked ? 'Change password' : 'Set password'}
              </Button>
            </div>
          </section>
        </div>
      </div>
    </Overlay>
  )
}

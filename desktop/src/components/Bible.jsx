import React, { useEffect, useState } from 'react'
import * as api from '../api.js'

// The BIBLE — the story's canon (characters, places, timeline…), as editable
// markdown. Files live at `bible/<name>.md` in the archive; this is the
// read/write surface for them. A left list of files, a markdown editor on the
// right. Save writes the md (source of truth) via PUT /bible/{name}.
export default function Bible({ series, initial, onClose, onChanged }) {
  const [files, setFiles] = useState({})       // name → content
  const [active, setActive] = useState(null)
  const [draft, setDraft] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')

  useEffect(() => {
    let alive = true
    api
      .getBible(series.series, series.book)
      .then((b) => {
        if (!alive) return
        const f = b.files || {}
        setFiles(f)
        const first = initial && f[initial] !== undefined ? initial : Object.keys(f)[0] || null
        setActive(first)
        setDraft(first ? f[first] || '' : '')
      })
      .catch((e) => alive && setError(e.message || 'failed to load bible'))
    return () => { alive = false }
  }, [series.series, series.book])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const names = Object.keys(files).sort()
  // The bible is a tree — group nested files (characters/kael.md) by folder.
  const loose = names.filter((n) => !n.includes('/'))
  const groups = {}
  for (const n of names) {
    const i = n.indexOf('/')
    if (i === -1) continue
    const folder = n.slice(0, i)
    if (!groups[folder]) groups[folder] = []
    groups[folder].push(n)
  }
  const rowClass = (n, indent) =>
    'w-full truncate rounded-md py-1.5 text-left text-[12px] ' +
    (indent ? 'pl-5 pr-2 ' : 'px-2 ') +
    (n === active
      ? 'bg-panel-2 text-ink ring-1 ring-gold/40'
      : 'text-mute hover:bg-panel-2/60 hover:text-ink')

  const select = (name) => {
    if (dirty && !window.confirm('Discard unsaved changes?')) return
    setActive(name)
    setDraft(files[name] || '')
    setDirty(false)
    setCreating(false)
  }

  const save = async () => {
    if (!active) return
    setSaving(true)
    setError('')
    try {
      const res = await api.saveBible(series.series, series.book, active, draft)
      setFiles(res.files || {})
      setDirty(false)
    } catch (e) {
      setError(e.message || 'save failed')
    } finally {
      setSaving(false)
    }
  }

  const create = async () => {
    let name = newName.trim()
    if (!name) return
    if (!name.endsWith('.md')) name += '.md'
    if (files[name] !== undefined) { setError('That file already exists.'); return }
    setSaving(true)
    setError('')
    try {
      const res = await api.saveBible(
        series.series, series.book, name,
        `# ${name.replace(/\.md$/, '')}\n\n`,
      )
      setFiles(res.files || {})
      setActive(name)
      setDraft((res.files || {})[name] || '')
      setCreating(false)
      setNewName('')
      setDirty(false)
      if (onChanged) onChanged()   // refresh the rail's bible list
    } catch (e) {
      setError(e.message || 'create failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="absolute inset-0 z-40 flex items-start justify-center bg-black/60 pt-[6vh]"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex h-[80vh] w-[860px] max-w-[94vw] overflow-hidden rounded-lg border hairline bg-panel shadow-2xl shadow-black/60"
      >
        {/* files */}
        <div className="flex w-56 shrink-0 flex-col border-r hairline">
          <div className="flex items-center justify-between px-3 py-2.5">
            <span className="text-[11px] font-medium text-ink">Bible</span>
            <button
              onClick={() => setCreating(true)}
              className="text-[14px] leading-none text-mute hover:text-gold"
              title="New bible file"
            >
              +
            </button>
          </div>
          <ul className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-2">
            {names.length === 0 && (
              <li className="px-2 py-2 text-[11px] text-mute/60">No bible files yet.</li>
            )}
            {loose.map((n) => (
              <li key={n}>
                <button onClick={() => select(n)} className={rowClass(n, false)}>
                  {n}
                </button>
              </li>
            ))}
            {Object.entries(groups)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([folder, items]) => (
                <li key={folder} className="mt-1">
                  <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-mute/50">
                    {folder}/
                  </div>
                  <ul className="space-y-0.5">
                    {items.map((n) => (
                      <li key={n}>
                        <button onClick={() => select(n)} className={rowClass(n, true)}>
                          {n.split('/').slice(1).join('/')}
                        </button>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
          </ul>
          {creating && (
            <div className="border-t hairline p-2">
              <input
                autoFocus
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') create() }}
                placeholder="characters/mira.md"
                className="w-full rounded border hairline bg-base px-2 py-1 text-[11.5px] text-ink placeholder:text-mute/50 focus:outline-none focus:ring-1 focus:ring-gold/50"
              />
              <div className="mt-1 flex justify-end gap-1">
                <button
                  onClick={() => { setCreating(false); setNewName('') }}
                  className="rounded border hairline px-2 py-0.5 text-[10px] text-mute hover:text-ink"
                >
                  cancel
                </button>
                <button
                  onClick={create}
                  className="rounded bg-gold px-2 py-0.5 text-[10px] font-semibold text-base hover:brightness-110"
                >
                  create
                </button>
              </div>
            </div>
          )}
        </div>

        {/* editor */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between border-b hairline px-4 py-2.5">
            <span className="text-[12px] text-ink">{active || 'No file selected'}</span>
            <div className="flex items-center gap-2">
              {dirty && <span className="text-[10px] text-warn">unsaved</span>}
              <button
                onClick={save}
                disabled={!active || saving || !dirty}
                className="rounded-md border border-gold/40 px-2.5 py-1 text-[10.5px] font-medium text-ink transition-colors hover:bg-gold/10 disabled:opacity-40"
              >
                {saving ? '…' : 'Save'}
              </button>
              <button onClick={onClose} className="text-[14px] text-mute hover:text-ink" title="Close (Esc)">
                ×
              </button>
            </div>
          </div>
          {error && (
            <div className="border-b hairline px-4 py-2 text-[10.5px] text-red-300">{error}</div>
          )}
          <textarea
            value={draft}
            onChange={(e) => { setDraft(e.target.value); setDirty(true) }}
            spellCheck={false}
            placeholder="Nothing here yet. Write the character, place, or thread…"
            className="min-h-0 flex-1 resize-none bg-base px-4 py-3 font-serif text-[14px] leading-[1.7] text-ink/95 placeholder:text-mute/40 focus:outline-none"
          />
        </div>
      </div>
    </div>
  )
}

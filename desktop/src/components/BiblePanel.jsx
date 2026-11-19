import React, { useEffect, useState } from 'react'
import * as api from '../lib/api.js'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'

// The BIBLE — the story's canon, organised as a tree:
//   bible/characters/<name>.md      one file per main character
//   bible/characters/side-characters.md   NPCs / supporting cast
//   bible/places.md, bible/timeline.md
// Left: the file tree; right: a markdown editor. Save writes the md (source
// of truth) via PUT /bible/{name}. New books start with the starter shape.

const SIDE_PATH = 'characters/side-characters.md'

const SIDE_TEMPLATE =
  '# Side Characters & NPCs\n\n' +
  'One `## Name` section per supporting character. Main characters get ' +
  'their own file under `characters/`.\n\n' +
  '## Name\n- Role:\n- Appearance:\n- Voice / manner:\n- Secret:\n'

const characterTemplate = (name) =>
  `# ${name}\n\n` +
  '- Role:\n' +
  '- Appearance:\n' +
  '- Voice / manner:\n' +
  '- Wants:\n' +
  '- Fears:\n' +
  '- Relationships:\n' +
  '- Arc:\n\n' +
  '## Notes\n'

// Same rule as the server's slugify(), so paths match the archive.
const slugify = (s) =>
  s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')

export default function BiblePanel({ series, initial, onClose, onChanged, refreshKey = 0, onDeleteFile }) {
  const [files, setFiles] = useState({})       // name → content
  const [active, setActive] = useState(null)
  const [draft, setDraft] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  // null | 'character' (one file under characters/) | 'file' (custom path)
  const [creating, setCreating] = useState(null)
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
  }, [series.series, series.book, refreshKey])

  const names = Object.keys(files).sort()
  // Group nested files (characters/kael.md) by their first folder.
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
      ? 'bg-panel-2 text-ink ring-1 ring-accent/40'
      : 'text-mute hover:bg-panel-2/60 hover:text-ink')

  const select = (name) => {
    if (dirty && !window.confirm('Discard unsaved changes?')) return
    setActive(name)
    setDraft(files[name] || '')
    setDirty(false)
    setCreating(null)
  }

  const guardDirty = () =>
    !dirty || window.confirm('Discard unsaved changes?')

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

  // Write one file and make it the active draft.
  const putFile = async (name, content) => {
    const res = await api.saveBible(series.series, series.book, name, content)
    const f = res.files || {}
    setFiles(f)
    setActive(name)
    setDraft(f[name] || '')
    setDirty(false)
    setCreating(null)
    setNewName('')
    if (onChanged) onChanged()
    return res
  }

  const createCharacter = async () => {
    const name = newName.trim()
    if (!name) return
    const slug = slugify(name) || 'unnamed'
    const path = `characters/${slug}.md`
    if (files[path] !== undefined) {
      setError('That character already exists.')
      return
    }
    setSaving(true)
    setError('')
    try {
      await putFile(path, characterTemplate(name))
    } catch (e) {
      setError(e.message || 'create failed')
    } finally {
      setSaving(false)
    }
  }

  const openSideCharacters = async () => {
    if (!guardDirty()) return
    if (files[SIDE_PATH] !== undefined) {
      select(SIDE_PATH)
      return
    }
    setSaving(true)
    setError('')
    try {
      await putFile(SIDE_PATH, SIDE_TEMPLATE)
    } catch (e) {
      setError(e.message || 'create failed')
    } finally {
      setSaving(false)
    }
  }

  const createOther = async () => {
    let name = newName.trim()
    if (!name) return
    if (!name.endsWith('.md')) name += '.md'
    if (files[name] !== undefined) {
      setError('That file already exists.')
      return
    }
    setSaving(true)
    setError('')
    try {
      await putFile(name, `# ${name.replace(/\.md$/, '')}\n\n`)
    } catch (e) {
      setError(e.message || 'create failed')
    } finally {
      setSaving(false)
    }
  }

  // Backfill the canonical shape for a book that predates it.
  const scaffold = async () => {
    if (!guardDirty()) return
    setSaving(true)
    setError('')
    try {
      const res = await api.scaffoldBible(series.series, series.book)
      const f = res.files || {}
      setFiles(f)
      const first = f[SIDE_PATH] !== undefined ? SIDE_PATH : Object.keys(f)[0] || null
      setActive(first)
      setDraft(first ? f[first] || '' : '')
      setDirty(false)
      setCreating(null)
      if (onChanged) onChanged()
    } catch (e) {
      setError(e.message || 'could not create the starter bible')
    } finally {
      setSaving(false)
    }
  }

  // One bible file: click to edit, × to send it to the trash. Deleting goes
  // through the shared confirm dialog (App owns it), which prints what exactly
  // would go; the panel re-reads from the server afterwards (refreshKey), so the
  // file list never drifts from disk.
  const FileRow = ({ name, indent }) => (
    <div className="group flex items-center gap-0.5">
      <button
        onClick={() => select(name)}
        className={rowClass(name, indent) + ' min-w-0 flex-1'}
      >
        {indent ? name.split('/').slice(1).join('/') : name}
      </button>
      {onDeleteFile && (
        <button
          onClick={() => onDeleteFile(name)}
          title={`Delete ${name} — moves it to the trash`}
          aria-label={`Delete ${name}`}
          className="shrink-0 rounded px-1 py-0.5 text-[11px] leading-none text-transparent transition-colors hover:text-err group-hover:text-mute/60"
        >
          ×
        </button>
      )}
    </div>
  )

  const cancelCreate = () => { setCreating(null); setNewName('') }

  const createInput = (placeholder, onCreate) => (
    <div className="border-t hairline p-2">
      <input
        autoFocus
        value={newName}
        onChange={(e) => setNewName(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') onCreate() }}
        placeholder={placeholder}
        className="w-full rounded border hairline bg-base px-2 py-1 text-[11.5px] text-ink placeholder:text-mute/50 focus:outline-none focus:ring-1 focus:ring-accent/50"
      />
      <div className="mt-1 flex justify-end gap-1">
        <button
          onClick={cancelCreate}
          className="rounded border hairline px-2 py-0.5 text-[10px] text-mute hover:text-ink"
        >
          cancel
        </button>
        <button
          onClick={onCreate}
          disabled={saving || !newName.trim()}
          className="rounded bg-accent px-2 py-0.5 text-[10px] font-semibold text-onaccent hover:brightness-110 disabled:opacity-40"
        >
          create
        </button>
      </div>
    </div>
  )

  return (
    <Overlay onClose={onClose} width={880} height="82vh" padTop="5vh">
      <div className="flex h-full flex-col">
        <OverlayHeader
          icon="✦"
          title="Bible"
          onClose={onClose}
          extra={
            <span className="text-[10px] text-mute/60">
              {names.length} file{names.length === 1 ? '' : 's'}
            </span>
          }
        />

        <div className="flex min-h-0 flex-1">
          {/* file tree */}
          <div className="flex w-44 shrink-0 flex-col border-r hairline md:w-60">
            <ul className="min-h-0 flex-1 overflow-y-auto p-1.5">
              {names.length === 0 && (
                <li className="px-2 py-2 text-[11px] text-mute/60">
                  No bible files yet. Use the buttons below or create the
                  starter bible.
                </li>
              )}
              {loose.map((n) => (
                <li key={n}>
                  <FileRow name={n} indent={false} />
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
                          <FileRow name={n} indent />
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
            </ul>

            {creating === 'character' && createInput('e.g. Percy Jackson', createCharacter)}
            {creating === 'file' && createInput('e.g. magic-system.md', createOther)}

            {!creating && (
              <div className="space-y-1 border-t hairline p-2">
                <button
                  onClick={() => { if (guardDirty()) { setCreating('character'); setNewName('') } }}
                  disabled={saving}
                  className="w-full rounded-md border border-accent/40 px-2 py-1 text-[10.5px] font-medium text-accent hover:bg-accent/10 disabled:opacity-40"
                >
                  + Main character
                </button>
                <button
                  onClick={openSideCharacters}
                  disabled={saving}
                  className="w-full rounded-md border hairline px-2 py-1 text-[10.5px] text-mute hover:text-ink disabled:opacity-40"
                >
                  NPCs / side characters
                </button>
                <button
                  onClick={() => { if (guardDirty()) { setCreating('file'); setNewName('') } }}
                  disabled={saving}
                  className="w-full rounded-md border hairline px-2 py-1 text-[10.5px] text-mute hover:text-ink disabled:opacity-40"
                >
                  + other file
                </button>
              </div>
            )}
          </div>

          {/* editor */}
          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex items-center justify-between border-b hairline px-4 py-2">
              <span className="truncate text-[12px] text-ink">{active || 'No file selected'}</span>
              <div className="flex items-center gap-2">
                {dirty && <span className="text-[10px] text-warn">unsaved</span>}
                <button
                  onClick={save}
                  disabled={!active || saving || !dirty}
                  className="rounded-md border border-accent/40 px-2.5 py-1 text-[10.5px] font-medium text-ink transition-colors hover:bg-accent/10 disabled:opacity-40"
                >
                  {saving ? '…' : 'Save'}
                </button>
              </div>
            </div>
            {error && <div className="border-b hairline px-4 py-2 text-[10.5px] text-err">{error}</div>}

            {names.length === 0 ? (
              <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
                <div className="text-[12.5px] text-ink">This book has no bible yet.</div>
                <div className="max-w-[46ch] text-[11px] leading-relaxed text-mute/70">
                  The canonical shape: one file per <span className="text-ink">main character</span> under{' '}
                  <code className="text-accent-dim">characters/</code>, one shared file for{' '}
                  <span className="text-ink">NPCs / side characters</span>, plus{' '}
                  <code className="text-accent-dim">places.md</code> and{' '}
                  <code className="text-accent-dim">timeline.md</code>.
                </div>
                <button
                  onClick={scaffold}
                  disabled={saving}
                  className="rounded-md border border-accent/40 px-3 py-1.5 text-[11px] font-medium text-accent hover:bg-accent/10 disabled:opacity-40"
                >
                  {saving ? 'creating…' : 'Create starter bible'}
                </button>
              </div>
            ) : (
              <textarea
                value={draft}
                onChange={(e) => { setDraft(e.target.value); setDirty(true) }}
                spellCheck={false}
                placeholder="Nothing here yet. Write the character, place, or thread…"
                className="min-h-0 flex-1 resize-none bg-base px-4 py-3 font-serif text-[14px] leading-[1.7] text-ink/95 placeholder:text-mute/40 focus:outline-none"
              />
            )}
          </div>
        </div>
      </div>
    </Overlay>
  )
}

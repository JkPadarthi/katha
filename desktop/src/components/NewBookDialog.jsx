import React, { useState } from 'react'
import * as api from '../lib/api.js'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Field, TextInput } from '../ui/Field.jsx'
import { Button } from '../ui/Button.jsx'

// Create a series + book (POST /api/books). The server slugifies both names;
// App refreshes the tree and switches to the new book.
export default function NewBookDialog({ onClose, onCreated }) {
  const [series, setSeries] = useState('')
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const canSubmit = series.trim() && title.trim() && !busy

  const submit = async () => {
    if (!canSubmit) return
    setBusy(true)
    setError('')
    try {
      const created = await api.createBook(series.trim(), title.trim())
      onCreated(created)
    } catch (e) {
      setError(e.message || 'could not create the book')
      setBusy(false)
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      submit()
    }
  }

  return (
    <Overlay onClose={onClose} width={420} padTop="20vh" z={50}>
      <OverlayHeader title="New book" onClose={onClose} />
      <div className="space-y-4 px-4 py-4">
        <Field label="Series" hint="Groups related books. An existing series is reused.">
          <TextInput
            autoFocus
            value={series}
            onChange={(e) => setSeries(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="The Ember Throne"
          />
        </Field>
        <Field label="Book title">
          <TextInput
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="The First Flame"
          />
        </Field>

        {error && (
          <div className="rounded-md border border-err/30 bg-err/10 px-3 py-2 text-[11px] text-err">
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 pt-1">
          <Button size="md" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button variant="primary" onClick={submit} disabled={!canSubmit}>
            {busy ? 'creating…' : 'Create book'}
          </Button>
        </div>
      </div>
    </Overlay>
  )
}

import React, { useRef, useState } from 'react'
import * as api from '../lib/api.js'
import Overlay, { OverlayHeader } from '../ui/Overlay.jsx'
import { Field, TextInput } from '../ui/Field.jsx'
import { Button } from '../ui/Button.jsx'

// A book's face (2.8, D43): the author that rides in the EPUB metadata, and the
// cover that becomes its first page.
//
// The cover is the AUTHOR's own file — Katha never invents artwork. It goes up as
// a data URL and comes back normalised by the server (real format sniffed, EXIF
// orientation honoured, fitted to 1600×2560, re-encoded JPEG), so an 8 MB phone
// photo can't end up inside an EPUB. Server messages are written for the author
// to read, so they are shown verbatim.
export default function BookDetailsDialog({
  series, book, title, author, hasCover, onClose, onSaved
}) {
  const [name, setName] = useState(author || '')
  const [cover, setCover] = useState(hasCover ? api.coverUrl(series, book) : null)
  const [busy, setBusy] = useState('')          // 'author' | 'cover' | 'epub'
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const fileRef = useRef(null)

  const dirty = (name || '').trim() !== (author || '').trim()

  const saveAuthor = async () => {
    setBusy('author'); setError(''); setNote('')
    try {
      const meta = await api.setBookMeta(series, book, { author: name })
      setNote(meta.author ? `Author saved: ${meta.author}` : 'Author cleared.')
      if (onSaved) await onSaved(meta)
    } catch (e) {
      setError(e.message || 'could not save the author')
    } finally {
      setBusy('')
    }
  }

  const pickCover = (file) => {
    if (!file) return
    setError(''); setNote('')
    // The server validates properly (it sniffs the bytes); these two checks just
    // save a pointless round trip for an obvious mistake.
    if (!/^image\//.test(file.type)) { setError('use a JPEG, PNG or WebP image'); return }
    if (file.size > 8 * 1024 * 1024) { setError('that file is larger than 8 MB — resize it first'); return }

    setBusy('cover')
    const reader = new FileReader()
    reader.onload = async () => {
      try {
        const info = await api.uploadCover(series, book, reader.result)
        setCover(api.coverUrl(series, book, Date.now()))   // never the cached one
        const kb = Math.max(1, Math.round((info.bytes || 0) / 1024))
        setNote(`Cover set — ${info.cover_w}×${info.cover_h}, ${kb} KB`)
        if (onSaved) await onSaved(info)
      } catch (e) {
        setError(e.message || 'could not store that cover')
      } finally {
        setBusy('')
      }
    }
    reader.onerror = () => { setError('that file could not be read'); setBusy('') }
    reader.readAsDataURL(file)
  }

  const removeCover = async () => {
    setBusy('cover'); setError(''); setNote('')
    try {
      await api.deleteCover(series, book)
      setCover(null)
      setNote('Cover removed — the EPUB will have no cover page.')
      if (onSaved) await onSaved(null)
    } catch (e) {
      setError(e.message || 'could not remove the cover')
    } finally {
      setBusy('')
    }
  }

  const downloadEpub = async () => {
    setBusy('epub'); setError(''); setNote('')
    try {
      const slug = (title || 'katha').replace(/[^A-Za-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '').toLowerCase()
      await api.exportEpub(series, book, `${slug || 'katha'}.epub`)
      setNote('EPUB downloaded — open it and check the cover page.')
    } catch (e) {
      setError(e.message || 'could not build the EPUB')
    } finally {
      setBusy('')
    }
  }

  return (
    <Overlay onClose={onClose} width={460} padTop="18vh" z={50}>
      <OverlayHeader title="Book details" onClose={onClose} />
      <div className="space-y-4 px-4 py-4">
        <div className="text-[11px] text-mute">
          <span className="text-mute/60">In </span>{series}
          <div className="mt-0.5 text-[12.5px] text-ink">{title}</div>
        </div>

        <Field label="Author"
               hint="Rides in the EPUB metadata — the name the shelf shows beside the title.">
          <TextInput
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && dirty) { e.preventDefault(); saveAuthor() }
            }}
            placeholder="J. K. Padarthi"
          />
        </Field>
        {dirty && (
          <div className="flex justify-end">
            <Button variant="primary" onClick={saveAuthor} disabled={busy === 'author'}>
              {busy === 'author' ? 'Saving…' : 'Save author'}
            </Button>
          </div>
        )}

        <div>
          <span className="text-[11px] text-mute">Cover</span>
          <div className="mt-1.5 flex gap-3">
            <div className="flex h-[132px] w-[84px] shrink-0 items-center justify-center overflow-hidden rounded-md border hairline bg-panel-2/40">
              {cover
                ? <img src={cover} alt="" className="h-full w-full object-cover" />
                : <span className="px-1 text-center text-[9.5px] text-mute/60">no cover</span>}
            </div>
            <div className="min-w-0 flex-1 space-y-1.5">
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={(e) => {
                  pickCover(e.target.files && e.target.files[0])
                  e.target.value = ''            // so re-picking the same file works
                }}
              />
              <div className="flex flex-wrap gap-1.5">
                <Button onClick={() => fileRef.current && fileRef.current.click()}
                        disabled={busy === 'cover'}>
                  {cover ? 'Replace image…' : 'Choose image…'}
                </Button>
                {cover && (
                  <Button onClick={removeCover} disabled={busy === 'cover'}>Remove</Button>
                )}
              </div>
              <p className="text-[10px] leading-snug text-mute/60">
                JPEG, PNG or WebP up to 8 MB. It is fitted to 1600×2560 and re-encoded,
                then becomes the EPUB's first page.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 border-t hairline pt-3">
          <Button onClick={downloadEpub} disabled={busy === 'epub'}>
            {busy === 'epub' ? 'Building…' : 'Download EPUB'}
          </Button>
          <Button variant="accent" onClick={onClose}>Done</Button>
        </div>

        {note && (
          <div className="rounded-md border border-accent/30 bg-accent/5 px-3 py-2 text-[11px] text-mute">
            {note}
          </div>
        )}
        {error && (
          <div className="rounded-md border border-err/30 bg-err/10 px-3 py-2 text-[11px] text-err">
            {error}
          </div>
        )}
      </div>
    </Overlay>
  )
}

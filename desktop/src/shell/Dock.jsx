import React, { useState } from 'react'
import Icon from '../ui/Icon.jsx'
import Composer from './Composer.jsx'
import { editorApi } from '../components/Editor.jsx'
import { fileLabel } from '../components/ProposalReview.jsx'
import { kTokens } from '../lib/useMuse.js'

// THE DOCK (4.0, D63) — everything the Muse is, at the bottom of the page: what is
// waiting for review, the latest reply, and the composer. It replaces the old Muse
// column: the page keeps the whole width, and the conversation is one tap away.

function PendingRow({ pending, onReview, onAcceptAll, onDiscard, busy }) {
  const [open, setOpen] = useState(false)
  const hunks = pending.reduce((n, p) => n + (p.hunk_count || 0), 0)
  const label = hunks
    ? `${hunks} ${hunks === 1 ? 'change' : 'changes'} waiting`
    : `${pending.length} ${pending.length === 1 ? 'file' : 'files'} waiting`
  const where = pending.map((p) => fileLabel(p.path)).join(' · ')
  const anyStale = pending.some((p) => p.stale)

  return (
    <div className="border-b hairline pb-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <button
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex min-h-9 min-w-0 flex-1 items-center gap-2 rounded-lg px-1 text-left"
          title="Show the files with changes waiting"
        >
          <span className="h-2 w-2 shrink-0 rounded-full bg-accent" aria-hidden="true" />
          <span className="shrink-0 text-[13.5px] font-medium text-ink">{label}</span>
          <span className="min-w-0 truncate text-[13px] text-mute max-md:hidden">{where}</span>
          <Icon name="chevronDown" size={15} className={'text-mute transition-transform ' + (open ? 'rotate-180' : '')} />
        </button>
        <button
          onClick={() => onReview(pending[0].id)}
          disabled={busy}
          className="h-9 rounded-lg px-3 text-[13.5px] font-medium text-accent hover:bg-accent/10 disabled:opacity-40"
        >
          Review
        </button>
        <button
          onClick={onAcceptAll}
          disabled={busy || pending.every((p) => p.stale)}
          className="h-9 rounded-lg bg-accent/12 px-3 text-[13.5px] font-medium text-accent hover:bg-accent/20 disabled:opacity-40"
          title={anyStale ? 'Accept every change that still applies' : 'Accept every change in every file'}
        >
          {busy ? 'Saving…' : 'Accept all'}
        </button>
      </div>
      {open && (
        <ul className="mt-1 max-h-48 space-y-0.5 overflow-y-auto">
          {pending.map((p) => (
            <li key={p.id} className="flex items-center gap-1">
              <button
                onClick={() => onReview(p.id)}
                className="flex min-h-9 min-w-0 flex-1 items-center gap-2 rounded-lg px-2 text-left text-[13.5px] text-ink hover:bg-panel-2"
                title={p.stale ? 'This file changed since the Muse read it' : `Review ${p.path}`}
              >
                <span className="truncate">{fileLabel(p.path)}</span>
                {typeof p.hunk_count === 'number' && <span className="text-mute">· {p.hunk_count}</span>}
                {p.stale && <span className="text-warn">· out of date</span>}
              </button>
              <button
                onClick={() => onDiscard(p.id)}
                aria-label={`Discard the change to ${fileLabel(p.path)}`}
                title="Discard this change"
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-mute hover:bg-err/10 hover:text-err"
              >
                <Icon name="x" size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ReplyCard({ muse, selection, onOpenThread, onClose }) {
  const lastUser = [...muse.messages].reverse().find((m) => m.role === 'user')
  const text = muse.busy ? muse.streaming : muse.latest
  const can = (fn) => !!fn && !!text && !muse.busy

  return (
    <div className="float sheet-in mb-2 rounded-2xl px-4 py-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          {lastUser && (
            <div className="mb-1 truncate text-[12.5px] text-mute">You: {lastUser.text}</div>
          )}
          <div className="max-h-[34vh] overflow-y-auto whitespace-pre-wrap text-[14.5px] leading-relaxed text-ink">
            {text || (
              <span className="flex items-center gap-2 text-mute">
                <span className="h-2 w-2 animate-pulse rounded-full bg-accent" aria-hidden="true" />
                {muse.status || 'thinking…'}
              </span>
            )}
            {muse.busy && text && <span className="ml-0.5 inline-block h-4 w-1 animate-pulse bg-accent/70 align-middle" />}
          </div>
          {muse.error && <div className="mt-2 text-[13px] text-err">{muse.error}</div>}
        </div>
        <button
          onClick={onClose}
          aria-label="Dismiss the reply"
          title="Dismiss"
          className="-mr-1 -mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-mute hover:bg-panel-2 hover:text-ink"
        >
          <Icon name="x" size={16} />
        </button>
      </div>
      {!muse.busy && text && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <button disabled={!can(editorApi.insertAtCursor)} onClick={() => editorApi.insertAtCursor(text)}
                  className="h-8 rounded-lg border hairline px-2.5 text-[12.5px] text-ink hover:bg-panel-2 disabled:opacity-40"
                  title="Put this reply into the chapter at the cursor (it saves like typing)">
            Insert at cursor
          </button>
          <button disabled={!can(editorApi.appendToChapter)} onClick={() => editorApi.appendToChapter(text)}
                  className="h-8 rounded-lg border hairline px-2.5 text-[12.5px] text-ink hover:bg-panel-2 disabled:opacity-40">
            Append to chapter
          </button>
          {selection?.text && (
            <button disabled={!can(editorApi.replaceSelection)} onClick={() => editorApi.replaceSelection(text)}
                    className="h-8 rounded-lg border hairline px-2.5 text-[12.5px] text-ink hover:bg-panel-2 disabled:opacity-40">
              Replace selection
            </button>
          )}
          <span className="flex-1" />
          {muse.usage && (
            <span className="text-[12px] text-mute" title={`This session: ${muse.spent.input} in, ${muse.spent.output} out`}>
              {kTokens(muse.usage.input)} in · {kTokens(muse.usage.output)} out
            </span>
          )}
          <button onClick={onOpenThread} className="h-8 rounded-lg px-2.5 text-[12.5px] font-medium text-accent hover:bg-accent/10">
            Conversation
          </button>
        </div>
      )}
    </div>
  )
}

export default function Dock({
  muse, selection, onInline, onRewrite, inlineBusy, onReview, onAcceptAll, reviewBusy,
  threadOpen, onToggleThread, disabled, children
}) {
  const showReply = muse.fresh && !threadOpen && (muse.busy || muse.latest || muse.error)
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 z-30 flex justify-center bg-gradient-to-t from-base from-40% to-transparent px-3 pb-[max(12px,env(safe-area-inset-bottom))] pt-10 md:px-6 md:pb-6">
      <div className="dock-width pointer-events-auto w-full">
        {children}
        {showReply && (
          <ReplyCard muse={muse} selection={selection} onOpenThread={onToggleThread} onClose={muse.dismiss} />
        )}
        <div className="float rounded-2xl px-3 pb-2 pt-2 md:px-4">
          {muse.pending.length > 0 && (
            <div className="mb-1.5">
              <PendingRow
                pending={muse.pending}
                onReview={onReview}
                onAcceptAll={onAcceptAll}
                onDiscard={muse.discard}
                busy={reviewBusy}
              />
            </div>
          )}
          <Composer
            muse={muse}
            selection={selection}
            onInline={onInline}
            onRewrite={onRewrite}
            inlineBusy={inlineBusy}
            onOpenThread={onToggleThread}
            threadOpen={threadOpen}
            disabled={disabled}
          />
        </div>
      </div>
    </div>
  )
}

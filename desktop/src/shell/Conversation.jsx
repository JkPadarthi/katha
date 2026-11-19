import React, { useEffect, useRef } from 'react'
import Icon from '../ui/Icon.jsx'
import { kTokens } from '../lib/useMuse.js'

// The whole conversation with the Muse for this chapter (4.0). A column beside the page
// on a wide screen (it stays open if you leave it open), a sheet over the page on a
// phone. The composer stays in the dock either way — there is only ever one.
export default function Conversation({ muse, onClose, chapterTitle }) {
  const ref = useRef(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [muse.messages, muse.streaming])

  return (
    <aside
      aria-label="Conversation with the Muse"
      className="flex min-h-0 flex-col bg-panel max-lg:absolute max-lg:inset-0 max-lg:z-20 lg:w-[400px] lg:shrink-0 lg:border-l lg:hairline"
    >
      <div className="flex min-h-14 shrink-0 items-center gap-2 border-b hairline px-4" style={{ paddingTop: 'env(safe-area-inset-top)' }}>
        <Icon name="spark" size={16} className="text-accent" />
        <h2 className="min-w-0 flex-1 truncate text-[15px] font-semibold text-ink">
          The Muse{chapterTitle ? <span className="font-normal text-mute"> · {chapterTitle}</span> : null}
        </h2>
        {muse.usage && (
          <span className="text-[12px] text-mute" title={`This session: ${muse.spent.input} in, ${muse.spent.output} out`}>
            {kTokens(muse.usage.input)} in · {kTokens(muse.usage.output)} out
          </span>
        )}
        <button
          onClick={onClose}
          aria-label="Close the conversation"
          title="Close"
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-mute hover:bg-panel-2 hover:text-ink"
        >
          <Icon name="x" />
        </button>
      </div>

      <div ref={ref} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 pb-56 pt-4 lg:pb-6">
        {muse.messages.length === 0 && !muse.streaming && !muse.busy && (
          <div className="mt-16 text-center text-[14px] leading-relaxed text-mute">
            Tell the Muse what to write, or what to change.
            <br />
            <span className="text-[13px]">@ points it at a chapter or a bible file. Select text on the page to edit just that.</span>
          </div>
        )}
        {muse.messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="flex justify-end">
              <div className="max-w-[88%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-panel-2 px-3.5 py-2.5 text-[14px] leading-relaxed text-ink">
                {m.text}
              </div>
            </div>
          ) : (
            <div key={i} className={'whitespace-pre-wrap text-[14.5px] leading-relaxed ' + (m.local ? 'text-mute' : 'text-ink')}>
              {m.text}
            </div>
          )
        )}
        {(muse.streaming || muse.busy) && (
          <div className="whitespace-pre-wrap text-[14.5px] leading-relaxed text-ink">
            {muse.streaming || (
              <span className="flex items-center gap-2 text-mute">
                <span className="h-2 w-2 animate-pulse rounded-full bg-accent" aria-hidden="true" />
                {muse.status || 'thinking…'}
              </span>
            )}
            {muse.busy && muse.streaming && <span className="ml-0.5 inline-block h-4 w-1 animate-pulse bg-accent/70 align-middle" />}
          </div>
        )}
        {muse.error && (
          <div className="rounded-lg border border-err/30 bg-err/10 px-3 py-2 text-[13px] text-err">{muse.error}</div>
        )}
      </div>
    </aside>
  )
}

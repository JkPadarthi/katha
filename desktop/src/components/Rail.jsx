import React from 'react'
import RitualsCard from './RitualsCard.jsx'

// The CHAPTERS pane. Collapses to icons like a proper IDE; the active chapter
// glows in the theme accent. Below: the bible tree and the ritual stat.
export default function Rail({ collapsed, onToggle, active, onSelect, archive, current, onSelectBook, onNewBook, onOpenBible, onNewChapter }) {
  const series = archive.find((s) => s.name === current?.series) || archive[0]
  const book = series?.books?.find((b) => b.id === current?.book) || series?.books?.[0]
  if (!series || !book) return null

  return (
    <aside className="flex min-h-0 flex-col border-r hairline bg-panel">
      {/* Series / book header */}
      <div className="flex items-center gap-2 px-3 py-2.5">
        {collapsed ? (
          <button
            onClick={onToggle}
            className="flex h-6 w-6 items-center justify-center rounded text-mute hover:bg-panel-2"
            title="Expand"
          >
            »
          </button>
        ) : (
          <>
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent/70" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[9.5px] uppercase tracking-wider text-mute/60">
                {series.title || series.name}
              </div>
              <select
                value={`${series.name}/${book.id}`}
                onChange={(e) => {
                  const i = e.target.value.indexOf('/')
                  if (i === -1 || !onSelectBook) return
                  onSelectBook(e.target.value.slice(0, i), e.target.value.slice(i + 1))
                }}
                className="mt-0.5 w-full cursor-pointer truncate border-none bg-transparent p-0 text-[11.5px] font-medium text-ink focus:outline-none"
                title="Switch book"
              >
                {archive.map((s) => (
                  <optgroup key={s.name} label={s.title || s.name}>
                    {s.books.map((b) => (
                      <option key={b.id} value={`${s.name}/${b.id}`}>{b.title}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
            <button
              onClick={onToggle}
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-mute hover:bg-panel-2"
              title="Collapse"
            >
              «
            </button>
          </>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {/* Chapters */}
        {!collapsed && (
          <div className="mb-1 px-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-mute/60">
            Chapters
          </div>
        )}
        <ul className="space-y-0.5">
          {book.chapters.map((c) => {
            const isActive = c.id === active
            return (
              <li key={c.id}>
                <button
                  onClick={() => onSelect(c.id)}
                  className={
                    'flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left transition-colors ' +
                    (isActive
                      ? 'bg-panel-2 text-ink ring-1 ring-accent/40'
                      : 'text-mute hover:bg-panel-2/60 hover:text-ink')
                  }
                  title={c.title}
                >
                  {collapsed ? (
                    <span className="mx-auto">·</span>
                  ) : (
                    <>
                      <span className="w-7 shrink-0 text-right text-[10px] text-mute/70">
                        {c.id.replace(/^ch-?/, '')}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[12px]">{c.title}</span>
                      <span className="text-[9.5px] text-mute/50">{c.words}</span>
                    </>
                  )}
                </button>
              </li>
            )
          })}
        </ul>

        {/* Bible — canon at a glance */}
        {!collapsed && (
          <>
            <div className="mb-1 mt-4 flex items-center justify-between px-1 pt-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-mute/60">
                Bible
              </span>
              <button
                onClick={() => onOpenBible && onOpenBible('')}
                className="rounded px-1 text-[11px] text-mute hover:bg-panel-2 hover:text-accent"
                title="Open the bible"
              >
                ✎
              </button>
            </div>
            <ul className="space-y-0.5">
              {book.bible.map((b) => (
                <li key={b.id}>
                  <button
                    onClick={() => onOpenBible && onOpenBible(b.id)}
                    className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[12px] text-mute hover:bg-panel-2/60 hover:text-ink"
                    title={b.id}
                  >
                    <span className="w-7 shrink-0 text-right text-[10px] text-accent-dim">✎</span>
                    <span className="min-w-0 flex-1 truncate">{b.title}</span>
                  </button>
                </li>
              ))}
              {book.bible.length === 0 && (
                <li>
                  <button
                    onClick={() => onOpenBible && onOpenBible('')}
                    className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[11px] text-accent/80 hover:bg-panel-2/60 hover:text-accent"
                  >
                    <span className="w-7 shrink-0 text-right text-[10px]">+</span>
                    <span>Add bible</span>
                  </button>
                </li>
              )}
            </ul>
          </>
        )}
      </div>

      {!collapsed && <RitualsCard />}

      <div className="border-t hairline p-1.5">
        {!collapsed && (
          <button
            onClick={onNewBook}
            className="mb-1 flex w-full items-center justify-center gap-1 rounded-md px-2 py-1.5 text-[11px] text-mute hover:bg-panel-2 hover:text-ink"
          >
            + New book
          </button>
        )}
        <button
          onClick={onNewChapter}
          className="flex w-full items-center justify-center gap-1 rounded-md px-2 py-1.5 text-[11px] text-mute hover:bg-panel-2 hover:text-ink"
        >
          {collapsed ? '+' : '+ New chapter'}
        </button>
      </div>
    </aside>
  )
}

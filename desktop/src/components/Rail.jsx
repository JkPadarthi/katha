import React from 'react'

// The CHAPTERS pane — the session-rail analog. Collapses to icons like a
// proper IDE. Active chapter glows gold.
export default function Rail({ collapsed, onToggle, active, onSelect, archive }) {
  const series = archive[0]

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
            <span className="h-1.5 w-1.5 rounded-full bg-gold/70" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[11.5px] font-medium text-ink">{series.name}</div>
              <div className="truncate text-[10.5px] text-mute">{series.books[0].title}</div>
            </div>
            <button
              onClick={onToggle}
              className="flex h-6 w-6 items-center justify-center rounded text-mute hover:bg-panel-2"
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
          <div className="mb-1 px-1 pt-1 text-[10px] font-semibold tracking-wider text-mute/60 uppercase">
            Chapters
          </div>
        )}
        <ul className="space-y-0.5">
          {series.books[0].chapters.map((c) => {
            const isActive = c.id === active
            const row = (
              <>
                {!collapsed && (
                  <span className="w-7 shrink-0 text-right text-[10px] text-mute/70">
                    {c.id.replace('ch', '')}
                  </span>
                )}
                {!collapsed && (
                  <span className="min-w-0 flex-1 truncate text-[12px]">{c.title}</span>
                )}
                {!collapsed && (
                  <span className="text-[9.5px] text-mute/50">{c.words}</span>
                )}
              </>
            )
            return (
              <li key={c.id}>
                <button
                  onClick={() => onSelect(c.id)}
                  className={
                    'flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left transition-colors ' +
                    (isActive
                      ? 'bg-panel-2 text-ink ring-1 ring-gold/40'
                      : 'text-mute hover:bg-panel-2/60 hover:text-ink')
                  }
                  title={c.title}
                >
                  {collapsed && <span className="mx-auto">·</span>}
                  {row}
                </button>
              </li>
            )
          })}
        </ul>

        {/* Bible — canon at a glance */}
        {!collapsed && (
          <>
            <div className="mb-1 mt-4 px-1 pt-1 text-[10px] font-semibold tracking-wider text-mute/60 uppercase">
              Bible
            </div>
            <ul className="space-y-0.5">
              {series.books[0].bible.map((b) => (
                <li key={b.id}>
                  <button className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[12px] text-mute hover:bg-panel-2/60 hover:text-ink">
                    <span className="w-7 shrink-0 text-right text-[10px] text-dim">✎</span>
                    <span className="min-w-0 flex-1 truncate">{b.title}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div className="border-t hairline p-1.5">
        <button className="flex w-full items-center justify-center gap-1 rounded-md px-2 py-1.5 text-[11px] text-mute hover:bg-panel-2 hover:text-ink">
          {collapsed ? '+' : '+ New chapter'}
        </button>
      </div>
    </aside>
  )
}
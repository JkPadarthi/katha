import React from 'react'

// Writing rituals — a quiet "today" stat. Discipline, not motivation: words against a
// daily goal, a streak, and a 14-day sparkline. No confetti. Lives in the book menu.
export default function RitualsCard({ stats }) {
  if (!stats) return null
  const pct = stats.goal > 0 ? Math.min(100, Math.round((stats.today / stats.goal) * 100)) : 0
  const max = Math.max(1, ...stats.history.map((h) => h.words))

  return (
    <div className="px-3 py-3">
      <div className="flex items-center justify-between text-[13px]">
        <span className="font-medium text-ink">Today</span>
        <span className="text-mute">{stats.today} / {stats.goal} words</span>
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-panel-2">
        <div className="h-full rounded-full bg-accent" style={{ width: pct + '%' }} />
      </div>
      <div className="mt-2 flex items-end justify-between">
        <span className="text-[12.5px] text-mute">{stats.streak}-day streak</span>
        <div className="flex items-end gap-[3px]" aria-hidden="true">
          {stats.history.map((h, i) => (
            <span
              key={i}
              className="w-[4px] rounded-sm bg-accent/50"
              style={{ height: Math.max(2, Math.round((h.words / max) * 18)) + 'px' }}
              title={`${h.date}: ${h.words} words`}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

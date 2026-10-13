import React, { useEffect, useState } from 'react'
import * as api from '../api.js'
import { getSetting } from '../settings.js'

// Writing rituals — a quiet "today" stat. Discipline, not motivation: words
// against a daily goal, a streak, and a 14-day sparkline. No confetti.
export default function Rituals() {
  const [stats, setStats] = useState(null)

  useEffect(() => {
    let alive = true
    const load = () => {
      const goal = getSetting('goal', null)
      api.getStats(goal).then((s) => alive && setStats(s)).catch(() => {})
    }
    load()
    const t = setInterval(load, 60000)
    window.addEventListener('focus', load)
    return () => {
      alive = false
      clearInterval(t)
      window.removeEventListener('focus', load)
    }
  }, [])

  if (!stats) return null

  const pct = stats.goal > 0 ? Math.min(100, Math.round((stats.today / stats.goal) * 100)) : 0
  const max = Math.max(1, ...stats.history.map((h) => h.words))

  return (
    <div className="border-t hairline px-2.5 py-2">
      <div className="flex items-center justify-between text-[10px] text-mute/60">
        <span className="font-semibold uppercase tracking-wider">Today</span>
        <span>{stats.today} / {stats.goal}</span>
      </div>
      <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-panel-2">
        <div className="h-full rounded-full bg-gold/70" style={{ width: pct + '%' }} />
      </div>
      <div className="mt-1.5 flex items-end justify-between">
        <span className="text-[10px] text-mute/60">{stats.streak}-day streak</span>
        <div className="flex items-end gap-[2px]">
          {stats.history.map((h, i) => (
            <span
              key={i}
              className="w-[3px] rounded-sm bg-gold/40"
              style={{ height: Math.max(2, Math.round((h.words / max) * 14)) + 'px' }}
              title={`${h.date}: ${h.words} words`}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

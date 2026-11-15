import { useEffect, useState } from 'react'
import * as api from './api.js'
import { getSetting } from './settings.js'

// Today's words against the goal, the streak and a 14-day history (the rituals, D11).
// Re-read every minute and whenever the window comes back into focus.
export function useStats(goalKey) {
  const [stats, setStats] = useState(null)
  useEffect(() => {
    let alive = true
    const load = () => {
      api.getStats(getSetting('goal', null)).then((s) => alive && setStats(s)).catch(() => {})
    }
    load()
    const t = setInterval(load, 60000)
    window.addEventListener('focus', load)
    return () => {
      alive = false
      clearInterval(t)
      window.removeEventListener('focus', load)
    }
  }, [goalKey])
  return stats
}

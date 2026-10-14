import { useEffect, useState } from 'react'
import { getSetting, setSetting } from './settings.js'
import { useMediaQuery } from './useMediaQuery.js'

// The theme registry. Each id maps to a `:root[data-theme="…"]` block in
// index.css. `scheme` drives the OS-follow default and browser chrome.
export const THEMES = [
  { id: 'hermes', label: 'Hermes', hint: 'dark · gold', scheme: 'dark' },
  { id: 'paper',  label: 'Paper',  hint: 'light · warm', scheme: 'light' },
  { id: 'slate',  label: 'Slate',  hint: 'dark · cool',  scheme: 'dark' }
]

const THEME_COLOR = { hermes: '#0e0e12', paper: '#f6f1e7', slate: '#0f1419' }

export function resolveTheme(pref, prefersLight) {
  if (pref === 'hermes' || pref === 'paper' || pref === 'slate') return pref
  return prefersLight ? 'paper' : 'hermes'
}

// Returns the active theme id and a setter. `pref === null` means "follow the
// OS"; once the user chooses, it sticks. Syncs <html data-theme> and the
// <meta name="theme-color"> so the mobile browser chrome matches.
export function useTheme() {
  const [pref, setPref] = useState(() => getSetting('theme', null))
  const prefersLight = useMediaQuery('(prefers-color-scheme: light)')
  const theme = resolveTheme(pref, prefersLight)

  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = theme
    const meta = document.querySelector('meta[name="theme-color"]')
    if (meta) meta.setAttribute('content', THEME_COLOR[theme] || THEME_COLOR.hermes)
  }, [theme])

  const choose = (id) => {
    setSetting('theme', id)
    setPref(id)
  }

  return { theme, pref, choose }
}

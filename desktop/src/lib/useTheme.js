import { useEffect, useState } from 'react'
import { getSetting, setSetting } from './settings.js'
import { useMediaQuery } from './useMediaQuery.js'

// The theme registry (4.0, D63). Each id maps to a `:root[data-theme="…"]` block in
// index.css (Light is the bare `:root`). With no stored choice the app follows the OS.
// The ids stay 'day' / 'hermes' so a choice already stored keeps working; only the
// names changed (4.1: Light and Dark).
export const THEMES = [
  { id: 'day',    label: 'Light',  hint: 'white · indigo', scheme: 'light', swatch: ['#fbfbf9', '#3b4cca'] },
  { id: 'hermes', label: 'Dark',   hint: 'black · gold',   scheme: 'dark',  swatch: ['#0e0e12', '#ffbf00'] },
  { id: 'paper',  label: 'Paper',  hint: 'light · warm',   scheme: 'light', swatch: ['#f6f1e7', '#9a5b17'] },
  { id: 'slate',  label: 'Slate',  hint: 'dark · cool',    scheme: 'dark',  swatch: ['#0f1419', '#5aa2f0'] }
]

const IDS = THEMES.map((t) => t.id)

export function resolveTheme(pref, prefersLight) {
  if (IDS.includes(pref)) return pref
  return prefersLight ? 'day' : 'hermes'
}

// Returns the active theme, the stored preference (null = follow the OS) and a
// setter (`choose(null)` goes back to following the OS). Keeps <html data-theme>
// and <meta name="theme-color"> in step so the phone's browser chrome matches.
export function useTheme() {
  const [pref, setPref] = useState(() => getSetting('theme', null))
  const prefersLight = useMediaQuery('(prefers-color-scheme: light)')
  const theme = resolveTheme(pref, prefersLight)

  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = theme
    const meta = document.querySelector('meta[name="theme-color"]')
    const t = THEMES.find((x) => x.id === theme) || THEMES[0]
    if (meta) meta.setAttribute('content', t.swatch[0])
  }, [theme])

  const choose = (id) => {
    const v = IDS.includes(id) ? id : null
    setSetting('theme', v)
    setPref(v)
  }

  return { theme, pref, choose }
}

// The two-way switch in the menu: whichever of Light / Dark you are not on.
export function oppositeOf(theme) {
  const t = THEMES.find((x) => x.id === theme)
  return t && t.scheme === 'dark' ? 'day' : 'hermes'
}

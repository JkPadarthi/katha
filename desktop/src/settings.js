// Tiny localStorage-backed settings store. Single-user, per-machine — no
// server round-trip. Values are JSON-encoded so numbers/booleans round-trip.

const PREFIX = 'katha.'

export function getSetting(key, fallback = null) {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    if (raw === null) return fallback
    return JSON.parse(raw)
  } catch {
    return fallback
  }
}

export function setSetting(key, value) {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value))
  } catch {
    /* storage may be unavailable (private mode) — settings are best-effort */
  }
}

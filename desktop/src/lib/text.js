// Small text helpers shared across the UI.

export function countWords(text) {
  const t = (text || '').trim()
  return t ? t.split(/\s+/).length : 0
}

export function clockNow() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

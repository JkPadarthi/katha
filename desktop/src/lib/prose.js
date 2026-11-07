/**
 * The paragraph rule (D50) — shared by the reading view and the EPUB builder.
 *
 * Mirrors `server/app/prose.py` exactly. Two chapters can be written two ways: one with
 * blank lines between paragraphs (single newlines are soft wraps), one with one line per
 * paragraph and no blank lines at all. Splitting only on blank lines renders the second
 * kind as a single enormous paragraph — no spacing, no gaps, and a one-wall EPUB.
 *
 * The rule: if the prose contains a blank line, blank lines separate paragraphs; if it
 * never does, every line is a paragraph. A leading heading and the blank line around it
 * are ignored when deciding.
 */

function kind(line) {
  const s = line.replace(/^\s+/, '')
  if (s.startsWith('#')) return 'h'
  if (s.startsWith('>')) return 'q'
  return 'p'
}

export function isBlankSeparated(text) {
  const lines = (text || '').split(/\r?\n/)
  const probe = lines.slice()
  while (probe.length && !probe[0].trim()) probe.shift()
  if (probe.length && kind(probe[0]) === 'h') probe.shift()
  // the blank line under the title must not decide the style either
  while (probe.length && !probe[0].trim()) probe.shift()
  // nor may a trailing newline: `split` keeps a trailing empty string where Python's
  // splitlines() drops it, and that difference alone flipped the rule (caught by the
  // JS/Python parity check).
  while (probe.length && !probe[probe.length - 1].trim()) probe.pop()
  return probe.some((l) => !l.trim())
}

export function proseBlocks(text) {
  const lines = (text || '').split(/\r?\n/)
  const blank = isBlankSeparated(text)
  const out = []
  let buf = []

  const flush = () => {
    if (buf.length) {
      out.push(buf.join('\n'))
      buf = []
    }
  }

  for (const raw of lines) {
    const ln = raw.replace(/\s+$/, '')
    if (!ln.trim()) {
      flush()
      continue
    }
    if (blank && buf.length && kind(ln) !== kind(buf[0])) flush()
    buf.push(ln)
    if (!blank) flush()        // line-separated: every line stands alone
  }
  flush()
  return out
}

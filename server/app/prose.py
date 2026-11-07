"""How prose is cut into paragraphs — one rule, shared by every renderer (3.0.6, D50).

Two of the author's chapters are written two different ways, both legitimately:

* ch-00 separates paragraphs with a **blank line**, and wraps a long paragraph across
  several lines — so a single newline there is a *soft wrap*.
* ch-01 puts every paragraph on **one line** with single newlines and no blank lines at
  all — so a single newline there *is* the paragraph break.

A renderer that only splits on blank lines sees ch-01 as a single 4,790-word paragraph: no
paragraph spacing, no paragraph indents, and an EPUB that is one wall of text with <br/>
everywhere. That was live, and the symptom the author reported ("only ch-0 is being
changed, not ch 1") is exactly this.

The rule: **if the prose contains a blank line, blank lines separate paragraphs; if it never
does, every line is a paragraph.** The decision ignores a leading heading and the blank line
around it, so a document whose only blank line sits under the title still counts as
line-separated. Pure functions, no I/O.
"""

from __future__ import annotations


def _kind(line: str) -> str:
    """h = heading, q = blockquote, p = prose. Blocks never merge across a change of kind."""
    s = line.lstrip()
    if s.startswith("#"):
        return "h"
    if s.startswith(">"):
        return "q"
    return "p"


def is_blank_separated(text: str) -> bool:
    """Does this manuscript use blank lines between paragraphs?

    The leading heading **and the blank line that follows it** are skipped before deciding:
    a document whose only blank line sits under the title is line-separated prose.
    """
    lines = (text or "").splitlines()
    probe = list(lines)
    while probe and not probe[0].strip():
        probe.pop(0)
    if probe and _kind(probe[0]) == "h":
        probe.pop(0)
    while probe and not probe[0].strip():
        probe.pop(0)
    while probe and not probe[-1].strip():
        probe.pop()          # trailing newlines say nothing about the style
    return any(not ln.strip() for ln in probe)


def split_paragraphs(text: str) -> list[str]:
    """Cut prose into blocks, each ready for one <p> / <h1> / <blockquote>.

    Blank lines are always a break. In a manuscript that never uses them, each line is a
    paragraph of its own; in one that does, single newlines stay inside the paragraph.
    """
    lines = (text or "").splitlines()
    blank = is_blank_separated(text)
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.append("\n".join(buf))
            buf.clear()

    for raw in lines:
        ln = raw.rstrip()
        if not ln.strip():
            flush()
            continue
        if blank and buf and _kind(ln) != _kind(buf[0]):
            flush()          # a heading or quote never swallows the prose around it
        buf.append(ln)
        if not blank:
            flush()          # line-separated: every line stands alone
    flush()
    return out

"""Word-level hunks — the unit of review for a proposed revision (3.0, D48).

The Muse hands over a whole chapter, but the author's decision is not one bit — it is one
decision per *place that changed*. Today's real revision moved ~138 words in 30 places;
all-or-nothing forces 30 decisions into one click.

This module is the only place that knows how a revision is cut into hunks, and the only
place that knows what "accept hunks 1 and 3, not 2" actually writes. Pure functions, no
I/O, so the maths can be tested against prose rather than hoped at.

Grouping rule (the same idea as git's context window): two changes separated by fewer than
`merge_gap` unchanged words belong to one hunk, because an author reading prose fixes a
sentence at a time, not a word at a time.
"""

from __future__ import annotations

import difflib
import re

# A word plus the whitespace that follows it (so joining always reproduces the text),
# falling back to bare whitespace for runs at the very start.
_TOKEN_RE = re.compile(r"\S+\s*|\s+")

MERGE_GAP = 8      # unchanged words that still join two changes into one hunk


def tokenize(text: str) -> list[str]:
    """Lossless tokens: `"".join(tokenize(t)) == t` for every t."""
    return _TOKEN_RE.findall(text or "")


def _offsets(tokens: list[str]) -> list[int]:
    out, n = [], 0
    for t in tokens:
        out.append(n)
        n += len(t)
    return out


def _groups(base: str, proposal: str, merge_gap: int) -> list[dict]:
    """Changed regions, with token ranges in both texts. Empty when identical."""
    bt, pt = tokenize(base), tokenize(proposal)
    boff, poff = _offsets(bt), _offsets(pt)
    if not bt and not pt:
        return []
    ops = [op for op in difflib.SequenceMatcher(None, bt, pt, autojunk=False).get_opcodes()
           if op[0] != "equal"]
    groups: list[dict] = []
    for tag, i1, i2, j1, j2 in ops:
        if groups:
            last = groups[-1]
            # ≤ merge_gap unchanged words since the previous change → same hunk.
            if i1 - last["i2"] <= merge_gap and j1 - last["j2"] <= merge_gap:
                last["i2"], last["j2"] = i2, j2
                last["op"] = "replace"
                continue
        groups.append({"op": tag, "i1": i1, "i2": i2, "j1": j1, "j2": j2})
    for n, g in enumerate(groups):
        g["id"] = n
        g["before"] = "".join(bt[g["i1"]:g["i2"]])
        g["after"] = "".join(pt[g["j1"]:g["j2"]])
        g["base_start"] = boff[g["i1"]] if g["i1"] < len(bt) else len(base)
        g["base_end"] = boff[g["i2"]] if g["i2"] < len(bt) else len(base)
        g["prop_start"] = poff[g["j1"]] if g["j1"] < len(pt) else len(proposal)
        g["prop_end"] = poff[g["j2"]] if g["j2"] < len(pt) else len(proposal)
    return groups


def hunks(base: str, proposal: str, merge_gap: int = MERGE_GAP) -> list[dict]:
    """The reviewable units of a revision, in reading order.

    Each hunk carries what it replaces (`before`), what it would say (`after`), and
    character offsets into both texts so a client can render the projection itself.
    """
    return [{k: v for k, v in g.items() if k not in ("i1", "i2", "j1", "j2")}
            for g in _groups(base, proposal, merge_gap)]


def validate_ids(groups: list[dict], ids) -> set[int]:
    """Unknown or duplicate hunk ids are a client bug, not something to guess at."""
    if ids is None:
        return {g["id"] for g in groups}
    wanted = set(int(i) for i in ids)
    known = {g["id"] for g in groups}
    unknown = wanted - known
    if unknown:
        raise ValueError(f"no such hunk(s): {sorted(unknown)}")
    return wanted


def merge(base: str, proposal: str, accepted=None, merge_gap: int = MERGE_GAP) -> str:
    """The prose a subset of hunk decisions produces.

    `accepted=None` means every hunk (the old all-or-nothing accept). An empty set gives
    the base back unchanged — which is what makes "reject everything" honest rather than
    a second code path.
    """
    groups = _groups(base, proposal, merge_gap)
    taken = validate_ids(groups, accepted)
    bt, pt = tokenize(base), tokenize(proposal)
    out: list[str] = []
    pos = 0
    for g in groups:
        if g["id"] in taken:
            out.append("".join(bt[pos:g["i1"]]))
            out.append("".join(pt[g["j1"]:g["j2"]]))
            pos = g["i2"]
    out.append("".join(bt[pos:]))
    return "".join(out)

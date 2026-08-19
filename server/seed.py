"""Seed the md archive from the Phase-0.1 mock data (data.js).

Turns the mock The Ember Throne / The First Flame into real .md files on
disk — proving the full round-trip: files → SQLite index → CRUD → revision.
Idempotent: existing files are left untouched unless --force.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app import archive as ar
from app.config import ARCHIVE_ROOT

# Faithful mirror of desktop/src/data.js + sampleProse.
ARCHIVE = [
    {
        "series": "The Ember Throne",
        "book": "The First Flame",
        "chapters": [
            ("The Dying Ember", 1243),
            ("The Road to Varna", 1892),
            ("The Inn at Crosswater", 1547),
            ("Kael's Bargain", 2110),
        ],
        "bible": {
            "characters.md": "# Characters\n\n## Kael\n- Mute-eyed, carries a debt.\n- Speaks in clipped, low-register lines.\n\n## The Innkeeper\n- Hems and haws; doesn't want trouble.\n",
            "places.md": "# Places\n\n## Crosswater\n- A wayside inn where the roads meet.\n\n## Varna\n- A city downhill; where debts get paid.\n",
            "timeline.md": "# Timeline\n\n- The fire burned low at Crosswater.\n- A stranger arrived with a doubled price on Kael's head.\n",
        },
    }
]

SAMPLE_PROSE = """The fire in the hearth had burned low, and the inn at Crosswater had grown quiet with it. Kael sat at the long table with a cup he had long stopped drinking from, watching the smoke climb toward the beams.

The door opened.

He did not look up — not yet. Some men you know by the weight of their step, and this one walked like a man carrying a debt.

"I heard you were dead," the stranger said.

Kael turned the cup slowly. "You heard wrong."

"Then you'll be glad to know the price on your head has doubled since the spring."

Now he looked. The gold by the door caught the lamplight, and in the stranger's eyes he saw the road ahead of him — long, and dark, and already paid for."""

# Short faithful bodies for chapters 2-4 (mock only carried titles+word counts).
CHAPTER_BODIES = {
    1: SAMPLE_PROSE,
    2: "The road to Varna unspooled under a grey dawn, and Kael kept his silence the way other men keep a weapon.\n\n# placeholder — seeded from mock; full text arrives with the author.",
    3: "A second fire in Crosswater, a third stranger, and the innkeeper's voice gone thin as smoke.\n\n# placeholder — seeded from mock; full text arrives with the author.",
    4: "Kael struck the bargain that had been waiting for him since the first page.\n\n# placeholder — seeded from mock; full text arrives with the author.",
}


def seed(force: bool = False, quiet: bool = False) -> list[str]:
    written = []
    for entry in ARCHIVE:
        meta = ar.ensure_book(entry["series"], entry["book"])
        bdir = ar.book_dir(entry["series"], entry["book"])
        # bible files
        bd = ar.bible_dir(bdir)
        bd.mkdir(parents=True, exist_ok=True)
        for name, content in entry["bible"].items():
            p = bd / name
            if force or not p.exists():
                p.write_text(content, encoding="utf-8")
                written.append(p.relative_to(ARCHIVE_ROOT).as_posix())
        # chapters
        existing = ar.list_chapters(bdir)
        existing_ids = {c["id"] for c in existing}
        for i, (title, _words) in enumerate(entry["chapters"], start=1):
            cid = f"ch-{i:02d}"
            if cid in existing_ids and not force:
                continue
            body = CHAPTER_BODIES.get(i, "")
            # reuse create_chapter which assigns next number — but we want ch-0N
            # matching mock ids, so write directly with the matching name.
            p = bdir / "chapters" / f"{cid}.md"
            p.write_text(f"# {title}\n\n{body}".rstrip() + "\n", encoding="utf-8")
            written.append(p.relative_to(ARCHIVE_ROOT).as_posix())
    if not quiet:
        for w in written:
            print(f"  ✓ {w}")
        print(f"\nSeeded {len(written)} files under {ARCHIVE_ROOT}")
    return written


if __name__ == "__main__":
    seed(force="--force" in sys.argv)

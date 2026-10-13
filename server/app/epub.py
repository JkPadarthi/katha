"""EPUB export (1.0) — stdlib only (zipfile), no new dependencies.

Builds a valid EPUB 3 from a book's chapters (and its bible as an appendix).
Nothing leaves the Pi; no DRM. The author downloads the file and sends it to
Kindle/Komga however they like.

The `mimetype` entry MUST be the first entry in the archive and STORED
(uncompressed) — readers reject the file otherwise.
"""

from __future__ import annotations

import html
import io
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import archive as ar

_CSS = """body { font-family: Georgia, serif; line-height: 1.6; margin: 1em; }
h1 { font-size: 1.6em; } h2 { font-size: 1.25em; }
blockquote { margin: 1em 2em; font-style: italic; color: #444; }
p { margin: 0 0 1em 0; }
"""

_CONTAINER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
    '  <rootfiles>\n'
    '    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
    '  </rootfiles>\n'
    '</container>\n'
)


def _xhtml(title: str, body_html: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">\n'
        '<head><meta charset="utf-8"/>'
        f'<title>{html.escape(title)}</title>'
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
        f'<body>{body_html}</body>\n'
        '</html>\n'
    )


def _md_to_html(md: str) -> str:
    out = []
    for block in re.split(r"\n\s*\n", md or ""):
        t = block.strip()
        if not t:
            continue
        if t.startswith("## "):
            out.append(f"<h2>{html.escape(t[3:].strip())}</h2>")
        elif t.startswith("# "):
            out.append(f"<h1>{html.escape(t[2:].strip())}</h1>")
        elif t.startswith(">"):
            text = html.escape(re.sub(r"^>\s?", "", t, flags=re.M)).replace("\n", "<br/>")
            out.append(f"<blockquote><p>{text}</p></blockquote>")
        else:
            out.append("<p>" + html.escape(t).replace("\n", "<br/>") + "</p>")
    return "\n".join(out)


def _docs(bdir: Path) -> list[tuple[str, str, str]]:
    """(filename, title, html) for every chapter + bible entry."""
    docs: list[tuple[str, str, str]] = []
    cd = bdir / "chapters"
    if cd.is_dir():
        for f in sorted(cd.glob("ch-*.md")):
            if not re.fullmatch(r"ch-\d{2}\.md", f.name):
                continue
            docs.append((f"{f.stem}.xhtml", ar._chapter_title(f), _md_to_html(f.read_text(encoding="utf-8"))))
    for name, text in sorted(ar.read_bible(bdir).items()):
        stem = Path(name).stem
        docs.append((f"bible-{stem}.xhtml", stem.title(), _md_to_html(text)))
    return docs


def build_epub(series_title: str, book_title: str, bdir: Path) -> bytes:
    uid = "urn:uuid:" + str(uuid.uuid4())
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    docs = _docs(bdir)

    manifest, spine, nav_li, nav_points = [], [], [], []
    for i, (fn, title, _) in enumerate(docs, start=1):
        manifest.append(f'<item id="{fn}" href="{fn}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{fn}"/>')
        nav_li.append(f'<li><a href="{fn}">{html.escape(title)}</a></li>')
        nav_points.append(
            f'<navPoint id="np{i}" playOrder="{i}">'
            f'<navLabel><text>{html.escape(title)}</text></navLabel>'
            f'<content src="{fn}"/></navPoint>'
        )

    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="bookid">{uid}</dc:identifier>\n'
        f'    <dc:title>{html.escape(book_title)}</dc:title>\n'
        '    <dc:language>en</dc:language>\n'
        f'    <meta property="dcterms:modified">{modified}</meta>\n'
        '  </metadata>\n'
        '  <manifest>\n'
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>\n'
        '    <item id="css" href="style.css" media-type="text/css"/>\n'
        '    ' + "\n    ".join(manifest) + "\n"
        '  </manifest>\n'
        '  <spine toc="ncx">\n'
        '    ' + "\n    ".join(spine) + "\n"
        '  </spine>\n'
        '</package>\n'
    )

    nav = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
        'xml:lang="en" lang="en">\n'
        f'<head><meta charset="utf-8"/><title>{html.escape(book_title)}</title></head>\n'
        '<body><nav epub:type="toc" id="toc"><h1>Contents</h1><ol>'
        + "".join(nav_li) +
        "</ol></nav></body>\n</html>\n"
    )

    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        f'  <head><meta name="dtb:uid" content="{uid}"/></head>\n'
        f'  <docTitle><text>{html.escape(book_title)}</text></docTitle>\n'
        '  <navMap>' + "".join(nav_points) + "</navMap>\n"
        '</ncx>\n'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", nav)
        z.writestr("OEBPS/toc.ncx", ncx)
        z.writestr("OEBPS/style.css", _CSS)
        for fn, title, body in docs:
            z.writestr(f"OEBPS/{fn}", _xhtml(title, body))
    return buf.getvalue()

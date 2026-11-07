"""EPUB export (1.0; cover + author 2.8, D43) — stdlib only, no new deps.

Builds a valid EPUB 3 from a book's chapters (and its bible as an appendix), with
the book's author in the metadata and, when the author has uploaded one, its
cover. Nothing leaves the Pi; no DRM. The author downloads the file and sends it
to Kindle/Komga however they like.

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
from . import prose

_CSS = """body { font-family: Georgia, serif; line-height: 1.6; margin: 1em; }
h1 { font-size: 1.6em; } h2 { font-size: 1.25em; }
blockquote { margin: 1em 2em; font-style: italic; color: #444; }
p { margin: 0 0 1em 0; }
"""

# The cover page. A full-bleed <img> in a centred div is the shape every reader
# understands; `page-break-after` keeps the first chapter off the cover.
# NOTE: the alt text is substituted with `.replace()`, not `.format()` — the CSS
# braces below are not format fields, and `.format()` reads them as ones.
_COVER_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">
<head><meta charset="utf-8"/><title>Cover</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%; }
  div.cover { margin: 0; padding: 0; text-align: center; page-break-after: always; }
  img { max-width: 100%; max-height: 100%; }
</style></head>
<body><div class="cover"><img src="cover.jpg" alt="__ALT__"/></div></body>
</html>
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
    for block in prose.split_paragraphs(md or ""):
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
    for f in ar.chapter_files(bdir / "chapters"):
        docs.append((f"{f.stem}.xhtml", ar._chapter_title(f), _md_to_html(f.read_text(encoding="utf-8"))))
    for name, text in sorted(ar.read_bible(bdir).items()):
        base = name.split("/")[-1].rsplit(".", 1)[0]
        slug = name.rsplit(".", 1)[0].replace("/", "-")
        docs.append((f"bible-{slug}.xhtml", base.replace("-", " ").title(), _md_to_html(text)))
    return docs


def build_epub(series_title: str, book_title: str, bdir: Path,
               author: str = "", cover: bytes | None = None) -> bytes:
    """Build the EPUB. 2.8: the author goes in the metadata, and a book with a
    cover gets a real cover page.

    `cover` is the already-normalised JPEG (see `archive.cover_path`). Wiring it
    correctly is fussier than it looks — a reader shows nothing if the image item
    lacks `properties="cover-image"`, or the cover page isn't FIRST in the spine,
    or the legacy `<meta name="cover">` that Kindle's converters still read is
    missing.
    """
    uid = "urn:uuid:" + str(uuid.uuid4())
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    docs = _docs(bdir)
    author = (author or "").strip()

    manifest, spine, nav_li, nav_points = [], [], [], []
    if cover:
        manifest.append('<item id="cover-image" href="cover.jpg" '
                        'media-type="image/jpeg" properties="cover-image"/>')
        manifest.append('<item id="cover" href="cover.xhtml" '
                        'media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="cover"/>')
    for i, (fn, title, _) in enumerate(docs, start=1):
        manifest.append(f'<item id="{fn}" href="{fn}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{fn}"/>')
        nav_li.append(f'<li><a href="{fn}">{html.escape(title)}</a></li>')
        nav_points.append(
            f'<navPoint id="np{i}" playOrder="{i}">'
            f'<navLabel><text>{html.escape(title)}</text></navLabel>'
            f'<content src="{fn}"/></navPoint>'
        )

    meta_lines = [
        f'    <dc:identifier id="bookid">{uid}</dc:identifier>',
        f'    <dc:title>{html.escape(book_title)}</dc:title>',
    ]
    # No author on the book = no dc:creator at all; a library grid showing
    # "Unknown" is worse than showing nothing.
    if author:
        meta_lines.append(f'    <dc:creator>{html.escape(author)}</dc:creator>')
    meta_lines.append('    <dc:language>en</dc:language>')
    if cover:
        # Legacy signal, and still the one Kindle's converter looks for.
        meta_lines.append('    <meta name="cover" content="cover-image"/>')
    meta_lines.append(f'    <meta property="dcterms:modified">{modified}</meta>')

    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        + "\n".join(meta_lines) + "\n"
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
        + ('  <guide><reference type="cover" href="cover.xhtml"/></guide>\n' if cover else '')
        + '</package>\n'
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
        if cover:
            # A plain <img> in a centred div: the most widely understood cover
            # page. (An SVG wrapper scales marginally better but silently shows
            # nothing on readers that don't render SVG in the spine.)
            z.writestr("OEBPS/cover.jpg", cover)
            z.writestr("OEBPS/cover.xhtml",
                       _COVER_XHTML.replace("__ALT__",
                                            html.escape(book_title, quote=True)))
        for fn, title, body in docs:
            z.writestr(f"OEBPS/{fn}", _xhtml(title, body))
    return buf.getvalue()

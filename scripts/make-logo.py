#!/usr/bin/env python3
"""Draw Katha's logo: a black tile with a golden क, lit from the upper left.

Katha = कथा. The mark is the first letter — and the first sound of the word — so
the icon is a tile in the app's own colours (base #0e0e12, accent #ffbf00)
carrying a single Devanagari क, rendered as *metal*: light falls from one side, so
the surface runs champagne → gold → amber as it turns away, with a specular band
across it and a soft shadow lifting it off the tile.

The lighting is deliberately ONE linear ramp along (x + y) — which is exactly what
an SVG `linearGradient` from (0,0) to (1,1) does — so the vector and the rasters
can never disagree about where the light is.

Reproduce everything with:

    python -m venv /tmp/logoenv && /tmp/logoenv/bin/pip install -r scripts/requirements-logo.txt
    /tmp/logoenv/bin/python scripts/make-logo.py --font /path/to/NotoSansDevanagari-SemiBold.ttf

It writes `desktop/public/logo.svg` (used by the UI) and the PWA/apple/favicon PNGs
into `desktop/public/icons/`. The glyph comes from **Noto Sans Devanagari**
(SIL OFL 1.1, © The Noto Project Authors), which is not committed — fetch it once:

    curl -Lo /tmp/NotoSansDevanagari-SemiBold.ttf \\
      https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/fonts/\\
NotoSansDevanagari/hinted/ttf/NotoSansDevanagari-SemiBold.ttf

Without `--font` the script falls back to FreeSans (GNU FreeFont, also free) so the
assets can always be rebuilt.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

BASE = "#0e0e12"        # --color-base (Hermes theme)
BASE_TOP = "#17171d"    # a whisper of depth at the top of the tile
GLYPH = "क"             # U+0915

# The metal: highlight → body → turn-away. 0.52 IS the app's accent (#ffbf00); the
# ends are what light does to gold — champagne where it strikes, amber where the
# surface faces away. Never white (that reads silver) and never brown (tarnished).
METAL = [
    (0.00, "#ffeba8"),
    (0.24, "#ffd660"),
    (0.52, "#ffbf00"),
    (0.78, "#c48d10"),
    (1.00, "#8c5c12"),
]
SHEEN_PEAK = 0.30       # where the specular band sits along the ramp
SHEEN_GAIN = 0.45       # how much light the band adds
SHEEN_WIDTH = 0.24      # half-width of the band
SHADOW = 0.012          # shadow offset as a fraction of the tile
SHADOW_BLUR = 0.035     # …and its blur
SHADOW_OPACITY = 0.55

INK = 0.62              # how much of the tile the glyph's ink fills
INK_MASKABLE = 0.48     # inside the 80% safe circle, with margin
INK_IOS = 0.56          # full-bleed; iOS rounds it itself
INK_FAVICON = 0.78      # 32px needs the ink to shout
INK_FAVICON_16 = 0.86   # at 16px the loop closes up unless it's pushed further
CORNER = 0.22           # corner radius as a fraction of the tile
THICKEN = 1             # MaxFilter radius: a hair of extra weight for a dark tile
THICKEN_FAVICON = 2     # at 32px a hair is not enough
SUPERSAMPLE = 4         # rasterise big, downscale: PIL at 32px is ugly

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "desktop" / "public"
ICONS = PUBLIC / "icons"
_FONT = ""


def _rgb(hx: str) -> list[int]:
    return [int(hx[i:i + 2], 16) for i in (1, 3, 5)]


def _load_font(path: str | None) -> str:
    if path:
        return path
    for candidate in (
        pathlib.Path("/tmp/NotoSansDevanagari-SemiBold.ttf"),
        pathlib.Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"),
    ):
        if candidate.is_file():
            print(f"note: no --font given, using {candidate}")
            return str(candidate)
    sys.exit("no font found — pass --font /path/to/NotoSansDevanagari-SemiBold.ttf")


def _ramp(size: tuple[int, int], peak: float | None = None):
    """`t` growing along (x + y): light arriving from the top-left corner.

    Built by hand rather than by rotating a gradient — rotating leaves black
    triangles outside the rotated square, and resizing those in poisons the
    corners. `t = (x + y) / (w + h)` is exactly a `linearGradient` from (0,0) to
    (1,1) in SVG.

    With `peak`, returns the specular band instead: a narrow bright streak centred
    on that point of the ramp, faded smoothly both ways.
    """
    from PIL import Image

    n = 160
    small = Image.new("L", (n, n))
    px = small.load()
    for y in range(n):
        for x in range(n):
            px[x, y] = int(round(255 * (x + y) / (2 * (n - 1))))
    grad = small.resize(size, Image.BICUBIC)
    if peak is None:
        return grad

    def lut(v: int) -> int:
        d = abs(v / 255 - peak) / SHEEN_WIDTH
        return 0 if d >= 1 else int(255 * (1 - d) ** 2)

    return grad.point(lut)


def _metal(grad):
    """Map a 0..255 ramp through the METAL stops."""
    from PIL import Image

    def channel(i: int) -> list[int]:
        lut = []
        for v in range(256):
            t = v / 255
            lo = max((s for s in METAL if s[0] <= t), key=lambda s: s[0])
            hi = min((s for s in METAL if s[0] >= t), key=lambda s: s[0])
            f = 0 if hi[0] == lo[0] else (t - lo[0]) / (hi[0] - lo[0])
            lut.append(round(_rgb(lo[1])[i] * (1 - f) + _rgb(hi[1])[i] * f))
        return lut

    return Image.merge(
        "RGB", [grad.point(channel(0)), grad.point(channel(1)), grad.point(channel(2))]
    )


def _gold(size: tuple[int, int]):
    """The metal body plus its specular band — added light, not a painted stripe."""
    from PIL import Image, ImageChops

    gold = _metal(_ramp(size))
    band = _ramp(size, peak=SHEEN_PEAK).point(lambda v: int(v * SHEEN_GAIN))
    return ImageChops.screen(gold, Image.merge("RGB", (band, band, band)))


def _glyph_mask(size: int, ink: float, thicken: int = THICKEN):
    """The glyph as an L mask, cropped to its ink and scaled to `ink` × `size`.

    Rasterised at SUPERSAMPLE× and downscaled: PIL's own hinting at 32px destroys
    a Devanagari glyph, while 128→32 with LANCZOS keeps it readable.
    """
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    big = max(size * SUPERSAMPLE, 512)
    probe = ImageFont.truetype(_FONT, big)
    bbox = probe.getbbox(GLYPH)
    gw, gh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = big
    layer = Image.new("L", (big * 3, big * 3), 0)
    ImageDraw.Draw(layer).text(
        (big * 1.5 - gw / 2 - bbox[0], big * 1.5 - gh / 2 - bbox[1]),
        GLYPH, font=probe, fill=255,
    )
    layer = layer.crop((int(big * 1.5 - gw / 2 - pad),
                        int(big * 1.5 - gh / 2 - pad),
                        int(big * 1.5 + gw / 2 + pad),
                        int(big * 1.5 + gh / 2 + pad)))
    if thicken:
        layer = layer.filter(ImageFilter.MaxFilter(thicken * 2 + 1))
    layer = layer.crop(layer.getbbox())
    # The crop IS the ink, so this is the same maths the SVG uses.
    target = max(1, int(size * ink))
    scale = target / max(layer.size)
    return layer.resize((max(1, round(layer.size[0] * scale)),
                         max(1, round(layer.size[1] * scale))), Image.LANCZOS)


def _tile(size: int, ink: float, rounded: bool, thicken: int = THICKEN):
    from PIL import Image, ImageDraw, ImageFilter

    layer = _glyph_mask(size, ink, thicken)      # already scaled + ink-cropped
    pos = ((size - layer.size[0]) // 2, (size - layer.size[1]) // 2)

    # Tile background: a whisper of vertical depth.
    bg = Image.new("RGB", (size, size), BASE)
    bd = ImageDraw.Draw(bg)
    top, bot = _rgb(BASE_TOP), _rgb(BASE)
    for y in range(size):
        f = y / max(1, size - 1)
        bd.line([(0, y), (size, y)],
                fill=tuple(round(top[i] * (1 - f) + bot[i] * f) for i in range(3)))

    # The shadow falls away from the light: down and to the right.
    shadow = layer.filter(ImageFilter.GaussianBlur(size * SHADOW_BLUR)).point(
        lambda v: int(v * SHADOW_OPACITY))
    bg.paste(Image.new("RGB", layer.size, (0, 0, 0)),
             (pos[0] + int(size * SHADOW), pos[1] + int(size * SHADOW * 1.35)), shadow)
    bg.paste(_gold(layer.size), pos, layer)

    if not rounded:
        # Full bleed: what a maskable/iOS icon must be (the OS crops it itself).
        return bg

    # alpha = 255 inside the rounded tile, 0 outside.
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * CORNER), fill=255,
    )
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(bg, (0, 0), mask)
    return out


def _svg() -> str:
    """The same mark as vector: the glyph's outline, straight from the font.

    The metal is extra stops in ONE `linearGradient` (0,0)→(1,1) — the same ramp
    the rasters use, with the specular band folded in at SHEEN_PEAK — so no blend
    modes are needed and it renders inside an <img> tag.
    """
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.ttLib import TTFont

    font = TTFont(_FONT)
    cmap = font.getBestCmap()
    if ord(GLYPH) not in cmap:
        sys.exit(f"{_FONT} has no glyph for {GLYPH}")
    name = cmap[ord(GLYPH)]
    glyphs = font.getGlyphSet()
    pen = SVGPathPen(glyphs)
    glyphs[name].draw(pen)
    bounds = BoundsPen(glyphs)
    glyphs[name].draw(bounds)
    x0, y0, x1, y1 = bounds.bounds
    gw, gh = x1 - x0, y1 - y0

    size = 512
    scale = (size * INK) / max(gw, gh)
    # Centre the ink: translate so the glyph's bbox middle sits at the tile middle
    # (SVG y grows downwards, font y grows upwards, hence the flip).
    tx = (size - gw * scale) / 2 - x0 * scale
    ty = (size + gh * scale) / 2 + y0 * scale

    stops = "".join(f'\n      <stop offset="{p:.2f}" stop-color="{c}"/>' for p, c in METAL)
    lo = max((s for s in METAL if s[0] <= SHEEN_PEAK), key=lambda s: s[0])
    hi = min((s for s in METAL if s[0] >= SHEEN_PEAK), key=lambda s: s[0])
    f = 0 if hi[0] == lo[0] else (SHEEN_PEAK - lo[0]) / (hi[0] - lo[0])
    base = [round(_rgb(lo[1])[i] * (1 - f) + _rgb(hi[1])[i] * f) for i in range(3)]
    lit = [round(v + (255 - v) * SHEEN_GAIN) for v in base]
    peak = "#%02x%02x%02x" % tuple(lit)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" role="img" aria-label="Katha">
  <title>Katha</title>
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{BASE_TOP}"/>
      <stop offset="1" stop-color="{BASE}"/>
    </linearGradient>
    <!-- Light from the top-left: one (x + y) ramp, exactly as generated. -->
    <linearGradient id="gold" x1="0" y1="0" x2="1" y2="1">{stops}
      <stop offset="{SHEEN_PEAK:.2f}" stop-color="{peak}"/>
    </linearGradient>
    <filter id="lift" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="{size * SHADOW:.1f}" dy="{size * SHADOW * 1.35:.1f}"
                    stdDeviation="{size * SHADOW_BLUR:.1f}"
                    flood-color="#000000" flood-opacity="{SHADOW_OPACITY}"/>
    </filter>
  </defs>
  <rect width="{size}" height="{size}" rx="{round(size * CORNER)}" fill="url(#tile)"/>
  <g filter="url(#lift)">
    <g transform="translate({tx:.2f} {ty:.2f}) scale({scale:.5f} -{scale:.5f})">
      <path d="{pen.getCommands()}" fill="url(#gold)"/>
    </g>
  </g>
</svg>
"""


def main() -> None:
    global _FONT
    ap = argparse.ArgumentParser(description="Draw Katha's क logo.")
    ap.add_argument("--font", help="path to NotoSansDevanagari-SemiBold.ttf")
    args = ap.parse_args()
    _FONT = _load_font(args.font)

    ICONS.mkdir(parents=True, exist_ok=True)
    (PUBLIC / "logo.svg").write_text(_svg(), encoding="utf-8")

    jobs = [
        ("icon-512.png", 512, INK, True, THICKEN),
        ("icon-192.png", 192, INK, True, THICKEN),
        # Maskable: full-bleed, no rounding, glyph well inside the safe circle.
        ("maskable-512.png", 512, INK_MASKABLE, False, THICKEN),
        # iOS rounds the tile itself and hates transparency.
        ("apple-touch-icon.png", 180, INK_IOS, False, THICKEN),
        # 32px: a heavier glyph, because a hair of extra weight isn't enough there.
        ("favicon-32.png", 32, INK_FAVICON, True, THICKEN_FAVICON),
        # 16px is the browser-tab size: the glyph needs every bit of ink it can get.
        ("favicon-16.png", 16, INK_FAVICON_16, True, THICKEN_FAVICON),
    ]
    for name, size, ink, rounded, thicken in jobs:
        _tile(size, ink, rounded, thicken).save(ICONS / name, optimize=True)
        print(f"  ✓ icons/{name}  ({size}×{size})")
    print("  ✓ logo.svg       (vector)")


if __name__ == "__main__":
    main()

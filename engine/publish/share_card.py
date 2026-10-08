"""A league's default share images, for a league without a logo (Ethan, 2026-10-08: a family league
link sent to a chat showed Preach's logo).

A chat app shows the image a page's og:image tag names; with none, some apps fall back to an icon
they hold for the site's host, and every league on one GitHub Pages host shares that host, so a
league without a logo showed another league's. `write_cards` draws two PNGs from the league's
name and year colors and the share tags point at them:

- assets/share/card.png (1200 x 630): the link preview's image
- assets/share/icon.png (180 x 180): the page icon (favicon, apple-touch-icon), the league's initials

The drawing uses Pillow and the first bold serif font it finds (DejaVu on the GitHub runner), else
Pillow's own font. Same inputs, same bytes.
"""

from __future__ import annotations

from pathlib import Path

CARD = "assets/share/card.png"
ICON = "assets/share/icon.png"

BG, BG_EDGE = (213, 207, 200), (196, 188, 180)          # site.css --bg, and a shade darker
TEXT, MID = (44, 42, 40), (90, 85, 80)                   # --text, --text-mid
PALM = (61, 58, 56)                                      # --palm
SERIF = ["/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
         "/Library/Fonts/Georgia Bold.ttf", "C:/Windows/Fonts/georgiab.ttf"]
SANS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/arial.ttf"]


def _font(paths, size):
    from PIL import ImageFont
    for p in paths:
        if Path(p).is_file():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def initials(name: str) -> str:
    """'Radecki Family League' -> 'RFL' (at most three letters)."""
    words = [w for w in name.replace("-", " ").split() if w[:1].isalnum()]
    return "".join(w[0].upper() for w in words[:3]) or "FF"


def _lines(draw, text, font, width):
    """text wrapped to fit width, word by word."""
    out, line = [], ""
    for w in text.split():
        trial = (line + " " + w).strip()
        if line and draw.textlength(trial, font=font) > width:
            out.append(line)
            line = w
        else:
            line = trial
    return out + ([line] if line else [])


def _background(img):
    """the site's warm grey, darkening slightly toward the bottom."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    w, h = img.size
    for y in range(h):
        t = y / max(h - 1, 1)
        d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(BG, BG_EDGE)))
    return d


def card(name: str, subtitle: str, colors: list[str]):
    """The 1200 x 630 link preview: the league name, a line under it, a band of the year colors."""
    from PIL import Image
    img = Image.new("RGB", (1200, 630))
    d = _background(img)
    size = 104
    font = _font(SERIF, size)
    lines = _lines(d, name, font, 1040)
    while (len(lines) > 2 or any(d.textlength(x, font=font) > 1040 for x in lines)) and size > 48:
        size -= 6
        font = _font(SERIF, size)
        lines = _lines(d, name, font, 1040)
    sub = _font(SANS, 36)
    line_h = round(size * 1.15)
    top = 315 - (len(lines) * line_h + 30 + 44) // 2 - 20
    for i, x in enumerate(lines):
        d.text((80, top + i * line_h), x, font=font, fill=TEXT)
    d.text((80, top + len(lines) * line_h + 30), subtitle, font=sub, fill=MID)
    d.rectangle([80, top - 40, 200, top - 32], fill=PALM)
    band = [_hex(c) for c in colors] or [PALM]
    w = 1200 / len(band)
    for i, c in enumerate(band):
        d.rectangle([round(i * w), 590, round((i + 1) * w), 630], fill=c)
    return img


def icon(name: str, color: str | None):
    """The 180 x 180 page icon: the league's initials on its latest year color."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (180, 180), _hex(color) if color else BG)
    d = ImageDraw.Draw(img)
    text = initials(name)
    size = 84 if len(text) < 3 else 64
    font = _font(SERIF, size)
    box = d.textbbox((0, 0), text, font=font)
    d.text(((180 - (box[2] - box[0])) / 2 - box[0], (180 - (box[3] - box[1])) / 2 - box[1]), text,
           font=font, fill=TEXT)
    return img


def write_cards(dest: Path, config: dict) -> list[str]:
    """Write the card and icon under dest for a league without a logo; returns their paths relative
    to dest (none when the league has a logo or no name, or Pillow is not installed)."""
    league = config.get("league") or {}
    if not league.get("name") or league.get("logo") or any((league.get("logos_by_season") or {}).values()):
        return []
    try:
        import PIL  # noqa: F401
    except ImportError:
        return []
    seasons = sorted((config.get("theme") or {}).get("season_colors", {}).items())
    colors = [c for _, c in seasons]
    first = league.get("first_season")
    subtitle = f"League history and analytics since {first}" if first else "League history and analytics"
    out = []
    for rel, img in ((CARD, card(league["name"], subtitle, colors)),
                     (ICON, icon(league["name"], colors[-1] if colors else None))):
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        img.save(dest / rel, format="PNG", optimize=True)
        out.append(rel)
    return out

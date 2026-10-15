"""Light images for the site (decision 7.18): the pages show small WebP copies of the league's images.

A league's image files are kept as they are (logos, champion photos, rankings screenshots: what
the commissioner uploaded, often far larger than they are shown). The build writes a resized WebP
copy of each one the site refers to, under `images/_opt/`, and the new site's config.json and page
data point to the copies:

    manager and championship logos   192 px on the longer side (shown at 90 px at most: sharp on
                                     a 2x screen)
    league logos                     256 px
    photos and screenshots           1600 px

An image already that small and light keeps its original. The originals stay published (link
previews use the league logo at full size; pages fall back to them). Example on Preach: logos
1.3 MB to about 0.1 MB, the screenshots 26 MB to about 4 MB.
"""

from __future__ import annotations

import re
from pathlib import Path

LOGO_PX, LEAGUE_LOGO_PX, PHOTO_PX = 192, 256, 1600
OPT_DIR = "images/_opt"
RASTER = (".png", ".jpg", ".jpeg")
IMAGE_PATH = re.compile(r"^images/[^?#]+\.(?:png|jpe?g)$", re.I)


def opt_path(rel: str, px: int) -> str:
    stem = Path(rel).with_suffix("").as_posix()
    if stem.startswith("images/"):
        stem = stem[len("images/"):]
    return f"{OPT_DIR}/{stem}-{px}.webp"


class Optimizer:
    """Writes each resized copy once per build; `src` holds the originals, `dest` is the site."""

    def __init__(self, src: Path, dest: Path):
        self.src, self.dest = Path(src), Path(dest)
        self.done: dict[tuple[str, int], str] = {}
        self.written: list[str] = []
        self.bytes_before = self.bytes_after = 0

    def __call__(self, rel, px: int):
        """The path to show for image `rel` (relative to the site root), or `rel` unchanged when it is
        not a local raster image or the copy would not be lighter."""
        if not isinstance(rel, str) or not IMAGE_PATH.match(rel.lstrip("/")):
            return rel
        rel = rel.lstrip("/")
        key = (rel, px)
        if key in self.done:
            return self.done[key]
        src = self.src / rel
        result = rel
        if src.is_file():
            from PIL import Image

            out_rel = opt_path(rel, px)
            out = self.dest / out_rel
            with Image.open(src) as im:
                im.load()
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA" if "transparency" in im.info or im.mode in ("LA", "PA", "P") else "RGB")
                im.thumbnail((px, px), Image.LANCZOS)
                out.parent.mkdir(parents=True, exist_ok=True)
                im.save(out, "WEBP", quality=82 if px >= PHOTO_PX else 88, method=4)
            before, after = src.stat().st_size, out.stat().st_size
            if after < before * 0.9:
                result = out_rel
                self.written.append(out_rel)
                self.bytes_before += before
                self.bytes_after += after
            else:
                out.unlink()
        self.done[key] = result
        return result


def light_config(config: dict, opt: Optimizer) -> dict:
    """config.json with every logo pointing at its small copy."""
    cfg = dict(config)
    league = dict(cfg.get("league") or {})
    league["logo"] = opt(league.get("logo"), LEAGUE_LOGO_PX)
    league["logos_by_season"] = {s: opt(p, LEAGUE_LOGO_PX) for s, p in (league.get("logos_by_season") or {}).items()}
    cfg["league"] = league
    cfg["managers"] = [m | {"logo": opt(m.get("logo"), LOGO_PX),
                            "championship_logos": {s: opt(p, LOGO_PX)
                                                   for s, p in (m.get("championship_logos") or {}).items()}}
                       for m in cfg.get("managers") or []]
    return cfg


def light_data(obj, opt: Optimizer, key: str = ""):
    """A page model with every local image path pointing at its small copy (keys naming a logo at
    logo size, anything else at photo size)."""
    if isinstance(obj, dict):
        return {k: light_data(v, opt, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [light_data(v, opt, key) for v in obj]
    if isinstance(obj, str) and IMAGE_PATH.match(obj.lstrip("/")):
        return opt(obj, LOGO_PX if "logo" in key.lower() else PHOTO_PX)
    return obj

"""The Stage B preview: the new pages (web/) built at /next/ beside the live site (milestone M2,
docs/PUBLISH_PLAN.md section 8; Ethan 2026-10-06: preview first, then one switch).

`write_preview` copies web/ into <dist>/next/ with what the pages read: config.json, the page
models (data/v1/) and, for the league on the Stage A site, its images. Pages not moved to web/ yet stay reachable: on a
league with the Stage A site their nav links point at the live page (../pages/...), on any
other league they are left out of the preview's page list. At cutover web/ becomes the root
and no link needs rewriting.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

PREVIEW = "next"
WEB = "web"


def web_files(web: Path) -> list[Path]:
    """The template's files, relative to web/ (dotfiles left out)."""
    return sorted(p.relative_to(web) for p in web.rglob("*")
                  if p.is_file() and not any(part.startswith(".") for part in p.relative_to(web).parts))


def preview_config(config: dict, web: Path, legacy_site: bool) -> dict:
    """config.json for the preview: each page not in web/ yet links to the live page (`href`), or is
    left out on a league without the Stage A site."""
    pages = []
    for p in config["pages"]:
        if (web / p["path"]).is_file():
            pages.append(dict(p))
        elif legacy_site:
            pages.append(dict(p) | {"href": "../" + p["path"]})
    return dict(config) | {"pages": pages}


def write_preview(root: Path, out: Path, legacy_site: bool) -> list[str]:
    """Write <out>/next/ when the repo has web/ and the build wrote page models; returns the files
    written (relative to out)."""
    web = root / WEB
    if not web.is_dir() or not (out / "data" / "v1").is_dir():      # no template, or no page models to show
        return []
    dest = out / PREVIEW
    written = []

    def put(src: Path, rel: Path) -> None:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / rel)
        written.append(f"{PREVIEW}/{rel.as_posix()}")

    for rel in web_files(web):
        put(web / rel, rel)
    for src in sorted((out / "data" / "v1").rglob("*")):
        if src.is_file():
            put(src, src.relative_to(out))
    # the Stage A site's images (logos, champion photos); a league's own assets move to
    # leagues/<league>/assets in phase 5, so no other league gets this folder
    images = root / "images"
    for src in sorted(images.rglob("*")) if legacy_site and images.is_dir() else []:
        if src.is_file():
            put(src, src.relative_to(root))
    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    (dest / "config.json").write_text(json.dumps(preview_config(config, web, legacy_site), indent=1,
                                                 ensure_ascii=False) + "\n", encoding="utf-8")
    written.append(f"{PREVIEW}/config.json")
    return written

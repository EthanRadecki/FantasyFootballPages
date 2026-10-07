"""The Stage B preview: the new pages (web/) built at /next/ beside the live site (milestone M2,
docs/PUBLISH_PLAN.md section 8; Ethan 2026-10-06: preview first, then one switch).

`write_preview` copies web/ into <dist>/next/ with what the pages read: config.json, the page
models (data/v1/) and, for the league on the Stage A site, its images. A template page the league does
not have (its feature is off, or the build produced no data for it: no weekly rankings) is left out,
so the preview never serves a page that cannot load. Pages not moved to web/ yet stay reachable: on a
league with the Stage A site their nav links point at the live page (../pages/...), on any
other league they are left out of the preview's page list. At cutover web/ becomes the root
and no link needs rewriting.

Share previews: a link pasted into a group chat or social app shows a card (title, description,
image) only when the page's HTML carries Open Graph and Twitter tags with absolute URLs; crawlers
do not run the pages' scripts. `share_tags` writes them into each page's <head> when the site's
public URL is known: `league.site_url` in league.yaml, else the SITE_URL environment variable (the
deploy workflow sets it). A build without either writes no tags.
"""

from __future__ import annotations

import html
import json
import os
import re
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


# pages whose shared link says more than "<Page> | <League>"; {league}, {season} filled from config.json
SHARE_TEXT = {
    "home": ("{league}", "Standings, records, rivalries and analytics for {league}, every season since {first}."),
    "schedule-release": ("{league}: {season} Schedule Release",
                         "The {season} schedule is live. See who you're up against, and revisit the history behind "
                         "every matchup."),
}
DEFAULT_DESCRIPTION = "{page} for {league}: league history and analytics, every season since {first}."


def site_url(config: dict) -> str | None:
    url = (config.get("league") or {}).get("site_url") or os.environ.get("SITE_URL")
    return url.rstrip("/") if url else None


def share_tags(config: dict, page: dict, base: str) -> tuple[str, str]:
    """(title, the <meta> tags) for one page; base is the URL the page's path is relative to."""
    league = config["league"]
    season = config.get("live_season") or (config.get("current") or {}).get("season") or ""
    fill = {"league": league["name"], "season": season, "first": league.get("first_season", ""),
            "page": page.get("title", "")}
    title, desc = SHARE_TEXT.get(page["id"], ("{page} | {league}", DEFAULT_DESCRIPTION))
    title, desc = title.format(**fill), desc.format(**fill)
    logo = (league.get("logos_by_season") or {}).get(str(season)) or league.get("logo")
    tags = [("property", "og:title", title), ("property", "og:description", desc),
            ("property", "og:url", base + page["path"]), ("property", "og:type", "website"),
            ("property", "og:site_name", league["name"]),
            ("name", "twitter:card", "summary_large_image" if logo else "summary"),
            ("name", "twitter:title", title), ("name", "twitter:description", desc)]
    if logo:
        tags += [("property", "og:image", base + logo), ("name", "twitter:image", base + logo)]
    meta = "".join(f'<meta {k}="{v}" content="{html.escape(c, quote=True)}">\n' for k, v, c in tags)
    if logo:
        meta += f'<link rel="apple-touch-icon" href="{html.escape(base + logo, quote=True)}">\n'
    return title, meta


def with_share_tags(text: str, title: str, meta: str) -> str:
    """The page with its <title> set (crawlers that ignore og:title read it) and the tags before </head>."""
    text = re.sub(r"<title>.*?</title>", lambda m: f"<title>{html.escape(title)}</title>", text, count=1, flags=re.S)
    return text.replace("</head>", meta + "</head>", 1)


def write_preview(root: Path, out: Path, legacy_site: bool) -> list[str]:
    """Write <out>/next/ when the repo has web/ and the build wrote page models; returns the files
    written (relative to out)."""
    web = root / WEB
    if not web.is_dir() or not (out / "data" / "v1").is_dir():      # no template, or no page models to show
        return []
    dest = out / PREVIEW
    written = []
    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    from engine.publish.site import PAGES
    absent = {p["path"] for p in PAGES} - {p["path"] for p in config["pages"]}

    def put(src: Path, rel: Path) -> None:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / rel)
        written.append(f"{PREVIEW}/{rel.as_posix()}")

    for rel in web_files(web):
        if rel.as_posix() not in absent:
            put(web / rel, rel)
    url = site_url(config)
    if url:                                           # share previews (see the module docstring)
        for p in config["pages"]:
            path = dest / p["path"]
            if path.is_file() and (web / p["path"]).is_file():
                title, meta = share_tags(config, p, f"{url}/{PREVIEW}/")
                path.write_text(with_share_tags(path.read_text(encoding="utf-8"), title, meta), encoding="utf-8")
    for src in sorted((out / "data" / "v1").rglob("*")):
        if src.is_file():
            put(src, src.relative_to(out))
    # the Stage A site's images (logos, champion photos); a league's own assets move to
    # leagues/<league>/assets in phase 5, so no other league gets this folder
    images = root / "images"
    for src in sorted(images.rglob("*")) if legacy_site and images.is_dir() else []:
        if src.is_file():
            put(src, src.relative_to(root))
    (dest / "config.json").write_text(json.dumps(preview_config(config, web, legacy_site), indent=1,
                                                 ensure_ascii=False) + "\n", encoding="utf-8")
    written.append(f"{PREVIEW}/config.json")
    return written

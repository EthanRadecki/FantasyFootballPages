"""The site template: which files make up the site, and its page list.

Stage A (docs/PUBLISH_PLAN.md) builds `dist/` from the current site files at
the repo root, unchanged, and overwrites only the data files publish
regenerates. `LEGACY_SITE` lists those root files. It is template, not league
data, and goes away at cutover (phase 6), when `web/` replaces it.

`PAGES` is the page list every league's site has. `config.json` carries the
resolved list (pages whose feature the league turned off are left out), and
the nav is drawn from it.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

LEGACY_SITE_FILES = ["index.html", "shared.js", "style.css", "data-engine.js", "preach_logo.png"]
LEGACY_SITE_DIRS = ["pages", "data", "images"]

# id, title, path, parent (for sub-pages), feature flag in league.yaml (None: always on), shown in the nav,
# and `data`: the page model files the page needs. A page whose data the build did not produce for this
# league (a league that never starts a D/ST has no D/ST page) is left out of config.json's page list.
# Pages not yet ported to publish declare no data and are always listed.
PAGES = [
    {"id": "home", "title": "Home", "path": "index.html", "parent": None, "feature": None, "nav": False,
     "data": ["data/v1/index.json"]},
    {"id": "weekly-rankings", "title": "Weekly Rankings", "path": "pages/weekly-rankings.html", "parent": None,
     "feature": "weekly_rankings", "nav": True},
    {"id": "managers", "title": "Managers", "path": "pages/managers.html", "parent": None, "feature": None,
     "nav": True, "data": ["data/v1/index.json"]},
    {"id": "champions", "title": "Champions", "path": "pages/champions.html", "parent": None,
     "feature": "champions_gallery", "nav": True},
    {"id": "matchups", "title": "Matchups", "path": "pages/matchups.html", "parent": None, "feature": None,
     "nav": True, "data": ["data/v1/matchups.json"]},
    {"id": "draft-analysis", "title": "Draft Analysis", "path": "pages/draft-analysis.html", "parent": None,
     "feature": None, "nav": True, "data": ["data/v1/draft-analysis.json"]},
    {"id": "surplus-value", "title": "Surplus Value", "path": "pages/surplus-value.html",
     "parent": "draft-analysis", "feature": None, "nav": True, "data": ["data/v1/surplus-value.json"]},
    {"id": "draft-history", "title": "Draft History", "path": "pages/draft-history.html",
     "parent": "draft-analysis", "feature": None, "nav": True, "data": ["data/v1/draft-history.json"]},
    {"id": "draft-fingerprints", "title": "Draft Fingerprints", "path": "pages/draft-fingerprints.html",
     "parent": "draft-analysis", "feature": None, "nav": True, "data": ["data/v1/draft-fingerprints.json"]},
    {"id": "transaction-analysis", "title": "Transaction Analysis", "path": "pages/transaction-analysis.html",
     "parent": None, "feature": None, "nav": True},
    {"id": "lineup-efficiency", "title": "Lineup Efficiency", "path": "pages/lineup-efficiency.html",
     "parent": "transaction-analysis", "feature": None, "nav": True},
    {"id": "waiver-value", "title": "Waiver Value", "path": "pages/waiver-value.html",
     "parent": "transaction-analysis", "feature": None, "nav": True},
    {"id": "trade-value", "title": "Trade Value", "path": "pages/trade-value.html",
     "parent": "transaction-analysis", "feature": None, "nav": True, "data": ["data/v1/trade-value.json"]},
    {"id": "extra-analytics", "title": "Extra Analytics", "path": "pages/extra-analytics.html", "parent": None,
     "feature": None, "nav": True},
    {"id": "position-impact", "title": "Position Impact", "path": "pages/position-impact.html",
     "parent": "extra-analytics", "feature": None, "nav": True, "data": ["data/v1/position-impact.json"]},
    {"id": "dst-impact", "title": "Life Without Defense", "path": "pages/dst-impact.html",
     "parent": "extra-analytics", "feature": None, "nav": True, "data": ["data/v1/dst-impact.json"]},
    {"id": "schedule-release", "title": "Schedule Release", "path": "pages/schedule_release.html", "parent": None,
     "feature": None, "nav": False},
]


def pages_for(features: dict | None, produced: set[str] | None = None) -> list[dict]:
    """The page list with pages whose feature is switched off removed (a
    feature missing from league.yaml counts as on) and, once the build knows
    what it produced, pages whose data is missing."""
    features = features or {}
    out = []
    for p in PAGES:
        if p["feature"] is not None and not features.get(p["feature"], True):
            continue
        need = p.get("data") or []
        if produced is not None and need and not all(d in produced for d in need):
            continue
        out.append({k: v for k, v in p.items()} | {"data": list(need)})
    return out


def site_files(root: Path) -> list[Path]:
    """Every file of the current site, relative to `root`, sorted."""
    out = [Path(f) for f in LEGACY_SITE_FILES if (root / f).is_file()]
    for d in LEGACY_SITE_DIRS:
        base = root / d
        if base.is_dir():
            out += [p.relative_to(root) for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    return sorted(out)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_site(root: Path, out: Path) -> list[Path]:
    """Copy the current site into `out`, byte for byte. Returns the files copied."""
    files = site_files(root)
    for rel in files:
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dest)
    return files

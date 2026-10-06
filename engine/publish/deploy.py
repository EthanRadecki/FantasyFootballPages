"""Milestone M0: what GitHub Pages serves, and the checks a deploy must pass.

The deploy workflow (.github/workflows/deploy.yml) publishes one folder:

    /            the current site, exactly the files committed in the repo
                 (engine/publish/site.py's site files: index.html, pages/, data/,
                 images/, the shared JS and CSS, the logo), checked byte for byte
    /next/       the engine's build of the same site (`engine update`), for review
                 before milestone M1 makes engine data live

Only site files are published: the code, docs, tools and league folders stay in
the repo (decision at M0, 2026-10-06). Every published page is byte-identical
to what "deploy from branch" served.

Sanity checks on a fresh /next/ build, against the stats of the last deploy
(`deploy-stats.json`, published beside the build):
    games        a season's game count never goes down
    week         the live season's last completed week never goes backwards
    managers     every visible manager has a data file and a leaderboard row
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from engine.publish.site import LEGACY_SITE_DIRS, LEGACY_SITE_FILES

STATS = "deploy-stats.json"


def committed_site_files(repo: Path) -> list[str]:
    """The site files git tracks (untracked files in data/ or images/ are never published)."""
    out = subprocess.run(["git", "ls-files", "-z", "--", *LEGACY_SITE_FILES, *LEGACY_SITE_DIRS], cwd=repo,
                         capture_output=True, check=True).stdout.decode()
    return sorted(f for f in out.split("\0") if f and (repo / f).is_file())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assemble(repo: Path, out: Path, dist: Path | None) -> dict:
    """Write the folder Pages serves: the committed site at the root, the engine build at /next/
    (when `dist` is given). Returns {"root": n files, "next": n files or 0}."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    files = committed_site_files(repo)
    for f in files:
        (out / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / f, out / f)
    n_next = 0
    if dist is not None:
        shutil.copytree(dist, out / "next")
        n_next = sum(1 for p in (out / "next").rglob("*") if p.is_file())
    return {"root": len(files), "next": n_next}


def check_root(repo: Path, out: Path) -> list[str]:
    """Problems with the published root: a committed site file missing or changed, or an extra file."""
    files = committed_site_files(repo)
    problems = [f"missing or changed: {f}" for f in files if not (out / f).is_file() or _sha(out / f) != _sha(repo / f)]
    published = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()
                 and not p.relative_to(out).as_posix().startswith("next/")}
    problems += [f"not a committed site file: {f}" for f in sorted(published - set(files))]
    return problems


def stats(dist: Path) -> dict:
    """Counts the sanity checks compare from one deploy to the next."""
    games: dict[str, int] = {}
    with open(dist / "data" / "v1" / "matchups.json", encoding="utf-8") as f:
        for g in json.load(f)["games"]:
            games[str(g["season"])] = games.get(str(g["season"]), 0) + 1
    with open(dist / "config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    visible = sorted(m["key"] for m in cfg["managers"] if not m.get("hidden"))
    return {"games": games, "current": cfg.get("current"), "live_season": cfg.get("live_season"),
            "visible_managers": visible}


def sanity(dist: Path, previous: dict | None) -> list[str]:
    """Problems with a fresh build, alone and against the last deploy's stats (None: first deploy)."""
    now = stats(dist)
    problems = []
    with open(dist / "data" / "v1" / "index.json", encoding="utf-8") as f:
        board = {r["manager_key"] for r in json.load(f)["leaderboard"]}
    for k in now["visible_managers"]:
        if not (dist / "data" / "v1" / "managers" / f"{k}.json").is_file():
            problems.append(f"manager {k}: no data/v1/managers file")
        if k not in board:
            problems.append(f"manager {k}: not on the leaderboard")
    if previous:
        for season, n in (previous.get("games") or {}).items():
            if now["games"].get(season, 0) < n:
                problems.append(f"season {season}: {now['games'].get(season, 0)} games, the last deploy had {n}")
        old, new = previous.get("current") or {}, now["current"] or {}
        if old.get("season") == new.get("season") and (new.get("last_completed_week") or 0) < (
                old.get("last_completed_week") or 0):
            problems.append(f"live week went backwards: {new.get('last_completed_week')} after "
                            f"{old.get('last_completed_week')}")
    return problems

"""What GitHub Pages serves, and the checks a deploy must pass (milestones M0 and M1).

The deploy workflow (.github/workflows/deploy.yml) publishes one folder. From M1 on
(2026-10-06) it is the engine's build (`engine update --verify`, dist/): the site files
committed in the repo (engine/publish/site.py: index.html, pages/, images/, the shared JS
and CSS, the logo) copied byte for byte, with every data file generated from ESPN data,
plus `deploy-stats.json`, `verify.json` and the change report (`changes.html`). A deploy
happens only when the build, its checks and the page test pass; otherwise the last good
site stays up and the run fails.

Before M1 (M0) the root was the committed site files and the build was a preview at
/next/; `assemble` still takes a `next` build for the Stage B preview (milestone M2).

Sanity checks on a fresh build, against the stats of the last deploy
(`deploy-stats.json`, published with the site):
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


def assemble(repo: Path, out: Path, dist: Path, next_dist: Path | None = None) -> dict:
    """Write the folder Pages serves: the engine build at the root, and a second build at /next/ when
    `next_dist` is given (the Stage B preview). Returns {"root": n files, "next": n files or 0}."""
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(dist, out)
    n_next = 0
    if next_dist is not None:
        shutil.copytree(next_dist, out / "next")
        n_next = sum(1 for p in (out / "next").rglob("*") if p.is_file())
    n_root = sum(1 for p in out.rglob("*") if p.is_file() and not p.relative_to(out).as_posix().startswith("next/"))
    return {"root": n_root, "next": n_next}


def check_root(repo: Path, out: Path, dist: Path) -> list[str]:
    """Problems with the published root: a file that differs from the build or is not in it, and a
    committed site file missing (the build copies every one; the generated data files replace theirs)."""
    built = {p.relative_to(dist).as_posix() for p in dist.rglob("*") if p.is_file()}
    extra = set() if (dist / "next").is_dir() else {"next/"}      # a separate preview build at /next/ (assemble)
    published = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()
                 and not any(p.relative_to(out).as_posix().startswith(x) for x in extra)}
    problems = [f"missing or changed: {f}" for f in sorted(built) if f not in published or _sha(out / f) != _sha(dist / f)]
    problems += [f"not in the build: {f}" for f in sorted(published - built)]
    problems += [f"committed site file not published: {f}" for f in committed_site_files(repo) if f not in published]
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

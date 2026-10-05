"""League editorial files: hand-written content a league may add.

They live in `leagues/<league>/editorial/<name>.yaml` beside league.yaml
(phase 5 moves the rest of the site's editorial content there). Every page
works without them: a missing file means the generated fallback.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def editorial_path(ctx, name: str) -> Path | None:
    base = getattr(ctx, "league_dir", None)
    return None if base is None else Path(base) / "editorial" / f"{name}.yaml"


def load_editorial(ctx, name: str):
    """The parsed file, or None when the league has none."""
    path = editorial_path(ctx, name)
    if path is None or not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def team_names(ctx, short: bool = False) -> dict:
    """(season, manager key) -> team name as the site shows it: ESPN's name unless the league's
    editorial `team_names.yaml` replaces it (`shown`, every page) or, with `short`, gives the
    name for pages that shorten team names (`short`, falling back to `shown`)."""
    f = load_editorial(ctx, "team_names") or {}
    by_season = lambda sec: {int(s): m or {} for s, m in (f.get(sec) or {}).items()}
    shown, small = by_season("shown"), by_season("short")
    t = ctx.tables["teams"]
    out = {}
    for s, k, n in zip(t["season"], t["manager_key"], t["team_name"]):
        name = shown.get(int(s), {}).get(n, n)
        out[(int(s), k)] = small.get(int(s), {}).get(n, name) if short else name
    return out

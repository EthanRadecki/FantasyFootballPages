"""`engine pull`: download raw league data into the local cache.

    engine pull leagues/preach/league.yaml                # all seasons, reuse completed ones
    engine pull leagues/preach/league.yaml --seasons 2025-2026 --refresh
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from engine.providers.espn import EspnClient, EspnProvider


def load_credentials(auth_path: str | None = None) -> tuple[str, str]:
    """ESPN cookies from an auth file, else the ESPN_S2 / SWID environment variables."""
    if auth_path:
        with open(auth_path, encoding="utf-8") as f:
            raw = {k.lower(): v for k, v in json.load(f).items()}
        return raw["espn_s2"], raw["swid"]
    s2, swid = os.environ.get("ESPN_S2"), os.environ.get("SWID")
    if not (s2 and swid):
        raise SystemExit("No ESPN credentials: set ESPN_S2 and SWID (Codespaces secrets) or pass --auth.")
    return s2, swid


def latest_season(today: date | None = None) -> int:
    """NFL seasons start in September; before August the latest season is last year's."""
    today = today or date.today()
    return today.year if today.month >= 8 else today.year - 1


def parse_seasons(spec: str | None, first_season: int, today: date | None = None) -> list[int]:
    last = latest_season(today)
    if not spec:
        return list(range(first_season, last + 1))
    seasons: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = (int(x) for x in part.split("-", 1))
            seasons.update(range(lo, hi + 1))
        else:
            seasons.add(int(part))
    bad = [s for s in seasons if s < first_season or s > last]
    if bad:
        raise SystemExit(f"Seasons out of range {first_season}-{last}: {sorted(bad)}")
    return sorted(seasons)


def cache_dir(cache_root: Path, provider: str, league_id: int, season: int) -> Path:
    return cache_root / provider / str(league_id) / str(season)


def run_pull(provider, league_id: int, seasons: list[int], cache_root: Path, refresh: bool = False):
    """Yield (season, status, summary) as each season finishes."""
    for season in seasons:
        out = cache_dir(cache_root, provider.name, league_id, season)
        if not refresh and provider.is_cached(out):
            summary = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["summary"]
            yield season, "cached", summary
            continue
        yield season, "pulled", provider.pull_season(season, out)


def make_provider(cfg: dict, auth_path: str | None) -> EspnProvider:
    league = cfg["league"]
    if league["provider"] != "espn":
        raise SystemExit(f"Provider '{league['provider']}' is not supported yet.")
    s2, swid = load_credentials(auth_path)
    return EspnProvider(EspnClient(league["league_id"], s2, swid))

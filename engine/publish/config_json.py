"""config.json: the one place pages get league facts from.

Built from league.yaml plus the canonical tables: seasons, team counts and
week structure come from the data (never config), so an imported league of
any size and history gets a correct file. Managers ESPN knows but league.yaml
does not list still appear, with generated colors and ESPN's team logo.
"""

from __future__ import annotations

import hashlib
import re

import pandas as pd

from engine.analytics import weeks
from engine.config import conference_labels, excluded_games, excluded_manager_keys, slugify
from engine.publish.site import pages_for

SCHEMA = "config"
SCHEMA_VERSION = 1

# Muted fallback colors for managers without configured ones (same family as
# the site's palette). Picked by a stable hash of the manager key.
FALLBACK_COLORS = ["#6d6a5f", "#5c6b73", "#7a5c58", "#5f6e4c", "#6b5a75", "#73624a", "#4f6a6a", "#6a5060"]
NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}
STANDARD_ROUNDS = ["Championship", "Semifinals", "Quarterfinals"]   # counted back from the final


def short_name(name: str) -> str:
    """Last name without a suffix: 'Carmine Pittelli Jr.' -> 'Pittelli'."""
    parts = [p for p in name.split() if p.lower() not in NAME_SUFFIXES]
    return parts[-1] if parts else name


def fallback_color(key: str) -> str:
    return FALLBACK_COLORS[int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(FALLBACK_COLORS)]


def round_names(cfg: dict, season: int, regular_weeks: int, final_week: int) -> dict[str, str]:
    """Playoff week -> round name. league.yaml `rules.playoff_rounds` for the
    season (a week map) or its default (a list for the weeks right after the
    regular season); otherwise generic names counted back from the final."""
    rules = (cfg.get("rules") or {}).get("playoff_rounds") or {}
    spec = rules.get(season, rules.get(str(season), rules.get("default")))
    playoff_weeks = list(range(regular_weeks + 1, final_week + 1))
    if isinstance(spec, dict):
        return {str(int(w)): str(n) for w, n in spec.items()}
    if isinstance(spec, list) and len(spec) >= len(playoff_weeks):
        return {str(w): str(spec[i]) for i, w in enumerate(playoff_weeks)}
    out = {}
    for i, w in enumerate(reversed(playoff_weeks)):
        out[str(w)] = STANDARD_ROUNDS[i] if i < len(STANDARD_ROUNDS) else f"Round {len(playoff_weeks) - i}"
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def _seasons(cfg: dict, tables: dict) -> list[dict]:
    s = tables["seasons"].sort_values("season")
    done = weeks.completed_weeks(tables).groupby("season")["week"].max()
    live = weeks.live_seasons(tables)
    out = []
    for r in s.itertuples():
        season = int(r.season)
        reg, final = int(r.regular_season_periods), int(r.final_scoring_period)
        last = int(done.get(season, 0))
        out.append({
            "season": season, "team_count": int(r.team_count), "regular_season_weeks": reg,
            "final_week": final, "playoff_team_count": int(r.playoff_team_count) if pd.notna(r.playoff_team_count) else None,
            "last_completed_week": last or None, "live": season in live,
            "rounds": round_names(cfg, season, reg, final),
            "faab": bool(getattr(r, "faab_enabled", False)) if pd.notna(getattr(r, "faab_enabled", None)) else False,
        })
    return out


def _logo(cfg: dict, season: int | None) -> str | None:
    logo = (cfg.get("league") or {}).get("logo")
    if isinstance(logo, dict):
        pattern = logo.get("by_season")
        return pattern.format(season=season) if pattern and season is not None else logo.get("default")
    return logo


def _managers(cfg: dict, tables: dict) -> list[dict]:
    hidden = excluded_manager_keys(cfg)
    teams = tables["teams"]
    played = teams.groupby("manager_key")["season"].apply(lambda s: sorted({int(x) for x in s}))
    latest = teams.sort_values("season").groupby("manager_key").tail(1).set_index("manager_key")
    out, seen = [], set()
    for m in cfg.get("managers") or []:
        key = m["id"]
        seen.add(key)
        colors = m.get("colors") or {}
        fb = fallback_color(key)
        out.append({
            "key": key, "slug": slugify(m["name"]), "name": m["name"],
            "short": m.get("short") or short_name(m["name"]), "aliases": list(m.get("aliases") or []),
            "colors": {"dark": colors.get("dark", fb), "light": colors.get("light", colors.get("dark", fb))},
            "logo": m.get("logo") or (latest["logo_url"].get(key) if key in latest.index else None),
            "championship_logos": {str(k): v for k, v in (m.get("championship_logos") or {}).items()},
            "hidden": key in hidden, "seasons": played.get(key, []),
        })
    names = tables["managers"].set_index("manager_key")["espn_name"] if "managers" in tables else pd.Series(dtype=object)
    for key in sorted(set(played.index) - seen):
        name = str(names.get(key) or key)
        fb = fallback_color(key)
        out.append({
            "key": key, "slug": slugify(name), "name": name, "short": short_name(name), "aliases": [],
            "colors": {"dark": fb, "light": fb}, "logo": latest["logo_url"].get(key), "championship_logos": {},
            "hidden": False, "seasons": played.get(key, []),
        })
    return out


def build_config(cfg: dict, tables: dict, build: dict) -> dict:
    league = cfg["league"]
    seasons = _seasons(cfg, tables)
    finished = [s["season"] for s in seasons if not s["live"]]
    live = [s["season"] for s in seasons if s["live"]]
    current = seasons[-1] if seasons else None
    theme = cfg.get("theme") or {}
    return {
        "build": dict(build),
        "league": {
            "name": league["name"], "provider": league["provider"], "league_id": league["league_id"],
            "first_season": league["first_season"],
            "logo": _logo(cfg, current["season"] if current else None),
            "logos_by_season": {str(s["season"]): _logo(cfg, s["season"]) for s in seasons},
            "conference_labels": {str(k): v for k, v in conference_labels(cfg).items()},
            **({"credit": dict(league["credit"])} if league.get("credit") else {}),
        },
        "seasons": seasons,
        "finished_seasons": finished,
        "live_season": live[-1] if live else None,
        "current": {"season": current["season"], "last_completed_week": current["last_completed_week"]}
        if current else None,
        "managers": _managers(cfg, tables),
        "exclude_games": [{"season": s, "week": w, "manager_key": k, "from": ["ppg"]}
                          for s, w, k in sorted(excluded_games(cfg, "ppg"))],
        "theme": {
            "fonts": dict(theme.get("fonts") or {}),
            "season_colors": {str(k): v for k, v in (theme.get("season_colors") or {}).items()},
            "season_accents": {str(k): v for k, v in (theme.get("season_accents") or {}).items()},
            "champion_tints": {str(k): v for k, v in (theme.get("champion_tints") or {}).items()},
        },
        "features": {str(k): bool(v) for k, v in (cfg.get("features") or {}).items()},
        "pages": pages_for(cfg.get("features")),
    }


def asset_paths(config: dict) -> list[str]:
    """Local asset paths config.json points to (URLs skipped), for the dist check."""
    paths = [config["league"].get("logo")] + list(config["league"].get("logos_by_season", {}).values())
    for m in config["managers"]:
        paths.append(m.get("logo"))
        paths += list(m.get("championship_logos", {}).values())
    return sorted({p for p in paths if p and not re.match(r"^[a-z]+://", p)})

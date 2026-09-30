"""Load and validate a league config (leagues/<name>/league.yaml).

Validation here is structural: required fields, types, formats, and internal
references. Whether the values match ESPN is checked in phase 2 by the
provider.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_PROVIDERS = {"espn"}
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
COLOR_ROLES = {"dark", "light"}
RECORD_GAME_TYPES = {"regular_season", "winners_bracket", "consolation"}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def excluded_manager_keys(cfg: dict[str, Any]) -> set[str]:
    """Member keys of analysis.exclude_managers (listed by name slug)."""
    slugs = set((cfg.get("analysis") or {}).get("exclude_managers") or [])
    return {m["id"] for m in cfg.get("managers") or [] if slugify(m["name"]) in slugs}


def conference_labels(cfg: dict[str, Any]) -> dict[int, str]:
    """league.conference_labels: ESPN division id -> the league's conference
    label, the same in every season whatever ESPN named the division."""
    return {int(k): str(v) for k, v in ((cfg.get("league") or {}).get("conference_labels") or {}).items()}


def excluded_games(cfg: dict[str, Any], scope: str) -> set[tuple[int, int, str]]:
    """(season, week, member key) of analysis.exclude_games entries whose
    `from` list names `scope` (for example "ppg")."""
    keys = {slugify(m["name"]): m["id"] for m in cfg.get("managers") or []}
    return {(int(g["season"]), int(g["week"]), keys[g["manager"]])
            for g in (cfg.get("analysis") or {}).get("exclude_games") or []
            if scope in (g.get("from") or []) and g.get("manager") in keys}


@dataclass
class ConfigReport:
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def load_config(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def validate_config(cfg: dict[str, Any]) -> ConfigReport:
    errors: list[str] = []
    warnings: list[str] = []

    league = cfg.get("league") or {}
    for key in ("name", "provider", "league_id", "first_season"):
        if key not in league:
            errors.append(f"league.{key} is required")
    if league.get("provider") not in SUPPORTED_PROVIDERS:
        errors.append(f"league.provider must be one of {sorted(SUPPORTED_PROVIDERS)}")
    if "league_id" in league and not isinstance(league["league_id"], int):
        errors.append("league.league_id must be an integer")
    if "first_season" in league and not isinstance(league["first_season"], int):
        errors.append("league.first_season must be an integer")

    labels = league.get("conference_labels")
    if labels is not None and not (isinstance(labels, dict)
                                   and all(isinstance(k, int) and not isinstance(k, bool) for k in labels)
                                   and all(isinstance(v, str) and v for v in labels.values())):
        errors.append("league.conference_labels must map ESPN division ids (whole numbers) to labels")

    managers = cfg.get("managers") or []
    if not managers:
        errors.append("managers: at least one manager is required")
    slugs: set[str] = set()
    ids: set[str] = set()
    for i, m in enumerate(managers):
        where = f"managers[{i}]"
        name = m.get("name")
        if not name:
            errors.append(f"{where}.name is required")
            continue
        slug = slugify(name)
        if slug in slugs:
            errors.append(f"{where}: duplicate manager '{name}'")
        slugs.add(slug)

        mid = m.get("id")
        if not mid or str(mid).startswith("TODO"):
            warnings.append(f"{where} ({name}): id not set yet (run tools/espn_members.py)")
        elif mid in ids:
            errors.append(f"{where} ({name}): duplicate id {mid}")
        else:
            ids.add(mid)

        colors = m.get("colors")
        if colors is None:
            warnings.append(f"{where} ({name}): no colors set; generated colors will be used")
        elif not isinstance(colors, dict) or set(colors) - COLOR_ROLES:
            errors.append(f"{where} ({name}): colors must map {sorted(COLOR_ROLES)} to #RRGGBB")
        else:
            for role, value in colors.items():
                if not HEX_COLOR.match(str(value)):
                    errors.append(f"{where} ({name}): colors.{role} '{value}' is not #RRGGBB")

        short = m.get("short")
        if short is not None and not (isinstance(short, str) and short.strip()):
            errors.append(f"{where} ({name}): short must be a non-empty name")

    features = cfg.get("features") or {}
    if not isinstance(features, dict) or not all(isinstance(v, bool) for v in features.values()):
        errors.append("features must map feature names to true or false")

    analysis = cfg.get("analysis") or {}
    bad_scope = set(analysis.get("record_games") or []) - RECORD_GAME_TYPES
    if bad_scope:
        errors.append(f"analysis.record_games: unknown {sorted(bad_scope)}; use {sorted(RECORD_GAME_TYPES)}")
    for slug in analysis.get("exclude_managers") or []:
        if slug not in slugs:
            errors.append(f"analysis.exclude_managers: '{slug}' is not a manager slug")
    for i, g in enumerate(analysis.get("exclude_games") or []):
        if g.get("manager") not in slugs:
            errors.append(f"analysis.exclude_games[{i}]: unknown manager '{g.get('manager')}'")
    cutoff = (analysis.get("playoff_odds") or {}).get("cutoff")
    if cutoff is not None and (not isinstance(cutoff, int) or isinstance(cutoff, bool) or cutoff < 1):
        errors.append(f"analysis.playoff_odds.cutoff: '{cutoff}' must be a positive whole number")
    adp = analysis.get("adp") or {}
    if adp:
        from engine.normalize.adp import LIBRARY_ROOT
        library = adp.get("library")
        if library is not None and not (LIBRARY_ROOT / str(library)).is_dir():
            available = sorted(p.name for p in LIBRARY_ROOT.iterdir() if p.is_dir()) if LIBRARY_ROOT.is_dir() else []
            errors.append(f"analysis.adp.library: '{library}' is not an ADP library; available: {available}")
        days = adp.get("snapshot_max_days")
        if days is not None and (isinstance(days, bool) or not isinstance(days, (int, float)) or days < 0):
            errors.append(f"analysis.adp.snapshot_max_days: '{days}' must be a number of days, 0 or more")

    corrections = cfg.get("corrections") or {}
    for season, order in (corrections.get("draft_order") or {}).items():
        unknown = [x for x in order if x not in slugs]
        if unknown:
            errors.append(f"corrections.draft_order.{season}: unknown managers {unknown}")
        if len(set(order)) != len(order):
            errors.append(f"corrections.draft_order.{season}: a manager appears twice")
    for season, owners in (corrections.get("draft_pick_owners") or {}).items():
        unknown = [x for x in (owners or {}).values() if x not in slugs]
        if unknown:
            errors.append(f"corrections.draft_pick_owners.{season}: unknown managers {unknown}")

    theme = cfg.get("theme") or {}
    for season, color in (theme.get("season_colors") or {}).items():
        if not HEX_COLOR.match(str(color)):
            errors.append(f"theme.season_colors.{season}: '{color}' is not #RRGGBB")

    return ConfigReport(errors=errors, warnings=warnings)

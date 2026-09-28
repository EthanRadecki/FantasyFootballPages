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

    theme = cfg.get("theme") or {}
    for season, color in (theme.get("season_colors") or {}).items():
        if not HEX_COLOR.match(str(color)):
            errors.append(f"theme.season_colors.{season}: '{color}' is not #RRGGBB")

    return ConfigReport(errors=errors, warnings=warnings)

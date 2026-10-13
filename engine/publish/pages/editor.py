"""The rankings editor's data (web/admin/, not in the nav).

Outputs
    data/v1/editor/vocab.json   page model (schema "editor-vocab"): the names the blurb
                                formatter marks (engine/publish/blurbs.py and its JavaScript
                                twin): managers with their colors, team names, player names

Only for a league that writes weekly rankings (it has an editorial/rankings folder).

    managers  every manager of the league: full name, aliases (league.yaml), nicknames
              (editorial blurbs.yaml `nicknames: {RPM: Ryan McQuaid}`), and the first and
              last name when no other manager shares it; color = the manager's dark color
    teams     every season's team names as the site shows them (team_names.yaml `shown`)
    players   every player in the league's data (players) plus the live season's free
              agents in the projections, multi-word names only
"""

from __future__ import annotations

from collections import Counter

from engine.publish import rankings as R
from engine.publish.build import Output
from engine.publish.config_json import _managers
from engine.publish.editorial import load_editorial, team_names

SCHEMA, VERSION = "editor-vocab", 1
PATH = "data/v1/editor/vocab.json"


def manager_names(managers: list[dict], nicknames: dict[str, str] | None = None) -> list[dict]:
    """[{key, color, names}]: full name, aliases, nicknames, and first / last names only one manager has."""
    first = Counter(m["name"].split()[0] for m in managers if m["name"].split())
    last = Counter(m["name"].split()[-1] for m in managers if len(m["name"].split()) > 1)
    by_name = {m["name"].strip().lower(): m["key"] for m in managers}
    nick = {}
    for n, who in (nicknames or {}).items():
        k = by_name.get(str(who).strip().lower())
        if k is None:
            raise ValueError(f"editorial blurbs.yaml: nickname {n!r} names no manager ({who!r})")
        nick.setdefault(k, []).append(str(n))
    out = []
    for m in managers:
        parts = m["name"].split()
        names = [m["name"], *m.get("aliases", []), *nick.get(m["key"], [])]
        if parts and first[parts[0]] == 1:
            names.append(parts[0])
        if len(parts) > 1 and last[parts[-1]] == 1:
            names.append(parts[-1])
        out.append({"key": m["key"], "color": (m.get("colors") or {}).get("dark"),
                    "names": list(dict.fromkeys(n for n in names if n))})
    return out


def vocabulary(ctx) -> dict:
    t = ctx.tables
    live = R.next_week(t)[0]
    season = live[0] if live else int(t["seasons"]["season"].max())
    managers = manager_names(_managers(ctx.cfg, t), (load_editorial(ctx, "blurbs") or {}).get("nicknames"))
    teams = sorted({str(n) for n in team_names(ctx).values() if str(n).strip()})
    players = set(t["players"]["player_name"].dropna().astype(str)) if "players" in t else set()
    proj = t.get("projections")
    if proj is not None and len(proj):
        players |= set(proj.loc[proj["season"] == season, "player_name"].dropna().astype(str))
    return {"season": season, "managers": managers, "teams": teams,
            "players": sorted(p for p in players if " " in p.strip())}


class EditorPublisher:
    name = "editor"
    pages: dict = {}

    def outputs(self, ctx) -> list[Output]:
        base = R.league_dir(ctx)
        if base is None or not (base / R.EDITORIAL_DIR).is_dir() or "teams" not in ctx.tables:
            return []
        return [Output(PATH, vocabulary(ctx), SCHEMA, VERSION)]

    def verify(self, ctx) -> list:
        return []

"""The rankings editor's data (pages/rankings-editor.html, not in the nav).

Outputs
    data/v1/editor/vocab.json   page model (schema "editor-vocab"): the names the blurb
                                formatter marks (engine/publish/blurbs.py and its JavaScript
                                twin): managers with their colors, team names, player names

    data/v1/editor/week.json    page model (schema "editor-week"): the week to write next
                                (rankings.next_week) and, per visible manager, the numbers
                                to write from, plus where the editorial files live in the repo

Only for a league that writes weekly rankings (it has an editorial/rankings folder).

    managers  every manager of the league: full name, aliases (league.yaml), nicknames
              (editorial blurbs.yaml `nicknames: {RPM: Ryan McQuaid}`), and the first and
              last name when no other manager shares it; color = the manager's dark color
    teams     every season's team names as the site shows them (team_names.yaml `shown`)
    players   every player in the league's data (players) plus the live season's free
              agents in the projections, multi-word names only

week.json, for week W of the live season (results through week W-1, regular season):
    record, ppg, last_score, streak   rankings.record_fields (the page's derived fields)
    prev_rank   the manager's rank in the season's latest published week before W
    last_game   week W-1: opponent, both scores, result, optimal lineup points and points left
                on the bench (lineup_efficiency), the manager's top two starters
    next_game   week W: opponent, both projected totals (projected_team_weeks), all-time
                head-to-head (head_to_head)
    repo        GitHub repository (league.yaml `league.repo`, else GITHUB_REPOSITORY in Actions
                and Codespaces, else null: the editor reads it from the github.io address),
                branch, and the editorial and snapshot folders
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pandas as pd

from engine.config import excluded_manager_keys
from engine.legacy import name_to_key
from engine.publish import rankings as R
from engine.publish.build import Output
from engine.publish.config_json import _managers
from engine.publish.editorial import load_editorial, team_names

SCHEMA, VERSION = "editor-vocab", 1
PATH = "data/v1/editor/vocab.json"
WEEK_SCHEMA, WEEK_PATH = "editor-week", "data/v1/editor/week.json"


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


def _r2(x):
    return None if x is None or pd.isna(x) else round(float(x), 2)


def repo_info(ctx) -> dict:
    league = ctx.cfg.get("league") or {}
    base = Path(R.league_dir(ctx))
    if base.is_absolute():
        try:
            base = base.relative_to(Path.cwd())
        except ValueError:
            pass
    return {"name": league.get("repo") or os.environ.get("GITHUB_REPOSITORY") or None,
            "branch": league.get("repo_branch") or "main",
            "editorial_dir": (base / R.EDITORIAL_DIR).as_posix(), "snapshot_dir": (base / R.SNAPSHOT_DIR).as_posix()}


def week_numbers(ctx) -> dict:
    """The editor's week model (see the module docstring)."""
    t, a = ctx.tables, ctx.analysis
    nxt, why = R.next_week(t)
    out = {"season": nxt[0] if nxt else None, "week": nxt[1] if nxt else None,
           "file": R.week_stem(*nxt) + ".json" if nxt else None, "why_none": why or None,
           "repo": repo_info(ctx), "managers": []}
    if not nxt or a.get("games") is None:
        return out
    season, week = nxt
    hidden = excluded_manager_keys(ctx.cfg)
    lookup = name_to_key(ctx.cfg)
    res = R.results_from_games(a["games"], ctx.cfg)
    reg = res[(res["season"] == season) & ~res["is_playoff"]].sort_values("week", kind="stable")
    published = R.week_files(R.published(R.load_folder(R.league_dir(ctx), R.EDITORIAL_DIR)))
    prev = [ed for (s, w), (_, ed) in published.items() if s == season and w < week]
    prev_rank = {lookup.get(str(x["manager"]).strip().lower()): x.get("rank")
                 for x in (prev[-1]["teams"] if prev else [])}
    eff = a.get("lineup_efficiency")
    eff = eff[(eff["season"] == season) & (eff["week"] == week - 1)].set_index("manager_key") \
        if eff is not None else pd.DataFrame()
    box = a.get("box_scores")
    box = box[(box["season"] == season) & (box["week"] == week - 1) & box["started"].astype(bool)] \
        if box is not None else pd.DataFrame()
    proj = a.get("projected_team_weeks")
    proj = proj[(proj["season"] == season) & (proj["week"] == week)].set_index("manager_key")["proj_points"] \
        if proj is not None else pd.Series(dtype=float)
    fut = t.get("future_matchups")
    opp = dict(zip(fut.loc[(fut["season"] == season) & (fut["week"] == week), "manager_key"],
                   fut.loc[(fut["season"] == season) & (fut["week"] == week), "opponent_manager_key"])) \
        if fut is not None else {}
    h2h = a.get("head_to_head")
    h2h = {(r["manager_key"], r["opponent_key"]): r for r in h2h.to_dict("records")} if h2h is not None else {}
    keys = [k for k in t["teams"].loc[t["teams"]["season"] == season, "manager_key"] if k not in hidden]
    names = {m["key"]: m["name"] for m in _managers(ctx.cfg, t)}
    for k in keys:
        mine = reg[reg["manager_key"] == k]
        row = {"key": k, "name": names.get(k, k), "prev_rank": prev_rank.get(k), **{
            f: v for f, v in R.record_fields(mine[mine["week"] < week]).items()}}
        row["record"] = row.pop("record_to_date")
        row["ppg"] = row.pop("ppg_to_date")
        if k in eff.index:
            e = eff.loc[k]
            starters = box[box["manager_key"] == k].sort_values("points", ascending=False).head(2) \
                if len(box) else pd.DataFrame()
            row["last_game"] = {"week": week - 1, "opponent_key": e["opponent_manager_key"],
                                "points": _r2(e["points"]), "opponent_points": _r2(e["opponent_points"]),
                                "result": e["result"], "optimal_points": _r2(e["optimal_points"]),
                                "left_on_bench": _r2(e["efficiency_gap"]),
                                "top_starters": [{"player": s["player_name"], "pos": s["position"],
                                                  "points": _r2(s["points"])} for s in starters.to_dict("records")]}
        o = opp.get(k)
        if o is not None:
            h = h2h.get((k, o)) or {}
            row["next_game"] = {"opponent_key": o, "proj": _r2(proj.get(k)), "opponent_proj": _r2(proj.get(o)),
                                "h2h": {"w": int(h.get("wins", 0)), "l": int(h.get("losses", 0)),
                                        "t": int(h.get("ties", 0))}}
        out["managers"].append(row)
    return out


class EditorPublisher:
    name = "editor"
    pages: dict = {}

    def outputs(self, ctx) -> list[Output]:
        base = R.league_dir(ctx)
        if base is None or not (base / R.EDITORIAL_DIR).is_dir() or "teams" not in ctx.tables:
            return []
        return [Output(PATH, vocabulary(ctx), SCHEMA, VERSION),
                Output(WEEK_PATH, week_numbers(ctx), WEEK_SCHEMA, VERSION)]

    def verify(self, ctx) -> list:
        return []

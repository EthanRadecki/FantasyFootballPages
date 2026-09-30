"""Waiver and free-agent pickups (waiver stints), their value, and roster stints.

A waiver stint starts with an executed waiver claim or free-agent add and
runs until the manager lets the player go (drop or trade) in a later week,
or later the same week; otherwise to the end of that team's season. Its value
is the player's position-relative z-score (weekly points against the weekly
position baseline, analytics.weeks) summed over the weeks rostered, the same
scale as trade grading.

Not a pickup:
- a same-week drop and re-add of a player who came from the draft or a trade
  (a roster shuffle, not a find)
- claiming a player your own trade dropped that same week
A drop recorded inside another manager's trade (a roster move forced when the
trade is accepted, undone within minutes) does not end a stint.

Weeks counted: the team's bracket weeks (finished regular-season weeks and
winners-bracket playoff weeks, as in trades). Excluded managers are counted
and flagged `hidden`.

legacy_mode=True reproduces waiver_stints_full.csv (its builder was lost; the
rules were recovered from the file): IR weeks count, the position baseline
includes IR, a same-week drop right after a re-add is missed (the stint runs to the
end of the season, double-counting the next pickup's weeks), an add, drop,
re-add in one week is labeled WAIVER if either add was a claim, and each
player carries one position label (his first season's).
The engine default applies ENGINE_CHANGES; `fixes` picks a subset.

Roster stints: every contiguous run of counted game weeks (regular season and
winners bracket, no byes, no consolation) a player spent on a manager's
roster, with the weeks he was started.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.analytics import weeks as weeks_mod

PICKUP_TYPES = ("WAIVER", "FREEAGENT")
IR_SLOT = "IR"

ENGINE_CHANGES = {
    "no_ir_weeks": "IR weeks are not counted (no weeks, points, or z while a player sits on IR), and the "
                   "position baseline excludes IR, as in trades",
    "no_double_count": "a same-week drop right after a re-add ends that stint (legacy missed it and "
                       "double-counted the next pickup's weeks)",
    "readd_type": "an add, drop, and re-add in one week takes the re-add's type (legacy: WAIVER if either was a claim)",
}

STINT_COLUMNS = ["season", "manager_key", "team_id", "player_id", "player_name", "position", "start_week",
                 "end_week", "type", "weeks_rostered", "total_points", "ppw", "avg_z", "total_z", "hidden"]


def _fixes(legacy_mode: bool, fixes) -> frozenset:
    if fixes is not None:
        return frozenset(fixes)
    return frozenset() if legacy_mode else frozenset(ENGINE_CHANGES)


def _events(tables: dict[str, pd.DataFrame], fx: frozenset) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(adds, exits, acquisitions) from executed transaction items."""
    tx = tables["transactions"]
    tx = tx[tx["status"] == "EXECUTED"]
    owner = tables["teams"].set_index(["season", "team_id"])["manager_key"]
    from_owner = owner.reindex(pd.MultiIndex.from_arrays([tx["season"], tx["from_team_id"]])).to_numpy()
    own_txn = tx["manager_key"].to_numpy() == from_owner
    adds = tx[(tx["item_type"] == "ADD") & tx["type"].isin(PICKUP_TYPES)].assign(team=lambda d: d["to_team_id"])
    drop = tx["item_type"] == "DROP"
    trade_drop = drop & (tx["type"] == "TRADE_ACCEPT")
    # a drop recorded inside another manager's trade is a forced roster move the
    # manager undoes within minutes (the player never leaves); it ends nothing
    exit_mask = (drop & ~trade_drop) | (trade_drop & own_txn) | (tx["item_type"] == "TRADE")
    exits = tx[exit_mask].assign(team=lambda d: d["from_team_id"])
    other = tx[tx["item_type"].isin(["DRAFT", "TRADE"])].assign(team=lambda d: d["to_team_id"], kind="OTHER")
    acq = pd.concat([adds.assign(kind="ADD"), other]).sort_values("proposed_at_ms", kind="stable")
    own_trade_drops = tx[trade_drop]
    return adds, exits, acq, own_trade_drops


def waiver_stints(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset(),
                  legacy_mode: bool = False, fixes=None) -> pd.DataFrame:
    fx = _fixes(legacy_mode, fixes)
    lu = weeks_mod.bracket_lineups(tables)
    base = weeks_mod.position_baseline(lu, include_ir="no_ir_weeks" not in fx)
    z = weeks_mod.with_z(lu, base, weeks_mod.week_weights(tables))
    if "no_ir_weeks" in fx:
        z = z[z["slot"] != IR_SLOT]
    by_player = {k: g for k, g in z.groupby(["season", "team_id", "player_id"])}
    last_week = lu.groupby(["season", "team_id"])["week"].max()
    owner = tables["teams"].set_index(["season", "team_id"])["manager_key"]
    names = tables["players"].set_index("player_id")["player_name"] if "players" in tables else pd.Series(dtype=object)

    adds, exits, acq, own_trade_drops = _events(tables, fx)
    exits_by = {k: g for k, g in exits.groupby(["season", "team", "player_id"])}
    acq_by = {k: g for k, g in acq.groupby(["season", "team", "player_id"])}
    adds_by = {k: g for k, g in adds.groupby(["season", "team", "player_id"])}
    otd_by = {k: g for k, g in own_trade_drops.groupby(["season", "player_id", "manager_key", "scoring_period"])}

    rows = []
    for a in adds.sort_values(["season", "team", "player_id", "proposed_at_ms"]).itertuples(index=False):
        key = (a.season, a.team, a.player_id)
        wk, ts = a.scoring_period, a.proposed_at_ms
        # claiming a player your own trade dropped this same week
        otd = otd_by.get((a.season, a.player_id, a.manager_key, wk))
        if otd is not None and (otd["proposed_at_ms"] < ts).any():
            continue
        ex = exits_by.get(key, exits.iloc[:0])
        prior = ex[(ex["scoring_period"] == wk) & (ex["proposed_at_ms"] < ts)]
        typ = a.type
        if len(prior):
            acq_k = acq_by.get(key)
            before = acq_k[acq_k["proposed_at_ms"] < prior["proposed_at_ms"].min()] if acq_k is not None else None
            if before is None or not len(before) or before.iloc[-1]["kind"] != "ADD":
                continue                    # drop and re-add of a drafted or traded player: an undo
            if "readd_type" not in fx:
                same_wk = adds_by[key]
                chain = same_wk[(same_wk["scoring_period"] == wk) & (same_wk["proposed_at_ms"] <= ts)]
                if (chain["type"] == "WAIVER").any():
                    typ = "WAIVER"
        same_week_ok = "no_double_count" in fx or not len(prior)
        later = ex[(ex["scoring_period"] > wk)
                   | ((ex["scoring_period"] == wk) & (ex["proposed_at_ms"] > ts) & same_week_ok)]
        end = int(later["scoring_period"].min()) if len(later) else int(last_week.get((a.season, a.team), 0)) + 1
        zz = by_player.get(key)
        zz = zz[(zz["week"] >= wk) & (zz["week"] < end)] if zz is not None else z.iloc[:0]
        n = len(zz)
        if n == 0:
            continue
        pts = float(zz["points"].sum())
        tz = float(zz["z"].sum())
        mk = owner.get((a.season, a.team))
        rows.append({"season": int(a.season), "manager_key": mk, "team_id": int(a.team), "player_id": int(a.player_id),
                     "player_name": names.get(a.player_id), "position": zz["position"].iloc[0],
                     "start_week": int(wk), "end_week": end, "type": typ, "weeks_rostered": n,
                     "total_points": float(np.round(pts, 2)), "ppw": float(np.round(np.round(pts, 2) / n, 2)),
                     "avg_z": tz / n, "total_z": tz,
                     "hidden": mk in exclude_managers})
    out = pd.DataFrame(rows, columns=STINT_COLUMNS)
    if legacy_mode:
        out = out[~out["hidden"]]
        # legacy labeled each player with one position: the one from his first season
        first = tables["lineups"].sort_values(["season", "week"]).drop_duplicates("player_id").set_index("player_id")["position"]
        out["position"] = out["player_id"].map(first).fillna(out["position"])
    return out.sort_values(["season", "manager_key", "start_week", "player_id"]).reset_index(drop=True)


BEST_MIN_WEEKS = 3      # a best-pickup list needs a pickup held at least this long
BEST_LIST = 12


def best_pickups(stints: pd.DataFrame, n: int = BEST_LIST, min_weeks: int = BEST_MIN_WEEKS) -> pd.DataFrame:
    """Top pickups by total z (positive only, held min_weeks or longer) per
    scope ('career' or a season) and position ('ALL' or one)."""
    pool = stints[(stints["total_z"] > 0) & (stints["weeks_rostered"] >= min_weeks)]
    parts = []
    for scope in ["career"] + sorted(pool["season"].astype(str).unique()):
        s = pool if scope == "career" else pool[pool["season"].astype(str) == scope]
        for pos in ["ALL"] + sorted(s["position"].unique()):
            top = (s if pos == "ALL" else s[s["position"] == pos]).sort_values("total_z", ascending=False, kind="stable")
            top = top[~top["hidden"]].head(n)
            parts.append(top.assign(scope=scope, list_position=pos, rank=range(1, len(top) + 1)))
    return pd.concat(parts, ignore_index=True) if parts else pool.iloc[:0]


def waiver_leaderboard(stints: pd.DataFrame) -> pd.DataFrame:
    """Per scope ('career' or a season), position ('ALL' or one), manager, and
    type ('ALL', 'WAIVER', 'FREEAGENT'): pickups, weeks, points per week, and
    z per week (both weighted by weeks rostered)."""
    parts = []
    for scope_col, pos_col, type_col in [(s, p, t) for s in ("career", "season") for p in ("ALL", "position")
                                         for t in ("ALL", "type")]:
        d = stints.assign(scope="career" if scope_col == "career" else stints["season"].astype(str),
                          pos="ALL" if pos_col == "ALL" else stints["position"],
                          kind="ALL" if type_col == "ALL" else stints["type"])
        g = d.groupby(["scope", "pos", "kind", "manager_key"]).agg(
            pickups=("weeks_rostered", "size"), weeks=("weeks_rostered", "sum"), points=("total_points", "sum"),
            total_z=("total_z", "sum"), hidden=("hidden", "any")).reset_index()
        parts.append(g)
    out = pd.concat(parts, ignore_index=True).rename(columns={"pos": "position", "kind": "type"})
    out["ppw"] = out["points"] / out["weeks"]
    out["z_per_week"] = out["total_z"] / out["weeks"]
    return out


def roster_stints(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset()) -> pd.DataFrame:
    """Contiguous runs of counted game weeks on a manager's roster, with the
    weeks started as a comma list."""
    lu = weeks_mod.game_lineups(tables).sort_values(["manager_key", "player_id", "season", "week"])
    rows = []
    for (mk, pid, season), g in lu.groupby(["manager_key", "player_id", "season"], sort=False):
        wks = g["week"].to_numpy()
        started = set(g.loc[g["started"], "week"])
        breaks = np.where(np.diff(wks) != 1)[0]
        starts = np.concatenate([[0], breaks + 1])
        ends = np.concatenate([breaks, [len(wks) - 1]])
        for s, e in zip(starts, ends):
            lo, hi = int(wks[s]), int(wks[e])
            rows.append({"manager_key": mk, "player_id": int(pid), "player_name": g["player_name"].iloc[0],
                         "position": g["position"].iloc[0], "season": int(season), "start": lo, "end": hi,
                         "started": ",".join(str(w) for w in sorted(started) if lo <= w <= hi),
                         "hidden": mk in exclude_managers})
    return pd.DataFrame(rows, columns=["manager_key", "player_id", "player_name", "position", "season", "start",
                                       "end", "started", "hidden"])


def analyze_waivers(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset()) -> dict[str, pd.DataFrame]:
    st = waiver_stints(tables, exclude_managers)
    return {"waiver_stints": st, "waiver_leaderboard": waiver_leaderboard(st), "waiver_best": best_pickups(st),
            "roster_stints": roster_stints(tables, exclude_managers)}

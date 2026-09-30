"""Projected strength of schedule for the live season, rest of season only.

For every regular-season week still to play (from the first week without a
final result), each team's projected total is its best projected lineup:
every rostered player, IR included, with ESPN's projection for that week,
fitted into the league's starting slots (fixed slots first, then flex). A
player on bye or ruled out has no projection or a zero one and is never
picked, so a player on IR who is projected to return counts from the week
he is back. A slot nobody on the roster can fill with a positive projection
takes the best projected available player (free agent or waivers) at that
position that week.

Then, per manager, over those weeks:
    own_avg_proj_ppg   average of the manager's own projected totals
    sos_avg_opp_ppg    average of the scheduled opponents' projected totals
    sos_rank           1 = hardest remaining schedule (highest opponent average)

Rosters and availability are a snapshot from the last `engine pull`: future
pickups, drops, and trades are not known.

legacy_lineups() reproduces build_projected_sos.py's lineup method (current
starters, a bench player swapped in for a starter on bye or projected at
zero, fixed defaults otherwise) so --verify can show what the engine method
changes. sos_from_totals() is shared by both.
"""

from __future__ import annotations

import pandas as pd

from engine.analytics import lineups as lineups_mod
from engine.analytics.weeks import completed_weeks

LINEUP_COLUMNS = ["season", "week", "team_id", "manager_key", "slot", "player_id", "player_name", "position",
                  "projected_points", "source"]


def remaining_weeks(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """(season, week) in the projection snapshot that do not have a final result yet."""
    fm = tables.get("future_matchups")
    if fm is None or not len(fm):
        return pd.DataFrame(columns=["season", "week"])
    weeks = fm[["season", "week"]].drop_duplicates()
    done = completed_weeks(tables).assign(_done=True)
    weeks = weeks.merge(done, on=["season", "week"], how="left")
    return weeks[weeks["_done"].isna()][["season", "week"]].sort_values(["season", "week"]).reset_index(drop=True)


def _slots(tables: dict[str, pd.DataFrame], season: int) -> list[str]:
    slots = lineups_mod.lineup_slots(tables["lineups"])
    if season in slots:
        return slots[season]
    return slots[max(slots)]          # no games yet this season: last season's shape


def _fill(roster: pd.DataFrame, available: pd.DataFrame, slots: list[str]) -> list[dict]:
    """Best projected lineup from the roster; empty slots from the available pool."""
    pool = roster[roster["projected_points"] > 0]
    rows = []
    used_available: set = set()
    for slot, idx in lineups_mod.best_lineup(pool, slots, points="projected_points"):
        if idx is not None:
            r = pool.loc[idx]
            rows.append({"slot": slot, "player_id": r["player_id"], "player_name": r["player_name"],
                         "position": r["position"], "projected_points": float(r["projected_points"]),
                         "source": "roster"})
            continue
        ok = lineups_mod.eligible(slot)
        cand = available[available["position"].isin(ok) & (available["projected_points"] > 0)
                         & ~available["player_id"].isin(used_available)]
        if len(cand):
            r = cand.loc[cand["projected_points"].idxmax()]
            used_available.add(r["player_id"])
            rows.append({"slot": slot, "player_id": r["player_id"], "player_name": r["player_name"],
                         "position": r["position"], "projected_points": float(r["projected_points"]),
                         "source": "available"})
        else:
            rows.append({"slot": slot, "player_id": None, "player_name": None, "position": None,
                         "projected_points": 0.0, "source": "empty"})
    return rows


def projected_lineups(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per team, remaining week, and starting slot: who fills it."""
    weeks = remaining_weeks(tables)
    proj = tables["projections"]
    out = []
    for season, week in weeks.itertuples(index=False):
        slots = _slots(tables, int(season))
        wk = proj[(proj["season"] == season) & (proj["week"] == week)]
        available = wk[wk["source"] == "available"]
        for (team_id, manager_key), roster in wk[wk["source"] == "roster"].groupby(["team_id", "manager_key"]):
            for r in _fill(roster, available, slots):
                out.append({"season": int(season), "week": int(week), "team_id": int(team_id),
                            "manager_key": manager_key, **r})
    return pd.DataFrame(out, columns=LINEUP_COLUMNS)


def team_week_totals(lineups: pd.DataFrame) -> pd.DataFrame:
    """(season, week, manager_key, proj_points)."""
    return (lineups.groupby(["season", "week", "manager_key"])["projected_points"].sum().round(2)
            .rename("proj_points").reset_index())


def sos_from_totals(totals: pd.DataFrame, schedule: pd.DataFrame, start_week: int | None = None) -> pd.DataFrame:
    """Per manager: own and opponents' average projected totals over the
    scheduled weeks from start_week on, and the rank (1 = hardest).

    totals:   season, week, manager_key, proj_points
    schedule: season, week, manager_key, opponent_manager_key
    Averages count only weeks with a total (the legacy script did the same).
    """
    sched = schedule if start_week is None else schedule[schedule["week"] >= start_week]
    t = totals.set_index(["season", "week", "manager_key"])["proj_points"]
    rows = []
    for (season, mgr), g in sched.groupby(["season", "manager_key"]):
        own = [t.get((season, w, mgr)) for w in g["week"]]
        opp = [t.get((season, w, o)) for w, o in zip(g["week"], g["opponent_manager_key"])]
        own = [x for x in own if x is not None and pd.notna(x)]
        opp = [x for x in opp if x is not None and pd.notna(x)]
        if own and opp:
            rows.append({"season": int(season), "manager_key": mgr, "start_week": int(g["week"].min()),
                         "weeks_counted": len(opp), "own_avg_proj_ppg": round(sum(own) / len(own), 2),
                         "sos_avg_opp_ppg": round(sum(opp) / len(opp), 2), "_opp": sum(opp) / len(opp)})
    out = pd.DataFrame(rows, columns=["season", "manager_key", "start_week", "weeks_counted", "own_avg_proj_ppg",
                                      "sos_avg_opp_ppg", "_opp"])
    # rank on the unrounded average, so two managers equal after rounding still rank apart
    out = out.sort_values(["season", "_opp"], ascending=[True, False], kind="stable")
    out["sos_rank"] = out.groupby("season").cumcount() + 1
    return out.drop(columns="_opp").reset_index(drop=True)


# ---------------------------------------------------------------- legacy method

LEGACY_STARTER_SLOTS = {"QB", "RB", "WR", "TE", "RB/WR/TE", "K", "D/ST", "FLEX"}


def legacy_lineups(tables: dict[str, pd.DataFrame], fixed_defaults: dict[str, float]) -> pd.DataFrame:
    """build_projected_sos.py's lineup: each current starter, unless his NFL
    team is on bye or he is projected at zero; then the best projected bench
    player (not IR, not on bye, not already used) who fits the slot, else a
    fixed default for the starter's position."""
    weeks = remaining_weeks(tables)
    proj = tables["projections"]
    byes = tables["pro_teams"][["season", "pro_team_id", "bye_week"]]
    out = []
    for season, week in weeks.itertuples(index=False):
        wk = proj[(proj["season"] == season) & (proj["week"] == week) & (proj["source"] == "roster")]
        on_bye = set(byes.loc[(byes["season"] == season) & (byes["bye_week"] == week), "pro_team_id"])
        for (team_id, manager_key), roster in wk.groupby(["team_id", "manager_key"]):
            starters = roster[roster["slot"].isin(LEGACY_STARTER_SLOTS)]
            bench = roster[~roster["slot"].isin(LEGACY_STARTER_SLOTS) & (roster["slot"] != "IR")]
            used: set = set()
            for _, p in starters.iterrows():
                pts = p["projected_points"] if pd.notna(p["projected_points"]) else 0.0
                row = {"season": int(season), "week": int(week), "team_id": int(team_id), "manager_key": manager_key,
                       "slot": p["slot"]}
                if p["pro_team_id"] not in on_bye and pts != 0.0:
                    out.append({**row, "player_id": p["player_id"], "player_name": p["player_name"],
                                "position": p["position"], "projected_points": float(pts), "source": "roster"})
                    continue
                ok = lineups_mod.eligible(p["slot"]) if p["slot"] != "FLEX" else {"RB", "WR", "TE"}
                cand = bench[bench["position"].isin(ok) & ~bench["player_id"].isin(used)
                             & ~bench["pro_team_id"].isin(on_bye) & (bench["projected_points"].fillna(0) > 0)]
                if len(cand):
                    b = cand.loc[cand["projected_points"].idxmax()]
                    used.add(b["player_id"])
                    out.append({**row, "player_id": b["player_id"], "player_name": b["player_name"],
                                "position": b["position"], "projected_points": float(b["projected_points"]),
                                "source": "bench"})
                else:
                    out.append({**row, "player_id": None, "player_name": None, "position": p["position"],
                                "projected_points": float(fixed_defaults.get(p["position"], 0.0)), "source": "default"})
    return pd.DataFrame(out, columns=LINEUP_COLUMNS)


def analyze_projected_sos(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset()) -> dict[str, pd.DataFrame]:
    if "projections" not in tables or not len(tables.get("future_matchups", [])):
        return {}
    lu = projected_lineups(tables)
    totals = team_week_totals(lu)
    fm = tables["future_matchups"]
    sched = fm.merge(remaining_weeks(tables), on=["season", "week"])[
        ["season", "week", "manager_key", "opponent_manager_key"]].dropna()
    sos = sos_from_totals(totals, sched)
    sos["hidden"] = sos["manager_key"].isin(exclude_managers)
    return {"projected_lineups": lu, "projected_team_weeks": totals, "projected_sos": sos}

"""Check projected strength of schedule against the legacy outputs.

Golden files (sos/):
    projected_sos_weekly_detail.csv.gz  build_projected_sos.py weekly totals,
                                        run with START_WEEK = 3 (before week 3)
    projected_sos_2026.csv.gz           its SOS table from those totals
    schedule_2026.csv.gz                data/schedule_2026.csv, the schedule it read
    and data/rankings/2026_week03.json  the rankings page values copied from it

ESPN projections change every day, so the legacy weekly totals cannot be
pulled again. The check is layered: the shared averaging and ranking step
(sos_from_totals) is fed the legacy weekly totals and schedule and must
reproduce the legacy SOS table and the rankings page values. The lineup step
is new in the engine (best projected lineup from the whole roster instead of
current starters with bye swaps), so INFO lines compare the two lineup
methods on the current snapshot.
"""

from __future__ import annotations

import pandas as pd

from engine.analytics import projected_sos as sos_mod
from engine.legacy import Comparison, compare, name_to_key, resolve_names

# build_projected_sos.py FIXED_DEFAULTS: used only to rerun the legacy lineup method
LEGACY_FIXED_DEFAULTS = {"QB": 14.0, "RB": 4.0, "WR": 8.0, "TE": 6.0, "K": 7.0, "D/ST": 4.0}
LEGACY_SEASON = 2026
LEGACY_START_WEEK = 3


def legacy_inputs(detail: pd.DataFrame, schedule: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    lk = name_to_key(cfg)
    totals = pd.DataFrame({"season": LEGACY_SEASON, "week": detail["week"].astype(int),
                           "manager_key": resolve_names(detail["manager"], lk), "proj_points": detail["proj_ppg"]})
    a, b = resolve_names(schedule["Team_A"], lk), resolve_names(schedule["Team_B"], lk)
    wk = schedule["Week"].astype(int)
    sched = pd.concat([pd.DataFrame({"week": wk, "manager_key": a, "opponent_manager_key": b}),
                       pd.DataFrame({"week": wk, "manager_key": b, "opponent_manager_key": a})], ignore_index=True)
    return totals, sched.assign(season=LEGACY_SEASON)


def check_sos_math(detail: pd.DataFrame, schedule: pd.DataFrame, legacy: pd.DataFrame,
                   ranking: dict | None, cfg: dict) -> list[Comparison]:
    totals, sched = legacy_inputs(detail, schedule, cfg)
    act = sos_mod.sos_from_totals(totals, sched, start_week=LEGACY_START_WEEK)
    lk = name_to_key(cfg)
    exp = pd.DataFrame({"manager_key": resolve_names(legacy["manager"], lk),
                        "own_avg_proj_ppg": legacy["own_avg_proj_ppg"],
                        "sos_avg_opp_ppg": legacy["sos_avg_opp_proj_ppg"],
                        "weeks_counted": legacy["weeks_counted"], "sos_rank": legacy["sos_rank_hardest_first"]})
    checks = [compare("SOS math on legacy weekly totals vs projected_sos_2026.csv", exp, act, keys=["manager_key"],
                      values=["own_avg_proj_ppg", "sos_avg_opp_ppg", "weeks_counted", "sos_rank"], tolerance=1e-9)]
    if ranking is not None:
        page = pd.DataFrame([{"manager_key": lk[t["manager"].strip().lower()], "sos_avg_opp_ppg": t["sos_avg_opp_ppg"],
                              "sos_rank": t["sos_rank"]} for t in ranking["teams"]])
        checks.append(compare(f"SOS math vs rankings {ranking['season']} week {ranking['week']} page", page, act,
                              keys=["manager_key"], values=["sos_avg_opp_ppg", "sos_rank"], tolerance=1e-9))
    return checks


def method_changes(tables: dict, cfg: dict) -> list[str]:
    """INFO: legacy lineup method vs the engine's on the current snapshot."""
    weeks = sos_mod.remaining_weeks(tables)
    if not len(weeks):
        return ["INFO  no live projection snapshot (run `engine pull` during the season)"]
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    fm = tables["future_matchups"].merge(weeks, on=["season", "week"])
    sched = fm[["season", "week", "manager_key", "opponent_manager_key"]].dropna()
    eng_lu = sos_mod.projected_lineups(tables)
    leg_lu = sos_mod.legacy_lineups(tables, LEGACY_FIXED_DEFAULTS)
    eng = sos_mod.sos_from_totals(sos_mod.team_week_totals(eng_lu), sched)
    leg = sos_mod.sos_from_totals(sos_mod.team_week_totals(leg_lu), sched)
    m = leg.merge(eng, on=["season", "manager_key"], suffixes=("_l", "_e"))
    wk = f"weeks {int(weeks['week'].min())}-{int(weeks['week'].max())}"
    lines = [f"INFO  engine lineup method ({wk}): best projected lineup from the whole roster, IR included; "
             f"empty slots from the best available player (legacy: current starters, bench swap for bye or "
             f"zero projection, fixed defaults)",
             f"INFO      slots filled from available players: {int((eng_lu['source'] == 'available').sum())}; "
             f"legacy fixed defaults used: {int((leg_lu['source'] == 'default').sum())}",
             "INFO      own avg / opp avg / rank, legacy -> engine: " + ", ".join(
                 f"{names.get(r.manager_key, r.manager_key)} {r.own_avg_proj_ppg_l:.2f}->{r.own_avg_proj_ppg_e:.2f} "
                 f"/ {r.sos_avg_opp_ppg_l:.2f}->{r.sos_avg_opp_ppg_e:.2f} / {r.sos_rank_l}->{r.sos_rank_e}"
                 for r in m.sort_values("sos_rank_e").itertuples())]
    return lines


def verify_projected_sos(tables: dict, golden: dict, cfg: dict) -> tuple[list[Comparison], list[str]]:
    checks = check_sos_math(golden["projected_sos_weekly_detail"], golden["schedule_2026"],
                            golden["projected_sos_2026"], golden.get("rankings_2026_week03"), cfg)
    info = [f"INFO  legacy weekly totals from START_WEEK {LEGACY_START_WEEK}; checks the averaging and ranking"]
    return checks, info + method_changes(tables, cfg)

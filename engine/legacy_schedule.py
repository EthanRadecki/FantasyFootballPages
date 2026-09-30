"""Compare the schedule analyses with the legacy outputs.

Golden files:
    schedule/schedule_luck_season.csv.gz   build_schedule_luck.py output,
                                           2020-2025 (the site's luck chart
                                           shows its career totals)
    schedule/schedule_swap.json.gz         build_schedule_swap.py output, the
                                           SCHEDULE_SWAP_DATA inline in
                                           extra-analytics.html (identical)

Legacy mode must reproduce both exactly, with one excused pattern: the luck
file was built from an older matchup_data.csv. Where it differs, the check
reruns the legacy luck logic on the current matchup_data.csv (golden) and
excuses the row only if that rerun gives the engine's number. Two 2025 rows
(Hancock, Bileydi) swap one expected win this way.

The legacy swap script patched one
score in memory (2025 week 14, Kelly's row showed McQuaid at 84.46 instead of
86.46); ESPN and the canonical tables have 86.46, so no patch is needed. Its
hardcoded forfeit (Castaldo 2024 week 14) comes from forfeited_weeks().
The live season is left out: the golden files stop at 2025.
"""

from __future__ import annotations

import pandas as pd

from engine.analytics import schedule as schedule_mod
from engine.config import excluded_manager_keys
from engine.legacy import Comparison, compare, name_to_key, resolve_names


def _golden_seasons(tables: dict, seasons: set[int]) -> dict:
    out = dict(tables)
    out["matchups"] = tables["matchups"][tables["matchups"]["season"].isin(seasons)]
    return out


def legacy_luck_rerun(matchup_data: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """build_schedule_luck.py, transcribed, run on a legacy matchup_data.csv:
    regular-season rows ('Week N' labels), excluded managers' own rows
    dropped, weekly median of the remaining scores, expected win when the
    score is above it, actual win when Outcome is 'Win'."""
    lookup = name_to_key(cfg)
    md = matchup_data[matchup_data["Week"].str.startswith("Week")].copy()
    md["manager_key"] = resolve_names(md["Team_Name"], lookup)
    md = md[~md["manager_key"].isin(excluded_manager_keys(cfg))]
    md["season"] = md["Season_Year"].astype(int)
    md["median"] = md.groupby(["season", "Week"])["Team_Score"].transform("median")
    md["expected_win"] = (md["Team_Score"] > md["median"]).astype(float)
    md["actual_win"] = md["Outcome"].eq("Win").astype(float)
    out = md.groupby(["season", "manager_key"]).agg(actual_wins=("actual_win", "sum"),
                                                     expected_wins=("expected_win", "sum")).reset_index()
    out["schedule_luck"] = out["actual_wins"] - out["expected_wins"]
    return out


def check_luck(analysis: dict, legacy: pd.DataFrame, matchup_data: pd.DataFrame, cfg: dict) -> Comparison:
    keys, values = ["season", "manager_key"], ["actual_wins", "expected_wins", "schedule_luck"]
    exp = pd.DataFrame({
        "season": legacy["Season"].astype(int),
        "manager_key": resolve_names(legacy["Manager"], name_to_key(cfg)),
        "actual_wins": legacy["actual_wins"], "expected_wins": legacy["expected_wins"],
        "schedule_luck": legacy["schedule_luck"]})
    act = analysis["schedule_luck"]
    rerun = legacy_luck_rerun(matchup_data, cfg)
    both = exp.merge(act, on=keys, suffixes=("", "_e")).merge(rerun, on=keys, suffixes=("", "_r"))
    reason = "legacy file built from an older matchup_data.csv; its logic on the current one gives the engine's number"
    known = [both.loc[((both[c] - both[f"{c}_e"]).abs() > 1e-9) & ((both[f"{c}_e"] - both[f"{c}_r"]).abs() <= 1e-9),
                      keys].assign(column=c, reason=reason) for c in values]
    return compare("schedule luck vs schedule_luck_season.csv", exp, act, keys=keys, values=values,
                   known=pd.concat(known, ignore_index=True))


def _swap_frames(data: dict, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    lookup = name_to_key(cfg)
    pairs, summary = [], []
    for season, managers in data.items():
        for mgr, d in managers.items():
            summary.append({"season": int(season), "manager": mgr, "wins": d["actual"]["w"],
                            "losses": d["actual"]["l"], "pct": d["actual"]["pct"],
                            "avg_alt_pct": d["avg_pct"], "wins_gained": d["wins_gained"]})
            for other, a in d["alt"].items():
                pairs.append({"season": int(season), "manager": mgr, "schedule": other, "wins": a["w"],
                              "losses": a["l"], "games": a["games"], "pct": a["pct"]})
    p, s = pd.DataFrame(pairs), pd.DataFrame(summary)
    p["manager_key"] = resolve_names(p["manager"], lookup)
    p["schedule_key"] = resolve_names(p["schedule"], lookup)
    s["manager_key"] = resolve_names(s["manager"], lookup)
    return p, s


def _rounded(df: pd.DataFrame, digits: dict[str, int]) -> pd.DataFrame:
    """Round like the legacy JSON (Python round on each value)."""
    out = df.copy()
    for col, n in digits.items():
        out[col] = [round(float(v), n) for v in out[col]]
    return out


def check_swap(analysis: dict, data: dict, cfg: dict) -> list[Comparison]:
    exp_p, exp_s = _swap_frames(data, cfg)
    act_p = _rounded(analysis["schedule_swap"], {"pct": 4})
    act_s = _rounded(analysis["schedule_swap_summary"], {"pct": 4, "avg_alt_pct": 4, "wins_gained": 2})
    return [
        compare("schedule swap pairs vs schedule_swap.json", exp_p, act_p,
                keys=["season", "manager_key", "schedule_key"], values=["wins", "losses", "games", "pct"],
                tolerance=1e-9),
        compare("schedule swap records vs schedule_swap.json", exp_s, act_s, keys=["season", "manager_key"],
                values=["wins", "losses", "pct", "avg_alt_pct", "wins_gained"], tolerance=1e-9),
    ]


def _effect(leg: dict, eng: dict, names: dict) -> list[str]:
    """Differences on the rows users see; hidden rows are only counted."""
    k = ["season", "manager_key"]
    n_hidden = sum(int(eng[t]["hidden"].sum()) for t in ("schedule_luck", "schedule_swap", "schedule_swap_summary"))
    eng = {t: df[~df["hidden"]] for t, df in eng.items()}
    out = [f"{n_hidden} hidden row(s) for excluded managers added"] if n_hidden else []
    luck = leg["schedule_luck"].merge(eng["schedule_luck"], on=k, suffixes=("_l", "_e"))
    moved = luck[(luck["schedule_luck_l"] - luck["schedule_luck_e"]).abs() > 1e-9]
    if len(moved):
        out.append(f"luck changes for {len(moved)} manager-season(s): " + ", ".join(
            f"{r.season} {names.get(r.manager_key, r.manager_key)} {r.schedule_luck_l:+g} -> {r.schedule_luck_e:+g}"
            for r in moved.itertuples()))
    s = leg["schedule_swap_summary"].merge(eng["schedule_swap_summary"], on=k, suffixes=("_l", "_e"))
    s["d"] = (s["wins_gained_e"] - s["wins_gained_l"]).abs()
    by_season = [f"{y}: {int((g['d'] > 0.005).sum())} of {len(g)}, max {g['d'].max():.2f}"
                 for y, g in s.groupby("season") if (g["d"] > 0.005).any()]
    if by_season:
        out.append("swap wins gained changes (" + "; ".join(by_season) + ")")
    p = leg["schedule_swap"].merge(eng["schedule_swap"], on=k + ["schedule_key"], suffixes=("_l", "_e"))
    changed = p[(p["wins_l"] != p["wins_e"]) | (p["losses_l"] != p["losses_e"]) | (p["ties_l"] != p["ties_e"])]
    if len(changed):
        out.append(f"{len(changed)} manager x schedule swap records change")
    return out or ["no effect on current data"]


def engine_changes(tables: dict, exclude: set[str], seasons: set[int], cfg: dict) -> list[str]:
    """INFO lines: the effect of each engine fix on its own, then all together."""
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    t = _golden_seasons(tables, seasons)
    leg = schedule_mod.analyze_schedule(t, exclude, legacy_mode=True)
    lines = []
    for fix, text in schedule_mod.ENGINE_CHANGES.items():
        eng = schedule_mod.analyze_schedule(t, exclude, fixes={fix})
        lines.append(f"INFO  engine fix [{fix}] {text}")
        lines += [f"INFO      {e}" for e in _effect(leg, eng, names)]
    eng = schedule_mod.analyze_schedule(t, exclude)
    lines.append("INFO  all engine fixes together:")
    lines += [f"INFO      {e}" for e in _effect(leg, eng, names)]
    k = ["season", "manager_key"]
    luck = leg["schedule_luck"].merge(eng["schedule_luck"][~eng["schedule_luck"]["hidden"]], on=k,
                                      suffixes=("_l", "_e"))
    car = luck.groupby("manager_key")[["schedule_luck_l", "schedule_luck_e"]].sum()
    car = car[(car["schedule_luck_l"] - car["schedule_luck_e"]).abs() > 1e-9]
    if len(car):
        lines.append("INFO      career luck (site chart): " + ", ".join(
            f"{names.get(m, m)} {r.schedule_luck_l:+g} -> {r.schedule_luck_e:+g}" for m, r in car.iterrows()))
    return lines


def verify_schedule(tables: dict, golden: dict, cfg: dict) -> tuple[list[Comparison], list[str]]:
    exclude = excluded_manager_keys(cfg)
    seasons = {int(y) for y in golden["schedule_swap"]} | set(golden["schedule_luck_season"]["Season"].astype(int))
    t = _golden_seasons(tables, seasons)
    legacy = schedule_mod.analyze_schedule(t, exclude, legacy_mode=True)
    checks = [check_luck(legacy, golden["schedule_luck_season"], golden["matchup_data"], cfg), *check_swap(legacy, golden["schedule_swap"], cfg)]
    info = [f"INFO  seasons {min(seasons)}-{max(seasons)}; legacy mode"] + engine_changes(tables, exclude, seasons, cfg)
    return checks, info

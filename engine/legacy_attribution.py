"""Compare win% attribution with the legacy outputs.

Golden files:
    attribution/win_attribution_final.json.gz          build_win_attribution_final.py
                                                       output; its DATA is the
                                                       inline DATA on
                                                       extra-analytics.html
                                                       (identical)
    attribution/attribution_season_data_final.csv.gz   the factor table it fit
                                                       (83 manager-seasons)

Two layers, both on legacy files (the factor inputs themselves are checked
against the engine by their own modules):
1. fit: the legacy factor table through fit() must reproduce the JSON
   exactly (rounded as the script rounded).
2. factors: factor_table() on the legacy inputs (draft_surplus_v2.csv,
   waiver_stints_full.csv, lineup_efficiency.csv, metrics_final.csv,
   schedule_luck_season.csv, matchup_data.csv) must reproduce the factor
   table. One pattern is excused: the luck file is older than the
   attribution run (see legacy_schedule.py); where they differ, the legacy
   luck logic rerun on the current matchup_data.csv must give the value the
   attribution used.
"""

from __future__ import annotations

import pandas as pd

from engine.analytics import attribution as attr
from engine.config import excluded_manager_keys
from engine.legacy import Comparison, compare, name_to_key, resolve_names
from engine.legacy_schedule import legacy_luck_rerun

KEYS = ["season", "manager_key"]
LEGACY_FACTOR_COLS = {"W%": "win_pct", **{f: f for f in attr.FACTORS}}


def _keyed(df: pd.DataFrame, name_col: str, season_col: str, value_col: str, cfg: dict) -> pd.DataFrame:
    out = pd.DataFrame({"season": df[season_col].astype(int),
                        "manager_key": resolve_names(df[name_col], name_to_key(cfg)),
                        "value": df[value_col].astype(float)})
    return out[~out["manager_key"].isin(excluded_manager_keys(cfg))]


def legacy_win_pct(matchup_data: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """build_win_attribution_final.py: regular-season rows ('Week N') and real
    playoff rows (Is_Playoff Yes), excluded managers' own rows dropped, share
    of rows with Outcome Win."""
    md = matchup_data[matchup_data["Week"].str.startswith("Week") | matchup_data["Is_Playoff"].eq("Yes")]
    md = md.assign(win=md["Outcome"].eq("Win").astype(float))
    k = _keyed(md, "Team_Name", "Season_Year", "win", cfg)
    return k.groupby(KEYS)["value"].mean().rename("win_pct").reset_index()


def legacy_inputs(golden: dict, cfg: dict) -> dict[str, pd.DataFrame]:
    luck = golden["schedule_luck_season"]
    luck = pd.DataFrame({"season": luck["Season"].astype(int),
                         "manager_key": resolve_names(luck["Manager"], name_to_key(cfg)),
                         "value": luck["schedule_luck"].astype(float)})
    return {
        "win_pct": legacy_win_pct(golden["matchup_data"], cfg),
        "draft": _keyed(golden["draft_surplus_v2"], "manager", "season", "surplus_wtd", cfg),
        "waiver": _keyed(golden["waiver_stints_full"], "Manager", "Season", "Total_Z", cfg),
        "lineup": _keyed(golden["lineup_efficiency"].assign(m=golden["lineup_efficiency"]["Missed_Win"].astype(float)),
                         "Manager", "Season", "m", cfg),
        "trade": _keyed(golden["metrics_final"], "manager", "season", "QUAD", cfg),
        "luck": luck[~luck["manager_key"].isin(excluded_manager_keys(cfg))],
    }


def published_factors(golden: dict, cfg: dict) -> pd.DataFrame:
    p = golden["attribution_season_data_final"].rename(columns=LEGACY_FACTOR_COLS)
    p["season"] = p["Season"].astype(int)
    p["manager_key"] = resolve_names(p["Manager"], name_to_key(cfg))
    return p[KEYS + ["win_pct"] + attr.FACTORS]


def check_factors(golden: dict, cfg: dict) -> Comparison:
    exp = published_factors(golden, cfg)
    act = attr.factor_table(**legacy_inputs(golden, cfg))
    rerun = legacy_luck_rerun(golden["matchup_data"], cfg)[KEYS + ["schedule_luck"]]
    b = exp.merge(act, on=KEYS, suffixes=("_p", "_a")).merge(rerun, on=KEYS)
    reason = "luck file older than the attribution run; the legacy luck logic on the current matchup_data.csv gives the value used"
    ok = ((b["schedule_luck_p"] - b["schedule_luck_a"]).abs() > 1e-9) & ((b["schedule_luck_p"] - b["schedule_luck"]).abs() <= 1e-9)
    known = b.loc[ok, KEYS].assign(column="schedule_luck", reason=reason)
    return compare("attribution factors vs attribution_season_data_final.csv", exp, act, keys=KEYS,
                   values=["win_pct"] + attr.FACTORS, tolerance=1e-9, known=known)


def _published_frames(data: dict, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    lk = name_to_key(cfg)
    m = pd.DataFrame([{"manager": k, **v} for k, v in data["DATA"].items()])
    m["manager_key"] = resolve_names(m["manager"], lk)
    c = pd.DataFrame({"factor": list(data["standardized_coef"]),
                      "std_coef": list(data["standardized_coef"].values()),
                      "p_value": [data["p_values"][f] for f in data["standardized_coef"]]})
    s = pd.DataFrame([{"n": data["n"], "r2": data["r2"], "adj_r2": data["adj_r2"],
                       "league_intercept": data["LEAGUE_INTERCEPT"],
                       "all_significant": data["all_significant"]}])
    return m, c, s


def rounded(res: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """The fit, rounded as the legacy JSON was (Python round per value)."""
    def r(values, n):
        return [round(float(v), n) for v in values]

    m = res["attribution_managers"].copy()
    m["winpct"] = r(m["win_pct"], 1)
    for col in ["draft", "waiver", "lineup", "trade", "luck", "predicted", "residual"]:
        m[col] = r(m[col], 2)
    c = res["attribution_coefficients"].copy()
    c["std_coef"], c["p_value"] = r(c["std_coef"], 4), r(c["p_value"], 4)
    s = res["attribution_fit"].copy()
    s["r2"], s["adj_r2"], s["league_intercept"] = r(s["r2"], 4), r(s["adj_r2"], 4), r(s["league_intercept"], 2)
    return m, c, s


def check_fit(golden: dict, cfg: dict) -> list[Comparison]:
    f = published_factors(golden, cfg).assign(hidden=False)
    act_m, act_c, act_s = rounded(attr.fit(f, sample_sd=False))
    exp_m, exp_c, exp_s = _published_frames(golden["win_attribution_final"], cfg)
    cols = ["winpct", "draft", "waiver", "lineup", "trade", "luck", "predicted", "residual"]
    act_s["key"] = exp_s["key"] = 1
    return [
        compare("attribution managers vs win_attribution_final.json", exp_m, act_m, keys=["manager_key"],
                values=cols, tolerance=1e-9),
        compare("attribution coefficients vs win_attribution_final.json", exp_c, act_c, keys=["factor"],
                values=["std_coef", "p_value"], tolerance=1e-9),
        compare("attribution fit vs win_attribution_final.json", exp_s, act_s, keys=["key"],
                values=["n", "r2", "adj_r2", "league_intercept", "all_significant"], tolerance=1e-9),
    ]


def _summary(res: dict) -> str:
    s = res["attribution_fit"].iloc[0]
    c = res["attribution_coefficients"]
    order = c.reindex(c["std_coef"].abs().sort_values(ascending=False).index)
    return (f"n {int(s['n'])}, R2 {s['r2']:.4f}, league intercept {s['league_intercept']:.2f}; standardized: "
            + ", ".join(f"{r.factor} {r.std_coef:.3f} (p {r.p_value:.3f})" for r in order.itertuples()))


def engine_changes(tables: dict, results: dict, golden: dict, cfg: dict) -> list[str]:
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    ex = excluded_manager_keys(cfg)
    leg = attr.analyze_attribution(tables, results, ex, legacy_mode=True)
    lines = [f"INFO  published: {_summary(attr.fit(published_factors(golden, cfg).assign(hidden=False), sample_sd=False))}",
             f"INFO  engine inputs, legacy attribution rules: {_summary(leg)}"]
    for fix, text in attr.ENGINE_CHANGES.items():
        eng = attr.analyze_attribution(tables, results, ex, fixes={fix})
        lines.append(f"INFO  engine fix [{fix}] {text}")
        lines.append(f"INFO      {_summary(eng)}")
    eng = attr.analyze_attribution(tables, results, ex)
    lines.append(f"INFO  engine (all fixes): {_summary(eng)}")
    pub = _published_frames(golden["win_attribution_final"], cfg)[0].set_index("manager_key")
    em = eng["attribution_managers"]
    em = em[~em["hidden"]].set_index("manager_key")
    moves = [(names.get(k, k), pub.loc[k, "predicted"], em.loc[k, "predicted"], pub.loc[k, "residual"],
              em.loc[k, "residual"]) for k in em.index if k in pub.index]
    lines.append("INFO      predicted win% (residual), published -> engine: " + ", ".join(
        f"{n} {p0:.1f} ({r0:+.1f}) -> {p1:.1f} ({r1:+.1f})" for n, p0, p1, r0, r1 in moves))
    return lines


def verify_attribution(tables: dict, results: dict, golden: dict, cfg: dict) -> tuple[list[Comparison], list[str]]:
    checks = [check_factors(golden, cfg), *check_fit(golden, cfg)]
    info = ["INFO  seasons 2020-2025; legacy files through the engine's factor builder and fit"]
    return checks, info + engine_changes(tables, results, golden, cfg)

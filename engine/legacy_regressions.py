"""Compare positional production and the quarterly playoff model with
extra-analytics.html.

Golden file:
    regressions/extra_analytics_regressions.json.gz   the page's inline
                                                      positional DATA,
                                                      STD_COEF, COEF_PVAL,
                                                      CORR_R, its R2 (0.57,
                                                      n=83), and the quarterly
                                                      coefs, corrs, pvals

Both checks feed the legacy inputs through the engine's functions (players'
positions and lineups from weekly_rosters_bracket_only.csv, game weeks
only; win% and quarter scores from matchup_data.csv; playoffs from the stats
file), 2020-2025, excluded managers dropped.

Positional production: the manager table (every career average and SD, and
win%) must match exactly. The page's regression came from a slightly earlier
data version: excused by pattern when within 0.005 (standardized
coefficients, correlations) and 0.012 (p-values) of the legacy inputs' fit;
R2 and n must match.

Quarterly model (export_quarterly_regression.py): the correlations must
match exactly. The page's coefficients and p-values came from a run that
cannot be reproduced (p-values of 0.000 with n=83); Ethan decided to port the
correct numbers (session 4), so they are excused and replaced.
"""

from __future__ import annotations

import pandas as pd

from engine.analytics import regressions as rg
from engine.config import excluded_games, excluded_manager_keys
from engine.legacy import Comparison, compare, name_to_key, resolve_names

LAST_SEASON = 2025
COEF_CLOSE, P_CLOSE = 0.005, 0.012


def _keys(names: pd.Series, cfg: dict) -> pd.Series:
    return resolve_names(names, name_to_key(cfg))


def legacy_weekly(rosters: pd.DataFrame, md: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    games = {(s, w, m) for s, w, m in zip(md["Season_Year"], md["Week"], md["Team_Name"])}
    r = rosters[[(s, w, m) in games for s, w, m in zip(rosters["Season"], rosters["Week_Label"], rosters["Manager"])]]
    r = r[r["Season"] <= LAST_SEASON]
    lu = pd.DataFrame({"manager_key": _keys(r["Manager"], cfg), "season": r["Season"].astype(int),
                       "week": r["Week"].astype(int), "position": r["Position"], "points": r["Points"].astype(float),
                       "started": r["Started"].astype(bool)})
    lu = lu[~lu["manager_key"].isin(excluded_manager_keys(cfg))]
    return rg.weekly_position_points(lu, rg.POSITION_ORDER)


def legacy_regular(md: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    m = md[md["Week"].str.startswith("Week") & (md["Season_Year"] <= LAST_SEASON)]
    out = pd.DataFrame({"season": m["Season_Year"].astype(int), "manager_key": _keys(m["Team_Name"], cfg),
                        "week": m["Week"].str.extract(r"(\d+)$")[0].astype(int),
                        "points": m["Team_Score"].astype(float), "win": m["Outcome"].eq("Win").astype(float)})
    return out[~out["manager_key"].isin(excluded_manager_keys(cfg))]


def check_positions(golden: dict, cfg: dict) -> list[Comparison]:
    page = golden["extra_analytics_regressions"]
    lk = name_to_key(cfg)
    reg = legacy_regular(golden["matchup_data"], cfg)
    wp = reg.groupby(["season", "manager_key"])["win"].mean().rename("win_pct").reset_index()
    res = rg.position_fit(legacy_weekly(golden["weekly_rosters_bracket_only"], golden["matchup_data"], cfg), wp)
    career = res["career"].set_index("manager_key")
    career_wp = reg.groupby("manager_key")["win"].mean() * 100
    exp, act = [], []
    for d in page["position_data"]:
        k = lk[d["mgr"].lower()]
        exp.append({"manager_key": k, "winpct": d["winpct"], **{f"{p}_avg": d["avg"][p] for p in rg.POSITION_ORDER},
                    **{f"{p}_sd": d["std"][p] for p in rg.POSITION_ORDER}})
        act.append({"manager_key": k, "winpct": round(float(career_wp[k]), 1),
                    **{f"{p}_{s}": round(float(career.loc[k, f"{p}_{s}"]), 2) for p in rg.POSITION_ORDER
                       for s in ("avg", "sd")}})
    cols = ["winpct"] + [f"{p}_{s}" for p in rg.POSITION_ORDER for s in ("avg", "sd")]
    checks = [compare("positional production table vs extra-analytics.html DATA", pd.DataFrame(exp),
                      pd.DataFrame(act), keys=["manager_key"], values=cols, tolerance=1e-9)]

    c = res["coefficients"].set_index("position")
    exp_c = pd.DataFrame([{"position": p, "std_coef": page["STD_COEF"][p], "p_value": page["COEF_PVAL"][p],
                           "corr": page["CORR_R"][p]} for p in rg.POSITION_ORDER])
    act_c = pd.DataFrame([{"position": p, "std_coef": round(float(c.loc[p, "std_coef"]), 3),
                           "p_value": round(float(c.loc[p, "p_value"]), 4), "corr": round(float(c.loc[p, "corr"]), 3)}
                          for p in rg.POSITION_ORDER])
    known = []
    reason = "page fit from a slightly earlier data version (within {:g} of the legacy inputs' fit)"
    for r_e, r_a in zip(exp_c.itertuples(), act_c.itertuples()):
        for col, bound in (("std_coef", COEF_CLOSE), ("p_value", P_CLOSE), ("corr", COEF_CLOSE)):
            if 0 < abs(getattr(r_e, col) - getattr(r_a, col)) <= bound + 1e-9:
                known.append({"position": r_e.position, "column": col, "reason": reason.format(bound)})
    checks.append(compare("positional regression vs extra-analytics.html STD_COEF, COEF_PVAL, CORR_R", exp_c, act_c,
                          keys=["position"], values=["std_coef", "p_value", "corr"], tolerance=1e-9,
                          known=pd.DataFrame(known, columns=["position", "column", "reason"])))
    s = res["summary"].iloc[0]
    checks.append(compare("positional regression fit vs extra-analytics.html (n, R2)",
                          pd.DataFrame([{"k": 1, "n": page["position_n"], "r2": page["position_r2"]}]),
                          pd.DataFrame([{"k": 1, "n": int(s["n"]), "r2": round(float(s["r2"]), 2)}]),
                          keys=["k"], values=["n", "r2"], tolerance=1e-9))
    return checks


def check_quarterly(golden: dict, cfg: dict) -> Comparison:
    page = golden["extra_analytics_regressions"]["quarterly"]
    stats = golden["preach_manager_stats"]
    stats = stats[stats["Year"] <= LAST_SEASON]
    playoffs = pd.DataFrame({"season": stats["Year"].astype(int), "manager_key": _keys(stats["Manager"], cfg),
                             "made": stats["Playoffs"].astype(int)})
    reg = legacy_regular(golden["matchup_data"], cfg)
    res = rg.quarterly_fit(reg[["season", "manager_key", "week", "points"]], playoffs, rg.LEGACY_QUARTERS)
    c = res["quarterly_coefficients"]
    exp = pd.DataFrame({"quarter": c["quarter"], "coef": page["coefs"], "p_value": page["pvals"], "corr": page["corrs"]})
    act = pd.DataFrame({"quarter": c["quarter"], "coef": [round(float(v), 3) for v in c["coef"]],
                        "p_value": [round(float(v), 3) for v in c["p_value"]],
                        "corr": [round(float(v), 3) for v in c["corr"]]})
    reason = "page coefficients from a run that cannot be reproduced; replaced with the correct fit (Ethan, session 4)"
    known = pd.DataFrame([{"quarter": q, "column": col, "reason": reason} for q in c["quarter"]
                          for col in ("coef", "p_value")])
    return compare("quarterly model vs extra-analytics.html coefs, corrs, pvals", exp, act, keys=["quarter"],
                   values=["coef", "p_value", "corr"], tolerance=1e-9, known=known)


def _pos_line(res: dict) -> str:
    c = res["position_coefficients"].set_index("position")
    s = res["position_fit"].iloc[0]
    return (f"n {int(s['n'])}, R2 {s['r2']:.3f}; " + ", ".join(
        f"{p} {c.loc[p, 'std_coef']:.3f} (p {c.loc[p, 'p_value']:.4f}, r {c.loc[p, 'corr']:.3f})" for p in c.index))


def _q_line(res: dict) -> str:
    c = res["quarterly_coefficients"]
    s = res["quarterly_fit"].iloc[0]
    return (f"n {int(s['n'])}, AUC {s['auc']:.3f}; " + ", ".join(
        f"{r.quarter} wks {r.weeks} {r.coef:+.3f} (p {r.p_value:.3f}, r {r.corr:.3f})" for r in c.itertuples()))


def engine_changes(tables: dict, results: dict, golden: dict, cfg: dict) -> list[str]:
    ex, ppg = excluded_manager_keys(cfg), excluded_games(cfg, "ppg")
    ms = results["manager_seasons"]
    cut = ((cfg.get("analysis") or {}).get("playoff_odds") or {}).get("cutoff")
    page = golden["extra_analytics_regressions"]["quarterly"]
    stats = golden["preach_manager_stats"]
    stats = stats[stats["Year"] <= LAST_SEASON]
    reg = legacy_regular(golden["matchup_data"], cfg)
    legq = rg.quarterly_fit(reg[["season", "manager_key", "week", "points"]],
                            pd.DataFrame({"season": stats["Year"].astype(int),
                                          "manager_key": _keys(stats["Manager"], cfg),
                                          "made": stats["Playoffs"].astype(int)}), rg.LEGACY_QUARTERS)
    lines = ["INFO  quarterly, page: " + ", ".join(f"Q{i + 1} {c:+.3f} (p {p:.3f}, r {r:.3f})" for i, (c, p, r) in
                                                    enumerate(zip(page["coefs"], page["pvals"], page["corrs"]))),
             f"INFO  quarterly, legacy inputs (the correct fit of the page's method): {_q_line(legq)}"]
    leg = {**rg.position_production(tables, ex, ppg, legacy_mode=True),
           **rg.quarterly_model(tables, ms, ex, ppg, legacy_mode=True, cutoff=cut)}
    lines += [f"INFO  positions, engine inputs, legacy rules: {_pos_line(leg)}",
              f"INFO  quarterly, engine inputs, legacy rules: {_q_line(leg)}"]
    for fix, text in rg.ENGINE_CHANGES.items():
        eng = {**rg.position_production(tables, ex, ppg, fixes={fix}),
               **rg.quarterly_model(tables, ms, ex, ppg, fixes={fix}, cutoff=cut)}
        lines.append(f"INFO  engine fix [{fix}] {text}")
        lines += [f"INFO      positions: {_pos_line(eng)}", f"INFO      quarterly: {_q_line(eng)}"]
    eng = {**rg.position_production(tables, ex, ppg), **rg.quarterly_model(tables, ms, ex, ppg, cutoff=cut)}
    lines += ["INFO  engine (all fixes):", f"INFO      positions: {_pos_line(eng)}",
              f"INFO      quarterly: {_q_line(eng)}"]
    return lines


def verify_regressions(tables: dict, results: dict, golden: dict, cfg: dict) -> tuple[list[Comparison], list[str]]:
    checks = [*check_positions(golden, cfg), check_quarterly(golden, cfg)]
    info = [f"INFO  legacy inputs 2020-{LAST_SEASON}, excluded managers dropped"]
    return checks, info + engine_changes(tables, results, golden, cfg)

"""Win% attribution: how much of each manager's win% comes from the draft,
waivers, lineups, trades, and schedule luck.

Replaces build_win_attribution_final.py (the waterfall on
extra-analytics.html).

One row per finished manager-season:
    win_pct         counted games (regular season and winners bracket; no
                    byes, no consolation games), as points out of 100
    draft_value     sum of the season's weighted draft surplus
    waiver_value    sum of each waiver stint's total z, upside only (a
                    stint below zero counts as 0, not as a penalty)
    lineup_value    minus the missed wins (weeks a better lineup from the
                    same roster would have won; a forfeited week counts)
    trade_value     sum of QUAD over the manager's trade sides (0 with no
                    trades)
    schedule_luck   actual minus expected wins against the weekly median

An ordinary least squares fit of win_pct on the five factors gives each
factor's coefficient, standardized coefficient (coefficient x SD of the
factor / SD of win%), and p-value. Per manager: the average of each factor
over their seasons, minus the league average, times the coefficient, is
that factor's contribution in win% points; the league intercept is the
prediction at league-average inputs, and residual = actual - predicted.

Excluded managers (Sullivan, Serafin) are data points in the fit like
everyone else and are only hidden from view (their manager rows carry
`hidden`).

legacy_mode=True reproduces the legacy script's own choices; the engine
default applies every fix in ENGINE_CHANGES. The factor inputs come from the
other modules in whatever mode they ran.

All functions are pure: canonical and analysis tables in, DataFrames out.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as spstats

from engine.analytics.weeks import counted_games, live_seasons

FACTORS = ["draft_value", "waiver_value", "lineup_value", "trade_value", "schedule_luck"]
LABELS = {"draft_value": "draft", "waiver_value": "waiver", "lineup_value": "lineup",
          "trade_value": "trade", "schedule_luck": "luck"}
KEYS = ["season", "manager_key"]

ENGINE_CHANGES = {
    "include_excluded": "excluded managers' seasons (Sullivan, Serafin 2020) are data points in the fit and only "
                        "hidden from view; legacy dropped them",
    "sample_sd": "standardized coefficients use the sample SD of win% as well as of each factor (legacy divided "
                 "a sample SD by a population SD)",
}


def _fixes(legacy_mode: bool, fixes) -> frozenset:
    if fixes is not None:
        return frozenset(fixes)
    return frozenset() if legacy_mode else frozenset(ENGINE_CHANGES)


def season_win_pct(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """(season, manager_key, win_pct) over counted games, ties as half."""
    g = counted_games(tables)
    pts = g["result"].map({"W": 1.0, "T": 0.5}).fillna(0.0)
    out = pts.groupby([g["season"], g["manager_key"]]).mean().rename("win_pct").reset_index()
    return out


def factor_table(win_pct: pd.DataFrame, draft: pd.DataFrame, waiver: pd.DataFrame, lineup: pd.DataFrame,
                 trade: pd.DataFrame, luck: pd.DataFrame) -> pd.DataFrame:
    """Joins per-season inputs into one row per manager-season.

    Each input is (season, manager_key, value): draft surplus per pick, waiver
    total z per stint, missed win per week (1 or 0), QUAD per trade side,
    luck per season. Rows missing a draft, waiver, lineup, or luck value are
    dropped; no trades means trade_value 0."""
    def total(df, name, clip=False):
        v = df["value"].clip(lower=0) if clip else df["value"]
        return v.groupby([df["season"], df["manager_key"]]).sum().rename(name).reset_index()

    out = win_pct.merge(total(draft, "draft_value"), on=KEYS, how="left")
    out = out.merge(total(waiver, "waiver_value", clip=True), on=KEYS, how="left")
    lu = total(lineup, "lineup_value")
    lu["lineup_value"] = -lu["lineup_value"]
    out = out.merge(lu, on=KEYS, how="left")
    out = out.merge(total(trade, "trade_value"), on=KEYS, how="left")
    out = out.merge(luck.rename(columns={"value": "schedule_luck"}), on=KEYS, how="left")
    out["trade_value"] = out["trade_value"].fillna(0.0)
    out = out.dropna(subset=["draft_value", "waiver_value", "lineup_value", "schedule_luck"])
    return out.sort_values(KEYS).reset_index(drop=True)


def engine_inputs(tables: dict[str, pd.DataFrame], results: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """The five factor inputs and win% from the canonical and analysis
    tables, finished seasons only."""
    live = live_seasons(tables)

    def done(df):
        return df[~df["season"].isin(live)]

    def v(df, col):
        return done(df)[["season", "manager_key", col]].rename(columns={col: "value"})

    lu = results["lineup_efficiency"]
    lu = lu.assign(missed=lu["missed_win"].astype(float))   # a forfeited week is still a missed win
    return {"win_pct": done(season_win_pct(tables)), "draft": v(results["draft_surplus"], "surplus_wtd"),
            "waiver": v(results["waiver_stints"], "total_z"), "lineup": v(lu, "missed"),
            "trade": v(results["trade_metrics"], "QUAD"), "luck": v(results["schedule_luck"], "schedule_luck")}


def fit(factors: pd.DataFrame, sample_sd: bool = True) -> dict[str, pd.DataFrame]:
    """OLS of win% (points out of 100) on the factors, and each manager's
    contributions. `factors` needs the FACTORS columns, win_pct (0-1), and
    `hidden` (manager rows to hide from view)."""
    df = factors.reset_index(drop=True)
    y = df["win_pct"].to_numpy(float) * 100
    X = np.column_stack([np.ones(len(df)), df[FACTORS].to_numpy(float)])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    n, k = X.shape
    ss_res, ss_tot = float(resid @ resid), float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot
    adj_r2 = 1 - (1 - r2) * (n - 1) / (n - k - 1)   # legacy's formula (k counts the intercept), kept as published
    se = np.sqrt(np.diag(ss_res / (n - k) * np.linalg.inv(X.T @ X)))
    p = 2 * (1 - spstats.t.cdf(np.abs(coef / se), df=n - k))
    sd_y = y.std(ddof=1 if sample_sd else 0)
    b = dict(zip(FACTORS, coef[1:]))
    coefficients = pd.DataFrame({
        "factor": [LABELS[f] for f in FACTORS], "coef": coef[1:],
        "std_coef": [b[f] * df[f].std(ddof=1) / sd_y for f in FACTORS], "p_value": p[1:]})

    avg = df[FACTORS].mean()
    league_intercept = coef[0] + sum(b[f] * avg[f] for f in FACTORS)
    by = df.groupby("manager_key")
    means = by[FACTORS].mean()
    rows = []
    for mgr, row in means.iterrows():
        contrib = {LABELS[f]: b[f] * (row[f] - avg[f]) for f in FACTORS}
        actual = float(by["win_pct"].mean()[mgr]) * 100
        predicted = league_intercept + sum(contrib.values())
        rows.append({"manager_key": mgr, "seasons": int(by.size()[mgr]), "win_pct": actual, **contrib,
                     "predicted": predicted, "residual": actual - predicted,
                     "hidden": bool(by["hidden"].first()[mgr])})
    summary = pd.DataFrame([{"n": n, "r2": r2, "adj_r2": adj_r2, "intercept": coef[0],
                             "league_intercept": league_intercept,
                             "all_significant": bool((p[1:] < 0.05).all())}])
    return {"attribution_coefficients": coefficients, "attribution_fit": summary,
            "attribution_managers": pd.DataFrame(rows)}


def analyze_attribution(tables: dict[str, pd.DataFrame], results: dict[str, pd.DataFrame],
                        exclude_managers: set[str] = frozenset(), legacy_mode: bool = False,
                        fixes=None) -> dict[str, pd.DataFrame]:
    fx = _fixes(legacy_mode, fixes)
    inputs = engine_inputs(tables, results)
    factors = factor_table(**inputs)
    factors["hidden"] = factors["manager_key"].isin(exclude_managers)
    used = factors if "include_excluded" in fx else factors[~factors["hidden"]]
    return {"attribution_factors": factors, **fit(used, sample_sd="sample_sd" in fx)}

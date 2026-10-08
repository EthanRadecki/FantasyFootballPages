"""Season-level models on extra-analytics.html: positional production and
the quarterly playoff model.

Positional production
    Weekly started points per position (a position with no starter that week
    counts 0), over counted games (finished regular-season and winners-
    bracket games; no byes, no consolation games). Per manager: the career
    average and sample SD of those weekly totals, and career regular-season
    win%. Per manager-season: the average weekly points per position; an
    ordinary least squares fit of that season's regular-season win% on the
    six averages gives standardized coefficients (coefficient x SD of the
    position / SD of win%, sample SDs), p-values, R2, and each position's
    Pearson correlation with win%.

Quarterly playoff model
    Average regular-season score in each quarter of the season (weeks 1-3,
    4-6, 7-9, and 10 to the end of each regular season) against whether the
    manager finished in the league's playoff field (division winners, then
    the best records up to league.yaml analysis.playoff_odds.cutoff, as on
    the D/ST page), per finished manager-season. A logistic
    regression on standardized quarter averages (population SD) gives each
    quarter's coefficient, p-value (Wald), and odds ratio, plus the model's
    AUC; each quarter's Pearson correlation with making the playoffs.

Forfeits: a game in league.yaml exclude_games (from: [ppg]) is a sat lineup,
so the forfeiter's week leaves both models' point averages; the result
still counts in win%.

Excluded managers (Sullivan, Serafin) are data points like everyone else and
only hidden from view.

All functions are pure: tables in, DataFrames out.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats as spstats

from engine.analytics.weeks import counted_games, game_lineups, live_seasons

POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "D/ST"]
LEGACY_QUARTERS = [(1, 3), (4, 6), (7, 9), (10, 13)]

ENGINE_CHANGES = {
    "include_excluded": "excluded managers' seasons (Sullivan, Serafin 2020) are data points and only hidden; "
                        "legacy dropped them",
    "ppg_exclusions": "the forfeiter's week (league.yaml exclude_games, from: [ppg]) leaves the point averages; "
                      "legacy counted Castaldo's 2024 week 14 zeros",
    "q4_to_season_end": "the last quarter runs from week 10 to the end of the regular season; legacy stopped at "
                        "week 13, leaving out week 14 of 14-week seasons (2022 on)",
    "league_field": "the quarterly model's outcome is the league's playoff field (division winners, then the best "
                    "records up to league.yaml analysis.playoff_odds.cutoff), as on the D/ST page; legacy used the "
                    "real brackets, where all 15 teams of 2020 made it",
}


def _fixes(legacy_mode: bool, fixes) -> frozenset:
    if fixes is not None:
        return frozenset(fixes)
    return frozenset() if legacy_mode else frozenset(ENGINE_CHANGES)


# ---------------------------------------------------------------- models

def ols(y: np.ndarray, X: pd.DataFrame) -> dict:
    """OLS with intercept: coef, std_coef (sample SDs), p (t test), r2, n."""
    A = np.column_stack([np.ones(len(X)), X.to_numpy(float)])
    b, *_ = np.linalg.lstsq(A, y, rcond=None)
    res = y - A @ b
    n, k = A.shape
    se = np.sqrt(np.diag(res @ res / (n - k) * np.linalg.inv(A.T @ A)))
    p = 2 * (1 - spstats.t.cdf(np.abs(b / se), n - k))
    sd_y = y.std(ddof=1)
    return {"coef": dict(zip(X.columns, b[1:])),
            "std_coef": {c: b[i + 1] * X[c].std(ddof=1) / sd_y for i, c in enumerate(X.columns)},
            "p": dict(zip(X.columns, p[1:])),
            "r2": 1 - res @ res / ((y - y.mean()) @ (y - y.mean())), "n": n}


def logit(y: np.ndarray, X: pd.DataFrame, iterations: int = 100) -> dict:
    """Logistic regression (Newton's method) on columns standardized with the
    population SD; Wald p-values; AUC of the fitted probabilities."""
    Z = (X - X.mean()) / X.std(ddof=0)
    A = np.column_stack([np.ones(len(Z)), Z.to_numpy(float)])
    b = np.zeros(A.shape[1])
    for _ in range(iterations):
        p = 1 / (1 + np.exp(-A @ b))
        H = A.T @ (A * (p * (1 - p))[:, None])
        step = np.linalg.solve(H, A.T @ (y - p))
        b += step
        if np.abs(step).max() < 1e-12:
            break
    p = 1 / (1 + np.exp(-A @ b))
    H = A.T @ (A * (p * (1 - p))[:, None])
    se = np.sqrt(np.diag(np.linalg.inv(H)))
    pv = [math.erfc(abs(v) / math.sqrt(2)) for v in b / se]
    pos, neg = p[y == 1], p[y == 0]
    auc = float(np.mean([(a > c) + 0.5 * (a == c) for a in pos for c in neg])) if len(pos) and len(neg) else float("nan")
    return {"coef": dict(zip(X.columns, b[1:])), "p": dict(zip(X.columns, pv[1:])),
            "odds_ratio": {c: math.exp(v) for c, v in zip(X.columns, b[1:])}, "intercept": float(b[0]),
            "auc": auc, "n": len(y)}


# ------------------------------------------------------ positional production

def weekly_position_points(lineups: pd.DataFrame, positions: list[str]) -> pd.DataFrame:
    """(manager_key, season, week) x position: started points, 0 where the
    manager started no one at that position."""
    s = lineups[lineups["started"].astype(bool)]
    wk = s.groupby(["manager_key", "season", "week", "position"])["points"].sum().unstack("position")
    return wk.reindex(columns=positions).fillna(0.0)


def position_fit(weekly: pd.DataFrame, win_pct: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """weekly: from weekly_position_points; win_pct: (season, manager_key,
    win_pct) regular season. Returns the career table and the season model."""
    positions = list(weekly.columns)
    by = weekly.groupby("manager_key")
    career = pd.concat({"avg": by.mean(), "sd": by.std()}, axis=1)
    career.columns = [f"{p}_{stat}" for stat, p in career.columns]
    season = weekly.groupby(["manager_key", "season"]).mean().reset_index()
    df = season.merge(win_pct, on=["season", "manager_key"]).dropna()
    fit = ols(df["win_pct"].to_numpy(float), df[positions])
    coef = pd.DataFrame({"position": positions, "coef": [fit["coef"][p] for p in positions],
                         "std_coef": [fit["std_coef"][p] for p in positions], "p_value": [fit["p"][p] for p in positions],
                         "corr": [df[p].corr(df["win_pct"]) for p in positions]})
    summary = pd.DataFrame([{"n": fit["n"], "r2": fit["r2"]}])
    return {"career": career.reset_index(), "season": df, "coefficients": coef, "summary": summary}


def regular_win_pct(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    g = counted_games(tables)
    g = g[~g["is_playoff_week"]]
    pts = g["result"].map({"W": 1.0, "T": 0.5}).fillna(0.0)
    return pts.groupby([g["season"], g["manager_key"]]).agg(["mean", "size"]).reset_index().rename(
        columns={"mean": "win_pct", "size": "games"})


def _drop_weeks(df: pd.DataFrame, weeks: set) -> pd.DataFrame:
    keep = [(int(s), int(w), m) not in weeks for s, w, m in zip(df["season"], df["week"], df["manager_key"])]
    return df[np.array(keep, dtype=bool)]


def position_production(tables: dict[str, pd.DataFrame], exclude_managers: set[str] = frozenset(),
                        ppg_exclusions: set[tuple[int, int, str]] = frozenset(),
                        legacy_mode: bool = False, fixes=None) -> dict[str, pd.DataFrame]:
    fx = _fixes(legacy_mode, fixes)
    lu = game_lineups(tables)
    lu = lu[~lu["season"].isin(live_seasons(tables))]
    if "include_excluded" not in fx:
        lu = lu[~lu["manager_key"].isin(exclude_managers)]
    if "ppg_exclusions" in fx and ppg_exclusions:
        lu = _drop_weeks(lu, ppg_exclusions)
    present = set(lu.loc[lu["started"].astype(bool), "position"])
    positions = [p for p in POSITION_ORDER if p in present] + sorted(present - set(POSITION_ORDER))
    weekly = weekly_position_points(lu, positions)
    wp = regular_win_pct(tables)
    res = position_fit(weekly, wp[["season", "manager_key", "win_pct"]])
    games = counted_games(tables)
    games = games[~games["is_playoff_week"] & ~games["season"].isin(live_seasons(tables))]
    career_wp = games["result"].map({"W": 1.0, "T": 0.5}).fillna(0.0).groupby(games["manager_key"]).mean()
    career = res["career"]
    career["win_pct"] = career["manager_key"].map(career_wp)
    career["hidden"] = career["manager_key"].isin(exclude_managers)
    return {"position_career": career, "position_coefficients": res["coefficients"],
            "position_fit": res["summary"]}


# ---------------------------------------------------------- quarterly model

def quarter_averages(scores: pd.DataFrame, quarters: list[tuple[int, int]]) -> pd.DataFrame:
    """scores: season, manager_key, week, points (regular season). Returns
    one row per manager-season with Q1..Qn averages (missing if no games)."""
    out = scores[["season", "manager_key"]].drop_duplicates().set_index(["season", "manager_key"])
    for i, (lo, hi) in enumerate(quarters, start=1):
        q = scores[scores["week"].between(lo, hi)]
        out[f"Q{i}"] = q.groupby(["season", "manager_key"])["points"].mean()
    return out.reset_index()


QUARTER_COLUMNS = ["quarter", "weeks", "coef", "p_value", "odds_ratio", "corr"]


def no_quarter_model(reason: str) -> dict[str, pd.DataFrame]:
    """The quarterly model's tables when a league's data cannot fit it (empty), and why."""
    import warnings
    warnings.warn(f"quarterly playoff model not fitted: {reason}", stacklevel=2)
    return {"quarterly_coefficients": pd.DataFrame(columns=QUARTER_COLUMNS),
            "quarterly_fit": pd.DataFrame(columns=["n", "auc"])}


def _quarter_model(q: pd.DataFrame, labels: list[str]) -> dict[str, pd.DataFrame]:
    """Generic leagues: a league where every manager makes the playoffs (or none miss in the data) has
    nothing to predict, and a tiny one can separate the outcome perfectly so the fit never converges;
    both give empty tables instead of stopping the build (the page hides the section)."""
    cols = [c for c in q.columns if c.startswith("Q")]
    made = q["made"].astype(float)
    if made.nunique() < 2:
        return no_quarter_model("every manager-season has the same playoff outcome")
    try:
        with np.errstate(all="ignore"):
            fit = logit(made.to_numpy(), q[cols])
    except np.linalg.LinAlgError:
        return no_quarter_model("the fit does not converge (the quarters separate the outcome perfectly)")
    if not all(np.isfinite(v) for v in list(fit["coef"].values()) + list(fit["p"].values())):
        return no_quarter_model("the fit does not converge (non-finite coefficients)")
    coef = pd.DataFrame({"quarter": cols, "weeks": labels, "coef": [fit["coef"][c] for c in cols],
                         "p_value": [fit["p"][c] for c in cols], "odds_ratio": [fit["odds_ratio"][c] for c in cols],
                         "corr": [q[c].corr(q["made"].astype(float)) for c in cols]})
    return {"quarterly_coefficients": coef, "quarterly_fit": pd.DataFrame([{"n": fit["n"], "auc": fit["auc"]}])}


def quarterly_fit(scores: pd.DataFrame, playoffs: pd.DataFrame, quarters: list[tuple[int, int]]) -> dict:
    """scores: season, manager_key, week, points (regular season);
    playoffs: season, manager_key, made (0/1). One set of quarters."""
    q = quarter_averages(scores, quarters).merge(playoffs, on=["season", "manager_key"]).dropna()
    return _quarter_model(q, [f"{lo}-{hi}" for lo, hi in quarters])


def quarters_for(regular_weeks: int, to_season_end: bool) -> list[tuple[int, int]]:
    return LEGACY_QUARTERS[:3] + [(10, regular_weeks if to_season_end else 13)]


def league_field(tables: dict[str, pd.DataFrame], cutoff: int | None) -> pd.DataFrame:
    """(season, manager_key, made): in the league's playoff field by the
    regular-season standings (position_impact.playoff_qualifier), finished
    seasons only."""
    from engine.analytics.position_impact import playoff_qualifier

    g = counted_games(tables)
    g = g[~g["is_playoff_week"] & ~g["season"].isin(live_seasons(tables))]
    qualify = playoff_qualifier(tables, cutoff)
    rows = []
    for season, sg in g.groupby("season"):
        st = sg.groupby("manager_key").agg(wins=("result", lambda r: int((r == "W").sum())),
                                           games=("result", "size"), points=("points", "sum")).reset_index()
        field = set(qualify(int(season), st))
        rows += [{"season": int(season), "manager_key": m, "made": int(m in field)} for m in st["manager_key"]]
    return pd.DataFrame(rows, columns=["season", "manager_key", "made"])


def quarterly_model(tables: dict[str, pd.DataFrame], manager_seasons: pd.DataFrame,
                    exclude_managers: set[str] = frozenset(),
                    ppg_exclusions: set[tuple[int, int, str]] = frozenset(),
                    legacy_mode: bool = False, fixes=None, cutoff: int | None = None) -> dict[str, pd.DataFrame]:
    fx = _fixes(legacy_mode, fixes)
    g = counted_games(tables)
    g = g[~g["is_playoff_week"] & ~g["season"].isin(live_seasons(tables))]
    if "include_excluded" not in fx:
        g = g[~g["manager_key"].isin(exclude_managers)]
    if "ppg_exclusions" in fx and ppg_exclusions:
        g = _drop_weeks(g, ppg_exclusions)
    reg = dict(zip(tables["seasons"]["season"], tables["seasons"]["regular_season_periods"]))
    if "league_field" in fx:
        playoffs = league_field(tables, cutoff)
    else:
        ms = manager_seasons.dropna(subset=["made_playoffs"])
        playoffs = pd.DataFrame({"season": ms["season"], "manager_key": ms["manager_key"],
                                 "made": ms["made_playoffs"].astype(bool).astype(int)})
    parts = []
    # the last quarter's length follows each season's length; the columns are shared
    for season, sg in g.groupby("season"):
        qs = quarters_for(int(reg[season]), "q4_to_season_end" in fx)
        qa = quarter_averages(sg[["season", "manager_key", "week", "points"]], qs)
        parts.append(qa)
    q = pd.concat(parts).merge(playoffs, on=["season", "manager_key"]).dropna()
    labels = [f"{lo}-{hi}" for lo, hi in LEGACY_QUARTERS[:3]] + (["10-end"] if "q4_to_season_end" in fx else ["10-13"])
    return _quarter_model(q, labels)


def analyze_regressions(tables: dict[str, pd.DataFrame], manager_seasons: pd.DataFrame,
                        exclude_managers: set[str] = frozenset(),
                        ppg_exclusions: set[tuple[int, int, str]] = frozenset(),
                        cutoff: int | None = None) -> dict[str, pd.DataFrame]:
    return {**position_production(tables, exclude_managers, ppg_exclusions),
            **quarterly_model(tables, manager_seasons, exclude_managers, ppg_exclusions, cutoff=cutoff)}

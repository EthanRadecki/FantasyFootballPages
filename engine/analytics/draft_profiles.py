"""Draft profiles: how each manager drafts, season by season and over a career.

Replaces the legacy draft_fingerprint.py (this module) and, in the next step,
the lost builder behind draft-fingerprints.html and generate_fingerprints.py.
generate_archetypes.py is retired (it fed no page; Ethan, session 5).

Every pick counts, all positions, every manager (excluded managers are only
hidden). Per manager and season, from the first picks by overall pick:

    early_rb_pct, early_wr_pct   share of the first 3 picks at RB, at WR
    rb_wr_balance                100 when those RB/WR picks split evenly, 0 when one-sided
    positional_diversity         distinct positions in the first 6 picks, as % of the league's positions
    positional_concentration     Herfindahl of those 6, scaled 0 (spread) to 100 (one position)
    same_position_run_rate       % of consecutive pairs in the first 10 picks at the same position

Patience, for QB, TE, K, D/ST: the manager's first pick at the position,
scored as a percentile against every pick at that position that season, two
ways (overall pick, and position order = the player's ADP rank at his
position), combined 70/30 for QB and TE and 20/80 for K and D/ST (their picks
bunch up at the end of the draft, so position order carries the signal).
Higher = waited longer.

ADP (engine.normalize.adp), deviation = ADP - overall pick (positive = the
manager took the player before the market did, a reach):
    avg_adp_deviation, reach_tendency (mean positive deviation), value_hunting
    (size of the mean negative deviation), draft_conviction (mean absolute
    deviation), adp_independence (100 x (1 - correlation of ADP and pick)),
    and the mean deviation per position.

Career: the mean of the manager's finished seasons (not pooled picks), plus
draft_adaptability, the mean across ten strategy columns of their
season-to-season standard deviation.

A season needs only its draft: the live season is profiled as soon as the
draft is done, and career covers finished seasons.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.analytics.weeks import live_seasons
from engine.normalize.adp import position_order

POSITION_ORDER = ["RB", "WR", "QB", "TE", "K", "D/ST"]   # column order; a league's positions are taken from its drafts
PATIENCE_POSITIONS = ["QB", "TE", "K", "D/ST"]
PATIENCE_WEIGHTS = {"QB": (0.70, 0.30), "TE": (0.70, 0.30), "K": (0.20, 0.80), "D/ST": (0.20, 0.80)}
EARLY_PICKS = 3
DIVERSITY_PICKS = 6
RUN_PICKS = 10

STRATEGY_COLUMNS = ["early_rb_pct", "early_wr_pct", "qb_patience", "te_patience", "k_patience", "dst_patience",
                    "rb_wr_balance", "positional_diversity", "positional_concentration", "same_position_run_rate"]

# Legacy mode: engine picks keep ESPN's own numbering, profiles cover finished seasons only.
ENGINE_CHANGES = {
    "engine_pick_numbering": True,    # picks numbered after the draft-order correction, as analytics/draft.py
    "live_season": True,              # profile the live season once its draft is done
}


def slug(position: str) -> str:
    return "dst" if position == "D/ST" else position.lower()


def draft_positions(picks: pd.DataFrame) -> list[str]:
    """The league's draftable positions, in column order."""
    seen = set(picks["position"].dropna())
    return [p for p in POSITION_ORDER if p in seen] + sorted(seen - set(POSITION_ORDER))


def picks_with_adp(tables: dict[str, pd.DataFrame], seasons: list[int], espn_numbering: bool) -> pd.DataFrame:
    """Every pick in `seasons`: manager, position that season, ADP and position order."""
    dp = tables["draft_picks"].copy()
    if espn_numbering and "espn_overall_pick" in dp:
        dp["overall_pick"] = dp["espn_overall_pick"].fillna(dp["overall_pick"]).astype(int)
    dp = dp[dp["season"].isin(seasons)]
    pos = tables["player_seasons"][["season", "player_id", "position"]]
    out = dp.merge(pos, on=["season", "player_id"], how="left")

    adp = tables.get("adp")
    if adp is not None and len(adp):
        a = adp.copy()
        a["position_order"] = position_order(a)
        a = a.dropna(subset=["player_id"]).drop_duplicates(["season", "player_id"])
        a["player_id"] = a["player_id"].astype(int)
        out = out.merge(a[["season", "player_id", "adp", "position_order"]], on=["season", "player_id"], how="left")
    else:
        out["adp"] = np.nan
        out["position_order"] = np.nan
    out["adp_deviation"] = out["adp"] - out["overall_pick"]
    return out.sort_values(["season", "overall_pick"]).reset_index(drop=True)


def percentile_score(value, series: pd.Series) -> float:
    """0-100 percentile of value within series (average rank for ties)."""
    s = pd.Series(series).dropna()
    if len(s) < 2 or pd.isna(value):
        return np.nan
    return s.rank(pct=True).loc[s.index[s == value]].mean() * 100


def patience(manager_picks: pd.DataFrame, season_picks: pd.DataFrame, position: str) -> dict:
    p = slug(position)
    mine = manager_picks[manager_picks["position"] == position]
    if mine.empty:
        return {f"{p}_patience": np.nan, f"first_{p}_pick": np.nan, f"first_{p}_round": np.nan,
                f"first_{p}_order": np.nan}
    first = mine.sort_values("overall_pick").iloc[0]
    pool = season_picks[season_picks["position"] == position]
    scores = [percentile_score(first["overall_pick"], pool["overall_pick"]),
              percentile_score(first["position_order"], pool["position_order"])]
    valid = [(s, w) for s, w in zip(scores, PATIENCE_WEIGHTS.get(position, (0.5, 0.5))) if not pd.isna(s)]
    composite = sum(s * w for s, w in valid) / sum(w for _, w in valid) if valid else np.nan
    return {f"{p}_patience": composite, f"first_{p}_pick": first["overall_pick"],
            f"first_{p}_round": first["round"], f"first_{p}_order": first["position_order"]}


def season_profile(df: pd.DataFrame, season_picks: pd.DataFrame, positions: list[str]) -> dict:
    df = df.sort_values("overall_pick")
    out: dict = {}
    first = df.head(EARLY_PICKS)
    out["early_rb_pct"] = (first["position"] == "RB").mean() * 100
    out["early_wr_pct"] = (first["position"] == "WR").mean() * 100
    rbwr = first[first["position"].isin(["RB", "WR"])]
    out["rb_wr_balance"] = np.nan if rbwr.empty else (1 - abs(rbwr["position"].eq("RB").mean() - 0.5) / 0.5) * 100

    six = df.head(DIVERSITY_PICKS)
    out["positional_diversity"] = six["position"].nunique() / len(positions) * 100
    hhi = (six["position"].value_counts(normalize=True) ** 2).sum()
    min_hhi = 1 / len(positions)
    out["positional_concentration"] = (hhi - min_hhi) / (1 - min_hhi) * 100

    run = df.head(RUN_PICKS)["position"].tolist()
    out["same_position_run_rate"] = (np.mean([run[i] == run[i - 1] for i in range(1, len(run))]) * 100
                                     if len(run) > 1 else np.nan)

    for pos in PATIENCE_POSITIONS:
        out.update(patience(df, season_picks, pos))

    a = df.dropna(subset=["adp_deviation"])
    if len(a):
        dev = a["adp_deviation"]
        out["avg_adp_deviation"] = dev.mean()
        out["reach_tendency"] = dev[dev > 0].mean() if (dev > 0).any() else 0
        out["value_hunting"] = abs(dev[dev < 0].mean()) if (dev < 0).any() else 0
        out["draft_conviction"] = dev.abs().mean()
        out["adp_independence"] = ((1 - a[["adp", "overall_pick"]].corr().iloc[0, 1]) * 100
                                   if a["adp"].nunique() > 1 and a["overall_pick"].nunique() > 1 else np.nan)
    else:
        for c in ("avg_adp_deviation", "reach_tendency", "value_hunting", "draft_conviction", "adp_independence"):
            out[c] = np.nan
    for pos in positions:
        d = a.loc[a["position"] == pos, "adp_deviation"]
        out[f"{slug(pos)}_adp_deviation"] = d.mean() if len(d) else np.nan
    return out


def fingerprints(tables: dict[str, pd.DataFrame], exclude: set[str] = frozenset(),
                 legacy_mode: bool = False, changes: dict | None = None,
                 live: set[int] | None = None) -> dict[str, pd.DataFrame]:
    """draft_fingerprint_seasons (manager x season) and draft_fingerprint_career.
    live: the live seasons (default: from the matchups)."""
    ch = {k: (False if legacy_mode else v) for k, v in ENGINE_CHANGES.items()}
    ch.update(changes or {})
    live = set(live_seasons(tables)) if live is None else set(live)
    drafted = sorted(int(s) for s in tables["draft_picks"]["season"].unique())
    seasons = [s for s in drafted if ch["live_season"] or s not in live]

    picks = picks_with_adp(tables, seasons, espn_numbering=not ch["engine_pick_numbering"])
    positions = draft_positions(picks)
    rows = []
    for (season, mgr), df in picks.groupby(["season", "manager_key"]):
        rows.append({"season": int(season), "manager_key": mgr,
                     **season_profile(df, picks[picks["season"] == season], positions)})
    seasons_df = pd.DataFrame(rows)
    metrics = [c for c in seasons_df.columns if c not in ("season", "manager_key")]
    seasons_df["live"] = seasons_df["season"].isin(live)
    seasons_df["hidden"] = seasons_df["manager_key"].isin(exclude)

    done = seasons_df[~seasons_df["live"]]
    career = done.groupby("manager_key")[metrics].mean()
    strategy = [c for c in STRATEGY_COLUMNS if c in done]
    career["draft_adaptability"] = done.groupby("manager_key")[strategy].std().mean(axis=1)
    career["n_seasons"] = done.groupby("manager_key").size()
    career = career.reset_index()
    career["hidden"] = career["manager_key"].isin(exclude)
    return {"draft_fingerprint_seasons": seasons_df, "draft_fingerprint_career": career}


def analyze_draft_profiles(tables: dict[str, pd.DataFrame], exclude: set[str] = frozenset(),
                           legacy_mode: bool = False) -> dict[str, pd.DataFrame]:
    return fingerprints(tables, exclude, legacy_mode)

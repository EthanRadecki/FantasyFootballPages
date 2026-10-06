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
    "surplus_weighted": True,         # surplus per pick = sum(surplus_wtd) / sum(weight), career pooled
                                      # (legacy: plain mean of surplus_wtd, career = mean of season means)
    "career_outcomes_unrounded": True,  # career win% and PPG from unrounded seasons (legacy rounded first)
    "stable_cluster_ids": True,       # archetype ids by size (largest 0), ties by lower draft conviction;
                                      # k-means' own numbering changes whenever the fit is rerun
}

# ---- archetypes and the draft-fingerprints page (the lost page builder, recovered from the page)
RADAR = ["early_rb_pct", "early_wr_pct", "rb_wr_balance", "positional_diversity", "same_position_run_rate",
         "draft_conviction", "qb_patience", "te_patience", "k_patience", "dst_patience"]
ADP_SUMMARY = ["avg_adp_deviation", "reach_tendency", "value_hunting", "adp_independence"]
FILL_POSITIONS = ["K", "D/ST"]      # late picks often fall outside the ADP list
MIN_FILL_ROWS = 10                  # observed rows needed to fit the fill-in; fewer: the observed mean
ARCHETYPE_K = 4
PCA_COMPONENTS = 10
MIN_CLUSTER_ROWS = 30               # fewer finished manager-seasons: no archetypes
MIN_FEATURE_COVERAGE = 0.9          # share of finished drafts that must have a clustering feature
SEED = 42
BOOTSTRAP_RUNS = 100


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


# ---------------------------------------------------------------- page layer

def round_half_up(values, digits: int):
    """Round halves up (0.125 -> 0.13), as the page's numbers were; Python's
    round() goes to the nearest float, which turns 141.415 into 141.41."""
    f = 10 ** digits
    return np.floor(np.asarray(values, dtype=float) * f + 0.5 + 1e-9) / f


def features(columns) -> list[str]:
    """Clustering features: the radar, deviation by position, and the ADP summary."""
    pos = [c for c in columns if c.endswith("_adp_deviation") and c != "avg_adp_deviation"]
    return [c for c in RADAR + pos + ADP_SUMMARY if c in columns]


def fill_adp_deviation(seasons: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """K and D/ST ADP deviation, where missing, from a straight-line fit on that
    position's patience over the finished seasons that have both, clipped to
    the observed range. Fewer than MIN_FILL_ROWS observed: the observed mean.
    None observed: left blank. Returns the table and one note per position."""
    out, notes = seasons.copy(), []
    for pos in FILL_POSITIONS:
        y, x = f"{slug(pos)}_adp_deviation", f"{slug(pos)}_patience"
        if y not in out or x not in out:
            continue
        out[f"{y}_filled"] = False
        missing = out[y].isna()
        if not missing.any():
            continue
        fit = out[~out["live"] & out[y].notna() & out[x].notna()]
        if fit.empty:
            notes.append(f"{pos}: no observed ADP deviation, {int(missing.sum())} left blank")
            continue
        lo, hi = fit[y].min(), fit[y].max()
        if len(fit) >= MIN_FILL_ROWS and fit[x].nunique() > 1:
            b, a = np.polyfit(fit[x], fit[y], 1)
            r = np.corrcoef(fit[x], fit[y])[0, 1]
            filled = (a + b * out.loc[missing, x]).clip(lo, hi)
            filled = filled.fillna(fit[y].mean())
            notes.append(f"{pos}: {int(missing.sum())} filled from {x} (r = {r:.2f}, {len(fit)} rows)")
        else:
            filled = pd.Series(fit[y].mean(), index=out.index[missing])
            notes.append(f"{pos}: {int(missing.sum())} filled with the mean ({len(fit)} rows, too few to fit)")
        out.loc[missing, y] = filled
        out.loc[missing, f"{y}_filled"] = True
    return out, notes


def minmax(values: pd.Series) -> pd.Series:
    """0-100 within the group; 50 when every value is the same."""
    lo, hi = values.min(), values.max()
    return pd.Series(50.0, index=values.index) if hi == lo else (values - lo) / (hi - lo) * 100


def normalize(frame: pd.DataFrame, by: str | None) -> pd.DataFrame:
    """norm_<radar dim> per period (season), or across all rows (career)."""
    out = frame.copy()
    for d in [c for c in RADAR if c in out]:
        out[f"norm_{d}"] = out.groupby(by)[d].transform(minmax) if by else minmax(out[d])
    return out


def surplus_per_pick(surplus: pd.DataFrame, weighted: bool, by: list[str]) -> pd.Series:
    """Surplus per pick: sum(surplus_wtd) / sum(weight), or the legacy plain mean of surplus_wtd."""
    g = surplus.groupby(by)
    return g["surplus_wtd"].sum() / g["weight"].sum() if weighted else g["surplus_wtd"].mean()


def archetypes(seasons: pd.DataFrame, feats: list[str]) -> dict:
    """k-means on standardized features reduced by PCA, fit on finished seasons,
    live seasons assigned to the nearest cluster. None when too few rows."""
    done = seasons[~seasons["live"]]
    # a feature counts when most finished drafts have it (a position the league's lineups dropped, or
    # never had, leaves its patience and ADP deviation blank for whole seasons); a draft missing a kept
    # feature takes the most patient value for a patience (it never drafted that position) or the
    # finished drafts' median otherwise. Preach has no gaps, so this changes nothing there.
    feats = [f for f in feats if len(done) and done[f].notna().mean() >= MIN_FEATURE_COVERAGE]
    seasons = seasons.copy()
    for f in feats:
        seasons[f] = seasons[f].fillna(100.0 if f.endswith("_patience") else done[f].median())
    fit = seasons[~seasons["live"]].dropna(subset=feats)
    if len(fit) < MIN_CLUSTER_ROWS or len(feats) < 2:
        return {}
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(fit[feats])
    X = scaler.transform(fit[feats])
    pca = PCA(min(PCA_COMPONENTS, len(feats), len(fit) - 1), random_state=SEED).fit(X)
    Z = pca.transform(X)
    km = KMeans(ARCHETYPE_K, n_init=50, random_state=SEED).fit(Z)
    rows = seasons.dropna(subset=feats)
    labels = pd.Series(km.predict(pca.transform(scaler.transform(rows[feats]))), index=rows.index)
    raw = KMeans(ARCHETYPE_K, n_init=50, random_state=SEED).fit(X)
    return {"labels": labels, "fit_index": fit.index, "Z": Z, "X": X, "km": km, "pca": pca, "scaler": scaler,
            "feats": feats, "filled": rows[feats],
            "silhouette_pca": silhouette_score(Z, km.labels_), "silhouette_raw": silhouette_score(X, raw.labels_)}


def stability(model: dict) -> dict:
    """Seeded checks on the clustering: a 3-group Gaussian mixture's silhouette,
    and how well k-means on bootstrap resamples agrees with the fit (ARI)."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import adjusted_rand_score, silhouette_score
    from sklearn.mixture import GaussianMixture

    Z, labels = model["Z"], model["km"].labels_
    gmm = GaussianMixture(3, random_state=SEED).fit(Z).predict(Z)
    rng = np.random.RandomState(SEED)
    aris = []
    for _ in range(BOOTSTRAP_RUNS):
        idx = rng.choice(len(Z), len(Z), replace=True)
        boot = KMeans(ARCHETYPE_K, n_init=10, random_state=SEED).fit(Z[idx])
        aris.append(adjusted_rand_score(labels[idx], boot.labels_))
    return {"silhouette_k3_gmm": silhouette_score(Z, gmm) if len(set(gmm)) > 1 else np.nan,
            "bootstrap_mean_ari": float(np.mean(aris)), "bootstrap_std_ari": float(np.std(aris)),
            "bootstrap_p5": float(np.percentile(aris, 5)), "bootstrap_p95": float(np.percentile(aris, 95))}


def profiles(fp: dict[str, pd.DataFrame], outcomes: pd.DataFrame, surplus: pd.DataFrame, names: dict[str, str],
             legacy_mode: bool = False, changes: dict | None = None, with_stability: bool = True) -> dict[str, pd.DataFrame]:
    """The draft-fingerprints page tables from fingerprints().

    outcomes: season, manager_key, win_pct, ppg (finished seasons).
    surplus: season, manager_key, surplus_wtd, weight (one row per pick).
    names: manager_key -> display name; rows are ordered by season and name,
    which fixes k-means' starting points (the page was built in that order)."""
    from scipy.stats import kruskal

    ch = {k: (False if legacy_mode else v) for k, v in ENGINE_CHANGES.items()}
    ch.update(changes or {})
    s = fp["draft_fingerprint_seasons"].copy()
    s["name"] = s["manager_key"].map(names).fillna(s["manager_key"])
    s = s.sort_values(["season", "name"], kind="stable").reset_index(drop=True)
    s, fill_notes = fill_adp_deviation(s)

    sur = surplus_per_pick(surplus, ch["surplus_weighted"], ["season", "manager_key"]).rename("surplus")
    out = outcomes[["season", "manager_key", "win_pct", "ppg"]]
    s = s.merge(out, on=["season", "manager_key"], how="left").merge(
        sur.reset_index(), on=["season", "manager_key"], how="left")
    s = normalize(s, "season")

    model = archetypes(s, features(s.columns))
    s["cluster"] = model["labels"].reindex(s.index).astype("Int64") if model else pd.array([pd.NA] * len(s), "Int64")
    remap = {k: k for k in range(ARCHETYPE_K)}
    if model and ch["stable_cluster_ids"]:
        fit = s[~s["live"]].dropna(subset=["cluster"])
        order = (fit.groupby("cluster").agg(n=("cluster", "size"), conv=("draft_conviction", "mean"))
                 .sort_values(["n", "conv"], ascending=[False, True]).index)
        remap = {int(old): new for new, old in enumerate(order)}
        s["cluster"] = s["cluster"].map(remap).astype("Int64")
    matches = archetype_matches(s, model) if model else pd.DataFrame(columns=MATCH_COLUMNS)

    c = fp["draft_fingerprint_career"].copy()
    done = s[~s["live"]]
    if ch["career_outcomes_unrounded"]:
        car_out = done.groupby("manager_key")[["win_pct", "ppg"]].mean()
    else:
        car_out = done.assign(win_pct=round_half_up(done["win_pct"], 3), ppg=round_half_up(done["ppg"], 2)).groupby(
            "manager_key")[["win_pct", "ppg"]].mean()
    if ch["surplus_weighted"]:
        fin_sur = surplus[surplus["season"].isin(done["season"].unique())]
        car_sur = surplus_per_pick(fin_sur, True, ["manager_key"]).rename("surplus")
    else:
        car_sur = done.groupby("manager_key")["surplus"].mean()
    c = c.merge(car_out.reset_index(), on="manager_key", how="left").merge(
        car_sur.reset_index(), on="manager_key", how="left")
    c = normalize(c, None)

    arch = pd.DataFrame()
    stats: dict = {"k": ARCHETYPE_K if model else 0, "n_observations": int(len(done)),
                   "n_managers": int(done["manager_key"].nunique())}
    if model:
        clustered = done.dropna(subset=["cluster"])
        rows = []
        for cid, g in clustered.groupby("cluster"):
            rows.append({"cluster": int(cid), "n": int(len(g)), **{f"center_{d}": g[d].mean() for d in RADAR if d in g},
                         "win_pct": g["win_pct"].mean(), "ppg": g["ppg"].mean(), "surplus": g["surplus"].mean()})
        arch = pd.DataFrame(rows)
        groups = [g.dropna() for _, g in clustered.groupby("cluster")["win_pct"]]
        ppg = [g.dropna() for _, g in clustered.groupby("cluster")["ppg"]]
        stats.update({
            "n_multi_cluster": int((clustered.groupby("manager_key")["cluster"].nunique() > 1).sum()),
            "win_pct_p": kruskal(*groups).pvalue if all(len(g) for g in groups) else np.nan,
            "ppg_p": kruskal(*ppg).pvalue if all(len(g) for g in ppg) else np.nan,
            "silhouette_pca": model["silhouette_pca"], "silhouette_raw": model["silhouette_raw"],
            "pca_components": int(model["pca"].n_components_),
            "pca_variance": float(model["pca"].explained_variance_ratio_.sum()),
        })
        if with_stability:
            stats.update(stability(model))
    stats["fill_notes"] = "; ".join(fill_notes)
    return {"draft_profile_seasons": s.drop(columns="name"), "draft_profile_career": c,
            "draft_archetypes": arch, "draft_archetype_stats": pd.DataFrame([stats]),
            "draft_archetype_matches": matches}


MATCH_COLUMNS = ["season", "manager_key", "cluster", "dist_to_nearest", "margin_over_2nd", "rank",
                 "comp_season", "comp_manager_key", "comp_cluster", "comp_dist"]
MATCH_COMPARISONS = 3


def archetype_matches(s: pd.DataFrame, model: dict) -> pd.DataFrame:
    """Each live-season draft against the archetype model, in the space k-means
    was fit in (standardized features, PCA): the distance to its own cluster's
    center, how much nearer that center is than the next one (margin_over_2nd,
    how clearly the draft belongs to its archetype), and the finished
    manager-seasons nearest to it (comparisons, nearest first). One row per
    live draft and comparison."""
    feats = model["feats"]
    live = s[s["live"]].dropna(subset=["cluster"])
    live = live[live.index.isin(model["filled"].index)]
    done = s.loc[model["fit_index"]]
    if not len(live):
        return pd.DataFrame(columns=MATCH_COLUMNS)
    Zl = model["pca"].transform(model["scaler"].transform(model["filled"].loc[live.index, feats]))
    centers = model["km"].cluster_centers_
    rows = []
    for i, (_, r) in enumerate(live.iterrows()):
        dc = np.sqrt(((centers - Zl[i]) ** 2).sum(axis=1))
        near = np.sort(dc)
        d = np.sqrt(((model["Z"] - Zl[i]) ** 2).sum(axis=1))
        for rank, j in enumerate(np.argsort(d, kind="stable")[:MATCH_COMPARISONS], start=1):
            c = done.iloc[j]
            rows.append({"season": int(r["season"]), "manager_key": r["manager_key"], "cluster": int(r["cluster"]),
                         "dist_to_nearest": float(near[0]),
                         "margin_over_2nd": float(near[1] - near[0]) if len(near) > 1 else np.nan,
                         "rank": rank, "comp_season": int(c["season"]), "comp_manager_key": c["manager_key"],
                         "comp_cluster": int(c["cluster"]), "comp_dist": float(d[j])})
    return pd.DataFrame(rows, columns=MATCH_COLUMNS)


def ranges(frame: pd.DataFrame, columns: list[str]) -> dict[str, list[float]]:
    """[min, max] of each column (the page's scales)."""
    return {c: [float(frame[c].min()), float(frame[c].max())] for c in columns if c in frame and frame[c].notna().any()}


def analyze_draft_profiles(tables: dict[str, pd.DataFrame], results: dict[str, pd.DataFrame],
                           exclude: set[str] = frozenset(), names: dict[str, str] | None = None,
                           legacy_mode: bool = False) -> dict[str, pd.DataFrame]:
    """Fingerprints and the page tables. Outcomes from manager_seasons, surplus
    from draft_surplus (both already in results)."""
    fp = fingerprints(tables, exclude, legacy_mode)
    ms = results["manager_seasons"]
    ms = ms[~ms["is_live"]] if "is_live" in ms else ms
    outcomes = ms.rename(columns={"pf_per_game": "ppg"})[["season", "manager_key", "win_pct", "ppg"]]
    ds = results["draft_surplus"]
    surplus = ds[["season", "manager_key", "surplus_wtd", "weight"]]
    return {**fp, **profiles(fp, outcomes, surplus, names or {}, legacy_mode)}

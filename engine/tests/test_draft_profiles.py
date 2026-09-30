from pathlib import Path

import numpy as np
import pandas as pd

from engine.analytics.draft_profiles import draft_positions, fingerprints, percentile_score
from engine.config import load_config
from engine.legacy import name_to_key, resolve_names
from engine.normalize.adp import build_adp

REPO = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).resolve().parent / "golden" / "draft"
CFG = load_config(REPO / "leagues" / "preach" / "league.yaml")


# ---------------------------------------------------------------- legacy golden (runs in CI)

def legacy_tables():
    """Canonical-shaped tables from draft_fingerprint.py's own draft file: one
    player id per season, name and position; ADP from the shipped library."""
    h = pd.read_csv(GOLDEN / "draft_history_with_adp.csv.gz")
    h["position"] = h["position"].replace({"DST": "D/ST"})
    ids = {k: i for i, k in enumerate(sorted(set(zip(h["season"], h["player_name"], h["position"]))))}
    h["player_id"] = [ids[k] for k in zip(h["season"], h["player_name"], h["position"])]
    h["manager_key"] = resolve_names(h["manager"], name_to_key(CFG))
    t = {"player_seasons": h[["season", "player_id", "player_name", "position"]].drop_duplicates(),
         "draft_picks": h[["season", "overall_pick", "round", "player_id", "manager_key"]]}
    t["adp"], _ = build_adp(t, {}, {"league": {"provider": "espn"}})
    return t


def compare(engine: pd.DataFrame, legacy: pd.DataFrame, keys: list[str]):
    legacy = legacy.assign(manager_key=resolve_names(legacy["manager"], name_to_key(CFG)))
    m = legacy.merge(engine, on=keys, suffixes=("_l", "_e"), how="outer", indicator=True)
    assert (m["_merge"] == "both").all()
    for c in legacy.columns:
        if c in keys or c == "manager":
            continue
        a, b = m[f"{c}_l"].astype(float), m[f"{c}_e"].astype(float)
        assert ((a - b).abs().le(1e-9) | (a.isna() & b.isna())).all(), c


def test_reproduces_draft_fingerprint_seasons_and_career():
    res = fingerprints(legacy_tables(), legacy_mode=True, live=set())
    compare(res["draft_fingerprint_seasons"], pd.read_csv(GOLDEN / "draft_fingerprint_manager_season.csv.gz"),
            ["season", "manager_key"])
    compare(res["draft_fingerprint_career"], pd.read_csv(GOLDEN / "draft_fingerprint_career.csv.gz"),
            ["manager_key"])


# ---------------------------------------------------------------- the metrics

POS = {"RB": "RB", "WR": "WR", "QB": "QB", "TE": "TE", "K": "K", "D": "D/ST"}


def draft(rows, season=2024):
    """rows: (manager, pick, position code, adp or None)."""
    picks = pd.DataFrame([{"season": season, "overall_pick": p, "round": (p - 1) // 2 + 1, "player_id": p,
                           "manager_key": m} for m, p, _, _ in rows])
    ps = pd.DataFrame([{"season": season, "player_id": p, "player_name": f"P{p}", "position": POS[c]}
                       for _, p, c, _ in rows])
    adp = pd.DataFrame([{"season": season, "source": "t", "rank": i, "player_name": f"P{p}", "pro_team": None,
                         "position": POS[c], "adp": a, "player_id": p}
                        for i, (_, p, c, a) in enumerate(rows) if a is not None])
    adp["player_id"] = adp["player_id"].astype("Int64")
    return {"draft_picks": picks, "player_seasons": ps, "adp": adp}


ROWS = [  # two managers alternating picks; A goes RB, RB, WR early and waits on QB
    ("A", 1, "RB", 2.0), ("B", 2, "WR", 1.0), ("A", 3, "RB", 5.0), ("B", 4, "QB", 9.0),
    ("A", 5, "WR", 3.0), ("B", 6, "RB", 4.0), ("A", 7, "QB", 6.0), ("B", 8, "TE", 12.0),
    ("A", 9, "TE", 7.0), ("B", 10, "K", None), ("A", 11, "K", None), ("B", 12, "D", 11.0),
    ("A", 13, "D", 10.0), ("B", 14, "WR", 8.0),
]


def season_row(res, mgr):
    s = res["draft_fingerprint_seasons"]
    return s[s["manager_key"] == mgr].iloc[0]


def test_draft_shape():
    a = season_row(fingerprints(draft(ROWS), live=set()), "A")
    assert np.isclose(a["early_rb_pct"], 100 * 2 / 3) and np.isclose(a["early_wr_pct"], 100 / 3)
    assert np.isclose(a["rb_wr_balance"], 100 * (1 - abs(2 / 3 - 0.5) / 0.5))
    assert np.isclose(a["positional_diversity"], 100 * 5 / 6)                  # RB RB WR QB TE K: 5 of 6 positions
    assert np.isclose(a["same_position_run_rate"], 100 / 6)                   # RB-RB, one of 6 pairs


def test_patience_waits_longer_scores_higher():
    res = fingerprints(draft(ROWS), live=set())
    a, b = season_row(res, "A"), season_row(res, "B")
    assert a["first_qb_pick"] == 7 and b["first_qb_pick"] == 4
    assert a["qb_patience"] > b["qb_patience"]
    assert percentile_score(7, pd.Series([4, 7])) == 100 and percentile_score(4, pd.Series([4, 7])) == 50


def test_adp_metrics_sign_and_missing_adp():
    a = season_row(fingerprints(draft(ROWS), live=set()), "A")
    dev = pd.Series([2 - 1, 5 - 3, 3 - 5, 6 - 7, 7 - 9, 10 - 13])      # ADP minus pick; K has none
    assert np.isclose(a["avg_adp_deviation"], dev.mean())
    assert np.isclose(a["reach_tendency"], dev[dev > 0].mean())
    assert np.isclose(a["value_hunting"], abs(dev[dev < 0].mean()))
    assert np.isclose(a["draft_conviction"], dev.abs().mean())
    assert np.isnan(a["k_adp_deviation"])


def test_season_without_adp_keeps_shape_and_blanks_adp_metrics():
    t = draft(ROWS)
    t["adp"] = t["adp"].iloc[0:0]
    a = season_row(fingerprints(t, live=set()), "A")
    assert a["early_rb_pct"] > 0 and np.isnan(a["draft_conviction"]) and np.isnan(a["rb_adp_deviation"])


def test_positions_come_from_the_league():
    no_kickers = [r for r in ROWS if r[2] != "K"]
    t = draft(no_kickers)
    assert draft_positions(t["draft_picks"].merge(t["player_seasons"])) == ["RB", "WR", "QB", "TE", "D/ST"]
    res = fingerprints(t, live=set())
    assert "k_adp_deviation" not in res["draft_fingerprint_seasons"]
    assert np.isnan(season_row(res, "A")["k_patience"])


def test_live_season_is_profiled_but_left_out_of_career_and_hidden_managers_flagged():
    t = draft(ROWS, 2024)
    t26 = draft(ROWS, 2025)
    t = {k: pd.concat([t[k], t26[k]], ignore_index=True) for k in t}
    res = fingerprints(t, exclude={"B"}, live={2025})
    s, c = res["draft_fingerprint_seasons"], res["draft_fingerprint_career"]
    assert sorted(s["season"].unique()) == [2024, 2025] and s.loc[s["season"] == 2025, "live"].all()
    assert c.set_index("manager_key")["n_seasons"].tolist() == [1, 1]
    assert c.set_index("manager_key").loc["B", "hidden"] and not c.set_index("manager_key").loc["A", "hidden"]
    legacy = fingerprints(t, live={2025}, legacy_mode=True)["draft_fingerprint_seasons"]
    assert sorted(legacy["season"].unique()) == [2024]


def test_adaptability_is_the_mean_season_to_season_sd():
    t = draft(ROWS, 2023)
    t2 = draft([(m, p, {"RB": "WR", "WR": "RB"}.get(c, c), a) for m, p, c, a in ROWS], 2024)
    t = {k: pd.concat([t[k], t2[k]], ignore_index=True) for k in t}
    res = fingerprints(t, live=set())
    s = res["draft_fingerprint_seasons"]
    cols = ["early_rb_pct", "early_wr_pct", "qb_patience", "te_patience", "k_patience", "dst_patience",
            "rb_wr_balance", "positional_diversity", "positional_concentration", "same_position_run_rate"]
    want = s[s["manager_key"] == "A"][cols].std().mean()
    got = res["draft_fingerprint_career"].set_index("manager_key").loc["A", "draft_adaptability"]
    assert np.isclose(got, want)


# ---------------------------------------------------------------- the page layer

import gzip
import json

from engine.analytics.draft_profiles import (MIN_CLUSTER_ROWS, fill_adp_deviation, minmax, profiles,
                                             round_half_up, surplus_per_pick)

PAGE = json.load(gzip.open(GOLDEN / "draft_fingerprints_page.json.gz", "rt", encoding="utf-8"))
NAMES = {m["id"]: m["name"] for m in CFG["managers"]}


def page_inputs():
    """Legacy fingerprints, the page's own win% and PPG, and draft_surplus_v2."""
    fp = fingerprints(legacy_tables(), legacy_mode=True, live=set())
    keys = name_to_key(CFG)
    out = pd.DataFrame([{"season": int(p), "manager_key": keys[n.lower()], "win_pct": e["all"]["Win_Pct"],
                         "ppg": e["all"]["PPG"]} for n, per in PAGE["FINGERPRINTS"].items()
                        for p, e in per.items() if p not in ("career", "2026")])
    v2 = pd.read_csv(GOLDEN / "draft_surplus_v2.csv.gz")
    v2["manager_key"] = resolve_names(v2["manager"], keys)
    return fp, out, v2


def test_reproduces_the_draft_fingerprints_page():
    fp, out, v2 = page_inputs()
    res = profiles(fp, out, v2, NAMES, legacy_mode=True, with_stability=False)
    s, keys = res["draft_profile_seasons"], name_to_key(CFG)
    assert len(s) == 85
    for r in s.itertuples():
        e = PAGE["FINGERPRINTS"][NAMES[r.manager_key]][str(r.season)]
        assert r.cluster == e["cluster"]
        for k, v in e["all"].items():
            got = {"Win_Pct": r.win_pct, "PPG": r.ppg, "avg_surplus_per_pick": r.surplus}.get(k, getattr(r, k, None))
            assert (pd.isna(got) and v is None) or abs(got - v) < 1e-9, (r.manager_key, r.season, k)
        for d, v in e["normalized"].items():
            assert abs(round(getattr(r, f"norm_{d}"), 1) - v) < 0.051, (r.season, d)
    arch = res["draft_archetypes"].set_index("cluster")
    for a in PAGE["ARCHETYPES"]["cluster_summary"]:
        g = arch.loc[a["id"]]
        assert g["n"] == a["n"]
        assert all(abs(round(g[f"center_{d}"], 2) - v) < 1e-9 for d, v in a["center"].items())
        assert abs(round(g["surplus"], 2) - a["outcomes"]["avg_surplus_per_pick"]) < 1e-9
    st = res["draft_archetype_stats"].iloc[0]
    want = PAGE["ARCHETYPES"]["stats"]
    assert round(st["win_pct_p"], 3) == want["win_pct_p"] and round(st["ppg_p"], 3) == want["ppg_p"]
    assert round(st["silhouette_pca"], 3) == want["silhouette_pca_k4"]
    assert round(st["silhouette_raw"], 3) == want["silhouette_raw_k4"]
    assert st["n_multi_cluster"] == PAGE["ARCHETYPES"]["n_multi_cluster"]
    c = res["draft_profile_career"].set_index("manager_key")
    for n, per in PAGE["FINGERPRINTS"].items():
        k = keys[n.lower()]
        sur = per["career"]["all"]["avg_surplus_per_pick"]
        assert (sur is None and pd.isna(c.loc[k, "surplus"])) or round(c.loc[k, "surplus"], 4) == sur


def test_engine_ids_are_stable_and_groups_unchanged():
    fp, out, v2 = page_inputs()
    leg = profiles(fp, out, v2, NAMES, legacy_mode=True, with_stability=False)["draft_profile_seasons"]
    eng = profiles(fp, out, v2, NAMES, with_stability=False)["draft_profile_seasons"]
    m = leg.merge(eng, on=["season", "manager_key"], suffixes=("_l", "_e"))
    assert pd.crosstab(m["cluster_l"], m["cluster_e"]).gt(0).sum(axis=1).eq(1).all()   # same groups
    sizes = eng.groupby("cluster").size()
    assert sizes.is_monotonic_decreasing and sizes.index.tolist() == [0, 1, 2, 3]


def frame(k_dev, k_pat, live=None):
    n = len(k_dev)
    return pd.DataFrame({"k_adp_deviation": k_dev, "k_patience": k_pat,
                         "live": live if live is not None else [False] * n})


def test_fill_in_fits_clips_and_falls_back():
    obs = list(np.linspace(-20, 20, 12))
    f, notes = fill_adp_deviation(frame(obs + [np.nan, np.nan], list(range(12)) + [100, -100]))
    assert f["k_adp_deviation"].iloc[-2] == 20 and f["k_adp_deviation"].iloc[-1] == -20   # clipped to observed
    assert f["k_adp_deviation_filled"].tolist() == [False] * 12 + [True, True] and "filled from" in notes[0]
    f, notes = fill_adp_deviation(frame([1.0, 3.0, np.nan], [1, 2, 3]))
    assert f["k_adp_deviation"].iloc[-1] == 2.0 and "mean" in notes[0]                     # too few to fit
    f, notes = fill_adp_deviation(frame([np.nan, np.nan], [1, 2]))
    assert f["k_adp_deviation"].isna().all() and "left blank" in notes[0]


def test_small_league_gets_no_archetypes():
    fp = fingerprints(draft(ROWS), live=set())
    out = pd.DataFrame({"season": [2024, 2024], "manager_key": ["A", "B"], "win_pct": [0.5, 0.5], "ppg": [100, 110]})
    sur = pd.DataFrame({"season": [2024] * 2, "manager_key": ["A", "B"], "surplus_wtd": [1.0, -1.0], "weight": [1.0, 1.0]})
    res = profiles(fp, out, sur, {"A": "A", "B": "B"})
    assert len(res["draft_profile_seasons"]) == 2 < MIN_CLUSTER_ROWS
    assert res["draft_profile_seasons"]["cluster"].isna().all() and res["draft_archetypes"].empty
    assert res["draft_archetype_stats"].iloc[0]["k"] == 0


def test_helpers():
    assert minmax(pd.Series([3.0, 3.0])).tolist() == [50.0, 50.0]
    assert minmax(pd.Series([0.0, 5.0, 10.0])).tolist() == [0.0, 50.0, 100.0]
    assert round_half_up([141.415, 89.275, 0.1234], 2).tolist() == [141.42, 89.28, 0.12]
    sur = pd.DataFrame({"k": ["a", "a"], "surplus_wtd": [1.0, 0.55], "weight": [1.0, 0.55]})
    assert surplus_per_pick(sur, True, ["k"])["a"] == 1.0
    assert surplus_per_pick(sur, False, ["k"])["a"] == 0.775

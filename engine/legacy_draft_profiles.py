"""Compare draft profiles with the legacy draft_fingerprint.py outputs and the
draft-fingerprints.html page.

Golden files (engine/tests/golden/draft/):
    draft_fingerprint_manager_season.csv.gz   per manager and season, 2020-2025
    draft_fingerprint_career.csv.gz           per manager, with draft_adaptability
    draft_fingerprints_page.json.gz           the page's inline data (its builder is lost)

The page checks feed the legacy inputs: fingerprints in legacy mode (with the
live season, which the page shows), win% and PPG from manager_seasons (checked
against the stats file elsewhere), and surplus from draft_surplus_v2.csv.
Known differences, by pattern:
- 2026: the page used an ADP copy that no longer exists (decision 0004), so
  every 2026 value that depends on ADP, and the 2026 clusters, are excused;
  the rest of 2026 is compared.
- the Gaussian-mixture and bootstrap figures depend on random draws the
  builder did not record; the engine's seeded values are listed as INFO.
- career win% and PPG within half a unit of a rounding tie (float noise in
  the builder's mean, e.g. 108.275 shown as 108.28, 110.145 as 110.14).

Legacy mode (ESPN's pick numbering, finished seasons only) must match every
number. The ADP it reads is the canonical adp table, which normalize already
checks pick by pick against draft_history_with_adp.csv. Engine changes are
listed as INFO lines, each alone and then together.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.analytics import draft_profiles as dp_mod
from engine.analytics.draft_profiles import RADAR, round_half_up
from engine.config import excluded_manager_keys
from engine.legacy import Comparison, compare, name_to_key, resolve_names

NAN = -999999.0
KEYS_SEASON = ["season", "manager_key"]


def _metrics(frame: pd.DataFrame, keys: list[str]) -> list[str]:
    return [c for c in frame.columns if c not in keys + ["manager", "live", "hidden", "n_seasons"]]


def _num(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        out[c] = pd.to_numeric(out[c], errors="coerce").astype(float).fillna(NAN)
    return out


def _check(name: str, legacy: pd.DataFrame, engine: pd.DataFrame, keys: list[str], lookup: dict) -> Comparison:
    exp = legacy.assign(manager_key=resolve_names(legacy["manager"], lookup))
    values = _metrics(exp, keys)
    missing = [c for c in values if c not in engine]
    if missing:
        raise ValueError(f"engine draft profiles lack columns {missing}")
    return compare(name, _num(exp, values), _num(engine, values), keys=keys, values=values, tolerance=1e-9)


def _effect(leg: pd.DataFrame, eng: pd.DataFrame, keys: list[str], names: dict) -> list[str]:
    both = leg.merge(eng, on=keys, suffixes=("_l", "_e"))
    out = []
    added = eng.merge(leg[keys], on=keys, how="left", indicator=True)
    added = added[added["_merge"] == "left_only"]
    if len(added):
        out.append(f"adds {len(added)} row(s): " + ", ".join(
            f"{s}" for s in sorted(added["season"].unique())) if "season" in keys else f"adds {len(added)} row(s)")
    changes = []
    for c in _metrics(leg, keys):
        d = (both[f"{c}_e"].astype(float) - both[f"{c}_l"].astype(float)).abs()
        d = d.where(~(both[f"{c}_e"].isna() & both[f"{c}_l"].isna()), 0).fillna(np.inf)
        if (d > 1e-9).any():
            i = d.idxmax()
            who = names.get(both.loc[i, "manager_key"], both.loc[i, "manager_key"])
            when = f" {int(both.loc[i, 'season'])}" if "season" in keys else ""
            changes.append((int((d > 1e-9).sum()), f"{c} {int((d > 1e-9).sum())} row(s), most {who}{when} "
                            f"{both.loc[i, f'{c}_l']:.2f} -> {both.loc[i, f'{c}_e']:.2f}"))
    changed_rows = int((sum(((both[f"{c}_e"].astype(float) - both[f"{c}_l"].astype(float)).abs() > 1e-9)
                            .astype(int) for c in _metrics(leg, keys)) > 0).sum()) if len(both) else 0
    out.append(f"{changed_rows} of {len(both)} rows change" + (": " + "; ".join(
        t for _, t in sorted(changes, reverse=True)[:6]) if changes else ""))
    return out


def engine_changes(tables: dict, cfg: dict) -> list[str]:
    exclude = excluded_manager_keys(cfg)
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    leg = dp_mod.fingerprints(tables, exclude, legacy_mode=True)
    lines = []
    texts = {"engine_pick_numbering": "picks numbered after the draft-order correction (as draft value)",
             "live_season": "the live season is profiled once its draft is done (career stays finished seasons)"}
    runs = [({k: k == fix for k in texts}, f"[{fix}] {texts[fix]}") for fix in texts]
    runs.append(({k: True for k in texts}, "both fingerprint changes together"))
    for changes, label in runs:
        eng = dp_mod.fingerprints(tables, exclude, legacy_mode=True, changes=changes)
        lines.append(f"INFO  engine {label}")
        lines += [f"INFO      seasons: {t}" for t in _effect(leg["draft_fingerprint_seasons"],
                                                            eng["draft_fingerprint_seasons"], KEYS_SEASON, names)]
        lines += [f"INFO      career: {t}" for t in _effect(leg["draft_fingerprint_career"],
                                                           eng["draft_fingerprint_career"], ["manager_key"], names)]
    return lines


SHAPE = ["early_rb_pct", "early_wr_pct", "rb_wr_balance", "positional_diversity", "positional_concentration",
         "same_position_run_rate"]     # need no ADP
OUTCOMES = {"Win_Pct": "win_pct", "PPG": "ppg", "avg_surplus_per_pick": "surplus"}
LIVE_REASON = "2026 ADP: the page used an ADP copy that no longer exists (decision 0004)"
RANDOM_REASON = "random draws the page builder did not record (engine value is seeded)"
TIE_REASON = "career mean at a rounding tie (float noise in the page builder)"
RANDOM_STATS = ["silhouette_k3_gmm", "bootstrap_mean_ari", "bootstrap_std_ari", "bootstrap_p5", "bootstrap_p95"]


def legacy_inputs(tables: dict, results: dict, golden: dict, cfg: dict) -> tuple:
    exclude = excluded_manager_keys(cfg)
    fp = dp_mod.fingerprints(tables, exclude, legacy_mode=True, changes={"live_season": True})
    ms = results["manager_seasons"]
    outcomes = ms[~ms["is_live"]].rename(columns={"pf_per_game": "ppg"})
    v2 = golden["draft_surplus_v2"].copy()
    v2["manager_key"] = resolve_names(v2["manager"], name_to_key(cfg))
    return fp, outcomes, v2


def _season_frames(page: dict, res: dict, keys: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(expected, actual, known) for season values, normalized values and clusters."""
    exp_rows, act = [], res["draft_profile_seasons"].copy()
    for name, periods in page["FINGERPRINTS"].items():
        for period, e in periods.items():
            if period == "career":
                continue
            row = {"season": int(period), "manager_key": keys[name], "cluster": e.get("cluster")}
            row.update({OUTCOMES.get(k, k): v for k, v in e["all"].items()})
            row.update({f"norm_{d}": v for d, v in e["normalized"].items()})
            exp_rows.append(row)
    exp = pd.DataFrame(exp_rows)
    act["win_pct"] = round_half_up(act["win_pct"], 3)
    act["ppg"] = round_half_up(act["ppg"], 2)
    for d in RADAR:
        act[f"norm_{d}"] = act[f"norm_{d}"].round(1)
    live = sorted(act.loc[act["live"], "season"].unique())
    adp_cols = [c for c in exp.columns if c not in KEYS_SEASON + SHAPE + ["win_pct", "ppg", "surplus"]
                + [f"norm_{d}" for d in SHAPE]]
    known = pd.DataFrame([{"season": s, "manager_key": k, "column": c, "reason": LIVE_REASON}
                          for s in live for k in exp.loc[exp["season"] == s, "manager_key"] for c in adp_cols])
    return exp, act, known


def page_checks(tables: dict, results: dict, golden: dict, cfg: dict) -> tuple[list[Comparison], list[str], dict]:
    page = golden["draft_fingerprints_page"]
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    lookup = name_to_key(cfg)
    keys = {n: lookup[n.strip().lower()] for n in page["FINGERPRINTS"]}
    fp, outcomes, v2 = legacy_inputs(tables, results, golden, cfg)
    res = dp_mod.profiles(fp, outcomes, v2, names, legacy_mode=True)

    exp, act, known = _season_frames(page, res, keys)
    values = [c for c in exp.columns if c not in KEYS_SEASON and c in act and not c.startswith("norm_") and c != "cluster"]
    norms = [c for c in exp.columns if c.startswith("norm_")]
    checks = [
        compare("page season values vs draft-fingerprints.html", _num(exp, values), _num(act, values),
                keys=KEYS_SEASON, values=values, tolerance=1e-9, known=known),
        compare("page radar scaling vs draft-fingerprints.html", _num(exp, norms), _num(act, norms),
                keys=KEYS_SEASON, values=norms, tolerance=0.051, known=known),
        compare("page archetype assignments vs draft-fingerprints.html", _num(exp, ["cluster"]),
                _num(act, ["cluster"]), keys=KEYS_SEASON, values=["cluster"], tolerance=0, known=known),
    ]

    # career
    c = res["draft_profile_career"].copy()
    cexp = pd.DataFrame([{"manager_key": keys[n], **{OUTCOMES.get(k, k): v for k, v in p["career"]["all"].items()},
                          **{f"norm_{d}": v for d, v in p["career"]["normalized"].items()}}
                         for n, p in page["FINGERPRINTS"].items()])
    raw = c.set_index("manager_key")
    c["win_pct"], c["ppg"], c["surplus"] = c["win_pct"].round(3), c["ppg"].round(2), c["surplus"].round(4)
    for d in RADAR:
        c[f"norm_{d}"] = c[f"norm_{d}"].round(1)
    ties = []
    for col, digits in (("win_pct", 3), ("ppg", 2)):
        e = cexp.set_index("manager_key")[col]
        near = (raw[col].reindex(e.index) - e).abs() <= 0.5 * 10 ** -digits + 1e-9
        ties += [{"manager_key": k, "column": col, "reason": TIE_REASON} for k in e.index[near]]
    cvals = [x for x in cexp.columns if x != "manager_key" and x in c]
    cn = [x for x in cvals if x.startswith("norm_")]
    cv = [x for x in cvals if x not in cn]
    checks.append(compare("page career values vs draft-fingerprints.html", _num(cexp, cv), _num(c, cv),
                          keys=["manager_key"], values=cv, tolerance=1e-9, known=pd.DataFrame(ties)))
    checks.append(compare("page career radar scaling vs draft-fingerprints.html", _num(cexp, cn), _num(c, cn),
                          keys=["manager_key"], values=cn, tolerance=0.051))

    # archetype summaries, stats, ranges
    arch = res["draft_archetypes"]
    aexp = pd.DataFrame([{"cluster": a["id"], "n": a["n"], **{f"center_{d}": v for d, v in a["center"].items()},
                          "win_pct": a["outcomes"]["win_pct"], "ppg": a["outcomes"]["ppg"],
                          "surplus": a["outcomes"]["avg_surplus_per_pick"]} for a in page["ARCHETYPES"]["cluster_summary"]])
    aact = arch.copy()
    avals = [x for x in aexp.columns if x != "cluster"]
    for x in avals:
        if x != "n":
            aact[x] = aact[x].round(2)
    checks.append(compare("page archetype summaries vs draft-fingerprints.html", _num(aexp, avals), _num(aact, avals),
                          keys=["cluster"], values=avals, tolerance=1e-9))

    st = res["draft_archetype_stats"].iloc[0]
    ps = dict(page["ARCHETYPES"]["stats"])
    lo, hi = ps.pop("bootstrap_p5_p95")
    ps.update({"bootstrap_p5": lo, "bootstrap_p95": hi, "silhouette_raw": ps.pop("silhouette_raw_k4"),
               "silhouette_pca": ps.pop("silhouette_pca_k4"),
               "n_observations": page["ARCHETYPES"]["n_observations"], "n_managers": page["ARCHETYPES"]["n_managers"],
               "n_multi_cluster": page["ARCHETYPES"]["n_multi_cluster"], "k": page["ARCHETYPES"]["k"]})
    sexp = pd.DataFrame([{"row": 0, **ps}])
    sact = pd.DataFrame([{"row": 0, **{k: round(float(st[k]), 3) for k in ps}}])
    known = pd.DataFrame([{"row": 0, "column": k, "reason": RANDOM_REASON} for k in RANDOM_STATS])
    checks.append(compare("page archetype stats vs draft-fingerprints.html", sexp, sact, keys=["row"],
                          values=list(ps), tolerance=1e-9, known=known))

    fin = res["draft_profile_seasons"]
    fin = fin[~fin["live"]].rename(columns={v: k for k, v in OUTCOMES.items()})
    fin["Win_Pct"], fin["PPG"] = round_half_up(fin["Win_Pct"], 3), round_half_up(fin["PPG"], 2)
    car = res["draft_profile_career"].rename(columns={v: k for k, v in OUTCOMES.items()})
    car["Win_Pct"], car["PPG"], car["avg_surplus_per_pick"] = (car["Win_Pct"].round(3), car["PPG"].round(2),
                                                               car["avg_surplus_per_pick"].round(4))
    rows = []
    for scope, frame, want in (("season", fin, page["GLOBAL_RANGES"]), ("career", car, page["CAREER_RANGES"])):
        got = dp_mod.ranges(frame, list(want))
        for col, (a, b) in want.items():
            g = got.get(col, [np.nan, np.nan])
            rows.append({"scope": scope, "metric": col, "lo_e": a, "hi_e": b, "lo_a": g[0], "hi_a": g[1]})
    r = pd.DataFrame(rows)
    rexp = r.rename(columns={"lo_e": "lo", "hi_e": "hi"})[["scope", "metric", "lo", "hi"]]
    ract = r.rename(columns={"lo_a": "lo", "hi_a": "hi"})[["scope", "metric", "lo", "hi"]]
    checks.append(compare("page scales vs draft-fingerprints.html", _num(rexp, ["lo", "hi"]), _num(ract, ["lo", "hi"]),
                          keys=["scope", "metric"], values=["lo", "hi"], tolerance=1e-9))

    info = [f"INFO  fill-in: {st['fill_notes']}"]
    info.append("INFO  seeded engine values for the random figures: " + ", ".join(
        f"{k} {float(st[k]):.3f} (page {ps[k]})" for k in RANDOM_STATS))
    s26 = res["draft_profile_seasons"]
    s26 = s26[s26["live"]]
    if len(s26):
        page_c = {(keys[n], int(p)): e.get("cluster") for n, per in page["FINGERPRINTS"].items()
                  for p, e in per.items() if p != "career"}
        same = sum(page_c.get((k, int(y))) == cl for k, y, cl in zip(s26["manager_key"], s26["season"], s26["cluster"]))
        info.append(f"INFO  live season: {same} of {len(s26)} archetypes as on the page (the page's ADP copy is gone)")
    return checks, info, {"fp": fp, "outcomes": outcomes, "v2": v2, "legacy": res, "names": names}


def match_clusters(legacy: pd.Series, engine: pd.Series) -> dict:
    """Engine cluster id -> the legacy id it overlaps most (one to one): k-means
    numbers clusters arbitrarily, so a rerun can relabel the same groups."""
    from scipy.optimize import linear_sum_assignment

    ok = legacy.notna() & engine.notna()
    table = pd.crosstab(engine[ok].astype(int), legacy[ok].astype(int))
    rows, cols = linear_sum_assignment(-table.to_numpy())
    return {table.index[r]: table.columns[c] for r, c in zip(rows, cols)}


def page_changes(tables: dict, results: dict, ctx: dict, cfg: dict) -> list[str]:
    """Engine changes to the page tables, each alone, then with the engine's own surplus."""
    names, leg = ctx["names"], ctx["legacy"]
    exclude = excluded_manager_keys(cfg)
    lines = []
    page_fixes = ["surplus_weighted", "career_outcomes_unrounded", "engine_pick_numbering"]
    texts = {"surplus_weighted": "surplus per pick = sum(surplus_wtd) / sum(weight), career pooled",
             "career_outcomes_unrounded": "career win% and PPG from unrounded seasons",
             "engine_pick_numbering": "picks numbered after the draft-order correction"}

    def run(changes, surplus):
        ch = {"live_season": True, **changes}
        fp = dp_mod.fingerprints(tables, exclude, legacy_mode=True, changes=ch)
        return dp_mod.profiles(fp, ctx["outcomes"], surplus, names, legacy_mode=True, changes=ch, with_stability=False)

    ds = results.get("draft_surplus")
    engine_surplus = ds[["season", "manager_key", "surplus_wtd", "weight"]] if ds is not None else ctx["v2"]
    runs = [({f: True}, ctx["v2"], f"[{f}] {texts[f]}") for f in page_fixes]
    runs.append(({f: True for f in page_fixes}, engine_surplus,
                 "all engine changes, with the engine's draft surplus (hidden managers included)"))
    for changes, surplus, label in runs:
        eng = run(changes, surplus)
        lines.append(f"INFO  engine {label}")
        a, b = leg["draft_profile_seasons"], eng["draft_profile_seasons"]
        m = a.merge(b, on=KEYS_SEASON, suffixes=("_l", "_e"))
        m["cluster_e"] = m["cluster_e"].map(match_clusters(m["cluster_l"], m["cluster_e"]))
        moved = m[m["cluster_l"].astype("float") != m["cluster_e"].astype("float")]
        lines.append(f"INFO      archetypes: {len(moved)} of {len(m)} manager-seasons change cluster"
                     + (": " + ", ".join(f"{names.get(r.manager_key, r.manager_key)} {r.season}"
                                         for r in moved.head(8).itertuples()) if len(moved) else ""))
        for col, frame_l, frame_e, keys in (("surplus", a, b, KEYS_SEASON),
                                            ("surplus", leg["draft_profile_career"], eng["draft_profile_career"], ["manager_key"]),
                                            ("win_pct", leg["draft_profile_career"], eng["draft_profile_career"], ["manager_key"]),
                                            ("ppg", leg["draft_profile_career"], eng["draft_profile_career"], ["manager_key"])):
            mm = frame_l.merge(frame_e, on=keys, suffixes=("_l", "_e"))
            d = (mm[f"{col}_e"] - mm[f"{col}_l"]).abs()
            filled = mm[f"{col}_l"].isna() & mm[f"{col}_e"].notna()
            scope = "season" if "season" in keys else "career"
            if d.fillna(0).gt(1e-9).any() or filled.any():
                i = d.fillna(-1).idxmax()
                who = names.get(mm.loc[i, "manager_key"], mm.loc[i, "manager_key"])
                when = f" {mm.loc[i, 'season']}" if "season" in keys else ""
                lines.append(f"INFO      {scope} {col}: {int(d.gt(1e-9).sum())} change, most {who}{when} "
                             f"{mm.loc[i, f'{col}_l']:.4f} -> {mm.loc[i, f'{col}_e']:.4f}"
                             + (f"; {int(filled.sum())} newly filled" if filled.any() else ""))
    full = dp_mod.profiles(dp_mod.fingerprints(tables, exclude), ctx["outcomes"], engine_surplus, names,
                           with_stability=False)["draft_profile_seasons"]
    m = leg["draft_profile_seasons"].merge(full, on=KEYS_SEASON, suffixes=("_l", "_e"))
    ids = match_clusters(m["cluster_l"], m["cluster_e"])
    lines.append("INFO  engine archetype ids (by size, largest 0) for the page's clusters: " + ", ".join(
        f"page {old} -> {new}" for new, old in sorted(ids.items(), key=lambda kv: kv[1])))
    return lines


def verify_draft_profiles(tables: dict, golden: dict, cfg: dict, results: dict | None = None
                          ) -> tuple[list[Comparison], list[str]]:
    if "adp" not in tables or not len(tables["adp"]):
        raise ValueError("no adp table in the canonical tables: run `engine normalize` first")
    lookup = name_to_key(cfg)
    res = dp_mod.fingerprints(tables, excluded_manager_keys(cfg), legacy_mode=True)
    checks = [
        _check("draft fingerprint seasons vs draft_fingerprint_manager_season.csv",
               golden["draft_fingerprint_manager_season"], res["draft_fingerprint_seasons"], KEYS_SEASON, lookup),
        _check("draft fingerprint career vs draft_fingerprint_career.csv",
               golden["draft_fingerprint_career"], res["draft_fingerprint_career"], ["manager_key"], lookup),
    ]
    info = ["INFO  legacy mode: ESPN pick numbering, finished seasons; ADP from the canonical adp table"]
    info += engine_changes(tables, cfg)
    if results is not None and "draft_fingerprints_page" in golden:
        pchecks, pinfo, ctx = page_checks(tables, results, golden, cfg)
        checks += pchecks
        info += pinfo + page_changes(tables, results, ctx, cfg)
    return checks, info

"""Draft fingerprints: draft-fingerprints.html.

Outputs
    data/v1/draft-fingerprints.json   page model (schema "draft-fingerprints"): every manager's
                                      draft profile per season and career, keyed by manager key;
                                      the archetypes, their summary and fit statistics; the scales
    pages/draft-fingerprints.html     the page with the data keys of its inline DATA replaced

The page's inline DATA mixes data (FINGERPRINTS, ARCHETYPES, GLOBAL_RANGES,
CAREER_RANGES, RADAR_DIMS, POSDEV_DIMS) with template metadata (labels,
EXPLORER_GROUPS, METRIC_META) and config (MGR_COLORS, MANAGERS_ORDERED,
SEASON_YEARS). Stage A replaces only the data keys and keeps the rest as it
is; Stage B moves the template keys into `web/` and the config keys come
from config.json.

The page builder was lost; its rules, recovered from the page and checked by
`legacy_draft_profiles.page_checks`, are in `fingerprints_view`. Excluded
managers keep their profiles (decision 7.3: archetype comparisons).

Archetype names, descriptions and colors are editorial (decision 7.6):
`leagues/<league>/editorial/archetypes.yaml`, keyed by the engine's stable
cluster id (largest cluster 0). A league without that file gets a generated
label from each cluster's most distinctive radar trait.

Coverage: finished seasons plus the live season once its draft is done, as
the page shows today.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.analytics.draft_profiles import RADAR, round_half_up
from engine.legacy import Comparison
from engine.publish.build import Output
from engine.publish.diff import compare_json
from engine.publish.editorial import load_editorial
from engine.publish.legacy_view import Names, page_roundtrip, read_literal, replace_literal
from engine.publish.writer import clean

SCHEMA, VERSION = "draft-fingerprints", 1
PAGE = "pages/draft-fingerprints.html"
DATA_KEYS = ["FINGERPRINTS", "ARCHETYPES", "GLOBAL_RANGES", "CAREER_RANGES", "RADAR_DIMS", "POSDEV_DIMS"]
OUTCOME_KEYS = ["Win_Pct", "PPG", "avg_surplus_per_pick"]
SEASON_EXTRA_SKIP = {"positional_concentration"}      # the page shows it for careers only
CAREER_EXTRAS = ["draft_adaptability", "first_qb_round", "first_te_round", "first_k_round", "first_dst_round"]
ADP_SUMMARY = ["avg_adp_deviation", "reach_tendency", "value_hunting", "draft_conviction", "adp_independence"]
SHAPE_DIMS = ["early_rb_pct", "early_wr_pct", "rb_wr_balance", "positional_diversity", "same_position_run_rate"]
PATIENCE_DIMS = ["qb_patience", "te_patience", "k_patience", "dst_patience"]
GENERATED_COLORS = ["#c9683f", "#4a7fa8", "#a85a5a", "#5a8a5a", "#8a6fa8", "#a8925a", "#5a8a8a", "#7a7a7a"]


def _num(v, digits=None):
    v = clean(v)
    if v is None:
        return None
    return float(v) if digits is None else round(float(v), digits)


def _half_up(v, digits):
    v = clean(v)
    return None if v is None else float(round_half_up([v], digits)[0])


def posdev_dims(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if c.endswith("_adp_deviation") and c != "avg_adp_deviation"
            and not c.endswith("_filled")]


def season_metrics(frame: pd.DataFrame) -> list[str]:
    """The season metrics the page lists: shape, patience, ADP summary, deviation by position."""
    shape = [d for d in SHAPE_DIMS if d in frame]
    patience = [d for d in PATIENCE_DIMS if d in frame]
    return shape + patience + [c for c in ADP_SUMMARY if c in frame] + posdev_dims(frame)


def career_metrics(career: pd.DataFrame) -> list[str]:
    """Every career fingerprint column (the career scales cover them all)."""
    skip = {"manager_key", "hidden", "n_seasons", "win_pct", "ppg", "surplus"}
    return [c for c in career.columns if c not in skip and not c.startswith("norm_")]


# ---------------------------------------------------------------- archetype labels

def archetype_meta(arch: pd.DataFrame, seasons: pd.DataFrame, editorial: dict | None) -> dict[int, dict]:
    """cluster id -> {name, desc, color}: the league's editorial file, else a
    generated label from the cluster's most distinctive radar trait."""
    editorial = {int(k): v for k, v in (editorial or {}).items()}
    out = {}
    fin = seasons[~seasons["live"]]
    for i, r in enumerate(arch.sort_values("cluster").itertuples()):
        cid = int(r.cluster)
        if cid in editorial:
            e = editorial[cid]
            out[cid] = {"name": str(e["name"]), "desc": str(e.get("desc", "")),
                        "color": str(e.get("color", GENERATED_COLORS[i % len(GENERATED_COLORS)]))}
            continue
        z = {}
        for d in RADAR:
            col = f"center_{d}"
            sd = fin[d].std() if d in fin else np.nan
            if col in arch and sd and sd == sd:
                z[d] = (getattr(r, col) - fin[d].mean()) / sd
        top = max(z, key=lambda d: abs(z[d])) if z else None
        label = top.replace("_pct", "").replace("_", " ").title() if top else f"Group {cid + 1}"
        name = f"{'High' if top and z[top] > 0 else 'Low'} {label}" if top else label
        out[cid] = {"name": name, "desc": f"Generated label: this group's most distinctive trait is "
                                          f"{'a high' if top and z[top] > 0 else 'a low'} {label.lower()}."
                    if top else "Generated label.", "color": GENERATED_COLORS[i % len(GENERATED_COLORS)]}
    return out


# ---------------------------------------------------------------- legacy view

def _entry(r: pd.Series, metrics: list[str], pdims: list[str], meta: dict, career: bool) -> dict:
    win = _half_up(r.get("win_pct"), 3) if not career else _num(r.get("win_pct"), 3)
    ppg = _half_up(r.get("ppg"), 2) if not career else _num(r.get("ppg"), 2)
    sur = _num(r.get("surplus")) if not career else _num(r.get("surplus"), 4)
    allv = {m: _num(r[m]) for m in metrics}
    allv |= {"Win_Pct": win, "PPG": ppg, "avg_surplus_per_pick": sur}
    if career:
        allv |= {c: _num(r[c]) for c in CAREER_EXTRAS if c in r}
        allv["n_seasons"] = int(r["n_seasons"])
    cl = clean(r.get("cluster")) if not career else None
    return {"raw": {d: _num(r[d]) for d in RADAR if d in r},
            "normalized": {d: _num(r[f"norm_{d}"], 1) for d in RADAR if f"norm_{d}" in r},
            "posdev": {d: _num(r[d]) for d in pdims}, "all": allv,
            "cluster": None if cl is None else int(cl),
            "archetype": None if cl is None else meta.get(int(cl), {}).get("name"),
            "outcomes": {"win_pct": win, "ppg": ppg, "surplus": sur}}


def fingerprints_view(res: dict, names, meta: dict[int, dict]) -> dict:
    """The data keys of the page's DATA from the profile tables (draft_profiles.profiles)."""
    s, c = res["draft_profile_seasons"], res["draft_profile_career"]
    arch, st = res["draft_archetypes"], res["draft_archetype_stats"].iloc[0]
    metrics, pdims = season_metrics(s), posdev_dims(s)
    fps: dict = {}
    order = sorted(set(s["manager_key"]) | set(c["manager_key"]), key=names)
    for key in order:
        per = {}
        mine = s[s["manager_key"] == key].sort_values("season")
        for _, r in mine[~mine["live"]].iterrows():
            per[str(int(r["season"]))] = _entry(r, metrics, pdims, meta, False)
        cr = c[c["manager_key"] == key]
        if len(cr):
            per["career"] = _entry(cr.iloc[0], metrics, pdims, meta, True)
        for _, r in mine[mine["live"]].iterrows():
            per[str(int(r["season"]))] = _entry(r, metrics, pdims, meta, False)
        fps[names(key)] = per

    fin = s[~s["live"]].copy()
    fin["Win_Pct"], fin["PPG"] = round_half_up(fin["win_pct"], 3), round_half_up(fin["ppg"], 2)
    fin["avg_surplus_per_pick"] = fin["surplus"]
    car = c.copy()
    car["Win_Pct"], car["PPG"], car["avg_surplus_per_pick"] = car["win_pct"].round(3), car["ppg"].round(2), \
        car["surplus"].round(4)
    ranges = lambda frame, cols: {k: [float(frame[k].min()), float(frame[k].max())]
                                  for k in cols if k in frame and frame[k].notna().any()}

    summary, assignments = [], []
    for r in arch.sort_values("cluster").itertuples():
        m = meta.get(int(r.cluster), {})
        summary.append({"id": int(r.cluster), "name": m.get("name"), "desc": m.get("desc"), "n": int(r.n),
                        "color": m.get("color"),
                        "center": {d: round(float(getattr(r, f"center_{d}")), 2) for d in RADAR
                                   if f"center_{d}" in arch},
                        "outcomes": {"win_pct": round(float(r.win_pct), 2), "ppg": round(float(r.ppg), 2),
                                     "avg_surplus_per_pick": round(float(r.surplus), 2)}})
    clustered = fin.dropna(subset=["cluster"]) if "cluster" in fin else fin.iloc[0:0]
    clustered = clustered.assign(_n=clustered["manager_key"].map(names)).sort_values(["_n", "season"], kind="stable")
    for _, r in clustered.iterrows():
        e = _entry(r, metrics, pdims, meta, False)
        assignments.append({"manager": names(r["manager_key"]), "season": int(r["season"]), "cluster": e["cluster"],
                            "archetype": e["archetype"], "dims": e["raw"], "posdev": e["posdev"],
                            "outcomes": e["outcomes"]})
    r3 = lambda k: None if pd.isna(st.get(k)) else round(float(st[k]), 3)
    archetypes = {"cluster_summary": summary, "assignments": assignments, "k": int(st["k"]),
                  "n_observations": int(st["n_observations"]), "n_managers": int(st["n_managers"]),
                  "n_multi_cluster": int(st.get("n_multi_cluster", 0) or 0),
                  "stats": {"win_pct_p": r3("win_pct_p"), "ppg_p": r3("ppg_p"),
                            "silhouette_pca_k4": r3("silhouette_pca"), "silhouette_raw_k4": r3("silhouette_raw"),
                            "silhouette_k3_gmm": r3("silhouette_k3_gmm"), "bootstrap_mean_ari": r3("bootstrap_mean_ari"),
                            "bootstrap_std_ari": r3("bootstrap_std_ari"),
                            "bootstrap_p5_p95": [r3("bootstrap_p5"), r3("bootstrap_p95")]}}
    return {"FINGERPRINTS": fps, "ARCHETYPES": archetypes,
            "GLOBAL_RANGES": ranges(fin, metrics + OUTCOME_KEYS),
            "CAREER_RANGES": ranges(car, career_metrics(c) + OUTCOME_KEYS),
            "RADAR_DIMS": [d for d in RADAR if d in s], "POSDEV_DIMS": pdims}


# ---------------------------------------------------------------- page model

def _rows(frame: pd.DataFrame, cols: list[str]) -> list[dict]:
    return [clean(r) for r in frame[[c for c in cols if c in frame]].to_dict(orient="records")]


def fingerprints_model(res: dict, meta: dict[int, dict]) -> dict:
    s, c = res["draft_profile_seasons"], res["draft_profile_career"]
    arch, st = res["draft_archetypes"], res["draft_archetype_stats"].iloc[0]
    metrics, pdims = season_metrics(s), posdev_dims(s)
    norms = [f"norm_{d}" for d in RADAR]
    seasons = _rows(s.sort_values(["season", "manager_key"]),
                    ["season", "manager_key", "live", "hidden", *metrics, "positional_concentration",
                     "win_pct", "ppg", "surplus", *norms, "cluster"])
    career = _rows(c.sort_values("manager_key"), ["manager_key", "hidden", *career_metrics(c), "n_seasons",
                                                  "win_pct", "ppg", "surplus", *norms])
    for row in seasons:
        row["cluster"] = None if row.get("cluster") is None else int(row["cluster"])
    archetypes = []
    for r in arch.sort_values("cluster").itertuples():
        m = meta.get(int(r.cluster), {})
        archetypes.append({"id": int(r.cluster), "name": m.get("name"), "description": m.get("desc"),
                           "color": m.get("color"), "n": int(r.n),
                           "center": {d: float(getattr(r, f"center_{d}")) for d in RADAR if f"center_{d}" in arch},
                           "win_pct": float(r.win_pct), "ppg": float(r.ppg), "surplus": float(r.surplus)})
    fin = s[~s["live"]]
    stats = {k: clean(st[k]) for k in st.index if k != "fill_notes"}
    stats["fill_notes"] = str(st.get("fill_notes") or "")
    return {"radar_dims": [d for d in RADAR if d in s], "posdev_dims": pdims, "seasons": seasons, "career": career,
            "archetypes": archetypes, "stats": stats,
            "season_ranges": {k: [clean(fin[k].min()), clean(fin[k].max())] for k in metrics + ["win_pct", "ppg", "surplus"]
                              if k in fin and fin[k].notna().any()},
            "career_ranges": {k: [clean(c[k].min()), clean(c[k].max())] for k in career_metrics(c) + ["win_pct", "ppg", "surplus"]
                              if k in c and c[k].notna().any()}}


# ---------------------------------------------------------------- Stage A check

LIVE_REASON = "2026 ADP: the page used an ADP copy that no longer exists (decision 0004)"
RANDOM_REASON = "random draws the page builder did not record (engine value is seeded)"
TIE_REASON = "career mean at a rounding tie (float noise in the page builder)"
RADAR_TIE_REASON = "radar value within 0.05 (rounded from a different float)"
RANDOM_STATS = {"silhouette_k3_gmm", "bootstrap_mean_ari", "bootstrap_std_ari", "bootstrap_p5_p95"}
NO_ADP = set(SHAPE_DIMS)                       # the 2026 values that need no ADP


def known_fn(live: set[str], career_raw: dict):
    """The excuses `legacy_draft_profiles.page_checks` makes, by path."""
    def known(path: str, eng, leg):
        parts = path.strip("/").replace("[", "/[").split("/")
        if parts[0] == "FINGERPRINTS" and len(parts) >= 3 and parts[2] in live:
            leaf = parts[-1]
            if parts[3] in ("cluster", "archetype") or leaf not in NO_ADP | {"Win_Pct", "PPG", "win_pct", "ppg",
                                                                            "surplus", "avg_surplus_per_pick"}:
                return LIVE_REASON
        if parts[0] == "ARCHETYPES" and len(parts) >= 3 and parts[1] == "stats" and parts[2] in RANDOM_STATS:
            return RANDOM_REASON
        if parts[0] == "FINGERPRINTS" and len(parts) == 5 and parts[2] == "career" and parts[4] in (
                "Win_Pct", "PPG", "win_pct", "ppg"):
            digits = 3 if parts[4].lower() == "win_pct" else 2
            raw = career_raw.get((parts[1], parts[4].lower()))
            if raw is not None and isinstance(leg, (int, float)) and abs(raw - leg) <= 0.5 * 10 ** -digits + 1e-9:
                return TIE_REASON
        if "normalized" in parts and isinstance(eng, float) and isinstance(leg, (int, float)) \
                and abs(eng - leg) <= 0.051:
            return RADAR_TIE_REASON
        return None
    return known


def _keyed(data: dict) -> dict:
    """Lists keyed so their order does not matter."""
    a = data["ARCHETYPES"]
    return {**data, "ARCHETYPES": {**a, "cluster_summary": {str(x["id"]): x for x in a["cluster_summary"]},
                                   "assignments": {f"{x['manager']}|{x['season']}": x for x in a["assignments"]}}}


def compare_view(view: dict, golden: dict, live: set[str], career_raw: dict) -> list[Comparison]:
    return compare_json(f"legacy view {PAGE} DATA", _keyed(view), _keyed(golden), known=known_fn(live, career_raw))


class FingerprintsPublisher:
    name = "draft-fingerprints"
    NEEDS = ("draft_profile_seasons", "draft_profile_career", "draft_archetypes", "draft_archetype_stats")

    def _meta(self, ctx, res) -> dict:
        return archetype_meta(res["draft_archetypes"], res["draft_profile_seasons"],
                              load_editorial(ctx, "archetypes"))

    def _names(self, ctx, text: str | None):
        spelled = []
        if text is not None:
            try:
                spelled = list(read_literal(text, "DATA")["FINGERPRINTS"])
            except (KeyError, ValueError):
                pass
        return Names(ctx, spelled)

    def outputs(self, ctx) -> list[Output]:
        a = ctx.analysis
        if not all(n in a and len(a[n]) for n in self.NEEDS):
            return []
        res = {n: a[n] for n in self.NEEDS}
        meta = self._meta(ctx, res)
        out = [Output(f"data/v1/{SCHEMA}.json", fingerprints_model(res, meta), SCHEMA, VERSION)]
        path = ctx.site_root / PAGE
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            live = read_literal(text, "DATA")
            view = fingerprints_view(res, self._names(ctx, text), meta)
            out.append(Output(PAGE, replace_literal(text, "DATA", {**live, **{k: view[k] for k in DATA_KEYS}})))
        return out

    def verify(self, ctx) -> list:
        a = ctx.analysis
        if not all(n in a and len(a[n]) for n in self.NEEDS):
            return []
        res = legacy_profiles(ctx)
        gold = ctx.golden["draft_fingerprints_page"]
        names = Names(ctx, list(gold["FINGERPRINTS"]))
        meta = {x["id"]: {"name": x["name"], "desc": x["desc"], "color": x["color"]}
                for x in gold["ARCHETYPES"]["cluster_summary"]}     # legacy mode keeps the page's cluster ids
        view = fingerprints_view(res, names, meta)
        path = ctx.site_root / PAGE
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            data = page_roundtrip(text, {"DATA": {**read_literal(text, "DATA"), **view}})["DATA"]
            view = {k: data[k] for k in DATA_KEYS}
        live = {str(int(x)) for x in res["draft_profile_seasons"].loc[res["draft_profile_seasons"]["live"], "season"]
                .unique()}
        c = res["draft_profile_career"]
        career_raw = {(names(k), col): float(v) for k, w, p in zip(c["manager_key"], c["win_pct"], c["ppg"])
                      for col, v in (("win_pct", w), ("ppg", p))}
        checks: list = compare_view(view, {k: gold[k] for k in DATA_KEYS}, live, career_raw)
        return checks + self.info(ctx)

    def info(self, ctx) -> list[str]:
        """What the live page changes to at M1: archetypes by name, engine vs the live page."""
        a = ctx.analysis
        res = {n: a[n] for n in self.NEEDS}
        editorial = load_editorial(ctx, "archetypes")
        meta = archetype_meta(res["draft_archetypes"], res["draft_profile_seasons"], editorial)
        path = ctx.site_root / PAGE
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8")
        live = read_literal(text, "DATA")["FINGERPRINTS"]
        eng = fingerprints_view(res, self._names(ctx, text), meta)["FINGERPRINTS"]
        both = [(m, p) for m, per in live.items() for p, e in per.items()
                if p != "career" and e.get("archetype") and m in eng and p in eng[m]]
        same = sum(eng[m][p]["archetype"] == live[m][p]["archetype"] for m, p in both)
        return [f"INFO  draft-fingerprints, engine data vs the live page: {same} of {len(both)} manager-seasons keep "
                f"their archetype (the live season's moved with the ADP copy); names from "
                f"{'the league editorial file' if editorial else 'generated labels'}: "
                + ", ".join(f"{k} {v['name']}" for k, v in sorted(meta.items()))
                + "; the methodology prose (p-values, variance) stays typed in the page until Stage B"]


def legacy_profiles(ctx) -> dict:
    """The profile tables on legacy inputs, as `analyze --verify` builds them for the page checks."""
    def run():
        from engine.analytics import draft_profiles as dp_mod
        from engine.legacy_draft_profiles import legacy_inputs
        fp, outcomes, v2 = legacy_inputs(ctx.tables, ctx.analysis, ctx.golden, ctx.cfg)
        names = {m["id"]: m["name"] for m in ctx.cfg.get("managers") or []}
        return dp_mod.profiles(fp, outcomes, v2, names, legacy_mode=True)
    return ctx.memo("legacy_profiles", run)

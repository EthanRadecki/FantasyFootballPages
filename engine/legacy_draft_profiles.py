"""Compare draft profiles with the legacy draft_fingerprint.py outputs.

Golden files (engine/tests/golden/draft/):
    draft_fingerprint_manager_season.csv.gz   per manager and season, 2020-2025
    draft_fingerprint_career.csv.gz           per manager, with draft_adaptability

Legacy mode (ESPN's pick numbering, finished seasons only) must match every
number. The ADP it reads is the canonical adp table, which normalize already
checks pick by pick against draft_history_with_adp.csv. Engine changes are
listed as INFO lines, each alone and then together.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.analytics import draft_profiles as dp_mod
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
    runs = [({k: k == fix for k in dp_mod.ENGINE_CHANGES}, f"[{fix}] {texts[fix]}") for fix in dp_mod.ENGINE_CHANGES]
    runs.append((dict(dp_mod.ENGINE_CHANGES), "all engine changes together"))
    for changes, label in runs:
        eng = dp_mod.fingerprints(tables, exclude, legacy_mode=True, changes=changes)
        lines.append(f"INFO  engine {label}")
        lines += [f"INFO      seasons: {t}" for t in _effect(leg["draft_fingerprint_seasons"],
                                                            eng["draft_fingerprint_seasons"], KEYS_SEASON, names)]
        lines += [f"INFO      career: {t}" for t in _effect(leg["draft_fingerprint_career"],
                                                           eng["draft_fingerprint_career"], ["manager_key"], names)]
    return lines


def verify_draft_profiles(tables: dict, golden: dict, cfg: dict) -> tuple[list[Comparison], list[str]]:
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
    return checks, info + engine_changes(tables, cfg)

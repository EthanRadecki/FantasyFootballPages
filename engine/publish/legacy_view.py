"""Helpers for Stage A legacy views: today's site files, rebuilt by publish.

A legacy view lets the current pages run on engine data unchanged until each
page moves into `web/` (Stage B), when its legacy view is deleted. Legacy
files name managers the way that file always did ("Carmine Pittelli Jr." on
one page, "Carmine Pittelli" on another), so each view takes its spellings
from the current site file it replaces, falling back to the config name for
a manager the file has never seen.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from engine.legacy import name_to_key


def site_json(ctx, rel: str):
    path = Path(ctx.site_root) / rel
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def site_csv(ctx, rel: str) -> pd.DataFrame | None:
    path = Path(ctx.site_root) / rel
    return pd.read_csv(path) if path.is_file() else None


def spellings(names: Iterable[str], cfg: dict) -> dict[str, str]:
    """member key -> the spelling these legacy names use (first seen wins)."""
    lookup = name_to_key(cfg)
    out: dict[str, str] = {}
    for n in names:
        if not isinstance(n, str):
            continue
        key = lookup.get(n.strip().lower())
        if key and key not in out:
            out[key] = n
    return out


class Names:
    """Display names for one legacy file: its own spelling, else config."""

    def __init__(self, ctx, legacy_names: Iterable[str] = ()):
        self.config = {m["key"]: m for m in ctx.config["managers"]}
        self.spelled = spellings(legacy_names, ctx.cfg)

    def __call__(self, key: str) -> str:
        return self.spelled.get(key) or self.config[key]["name"]

    def short(self, key: str) -> str:
        return self.config[key]["short"]


def csv_text(df: pd.DataFrame, index_label: str | None = None) -> str:
    buf = io.StringIO()
    if index_label is None:
        df.to_csv(buf, index=False, lineterminator="\n")
    else:
        df.to_csv(buf, index=True, index_label=index_label, lineterminator="\n")
    return buf.getvalue()


def info_diff(name: str, live: pd.DataFrame, engine: pd.DataFrame, keys: list[str], values: list[str],
              tol: float = 0.005) -> str:
    """One INFO line: how the engine's data differs from the live site file
    (what the live page will show after milestone M1). Not a check."""
    both = live.merge(engine, on=keys, how="outer", suffixes=("_l", "_e"), indicator=True)
    only_e = int((both["_merge"] == "right_only").sum())
    only_l = int((both["_merge"] == "left_only").sum())
    b = both[both["_merge"] == "both"]
    changed = pd.Series(False, index=b.index)
    for v in values:
        lv, ev = b[f"{v}_l"], b[f"{v}_e"]
        if pd.api.types.is_numeric_dtype(lv) and pd.api.types.is_numeric_dtype(ev):
            changed |= (lv.astype(float) - ev.astype(float)).abs().gt(tol)
        else:
            changed |= lv.astype(str) != ev.astype(str)
    return (f"INFO  {name}, engine data vs the live file: {len(b)} rows in both, {int(changed.sum())} with a "
            f"different {'/'.join(values)}; {only_e} only in the engine, {only_l} only in the live file "
            f"(later weeks, or rows the live file keys differently)")

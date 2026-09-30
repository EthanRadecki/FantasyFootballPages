"""Turn Python and pandas values into site JSON, and write it.

Every page model file carries a `meta` block (schema name and version, build
id, generation time) beside its data. Legacy views (Stage A copies of the
current site files) are written without it, in the shape the old pages read.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def clean(value: Any) -> Any:
    """JSON-safe copy: numpy and pandas scalars become Python values, NaN,
    infinity and pandas missing values become None, tuples become lists.
    Dict keys become strings (JSON has no other key type)."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return [clean(v) for v in value.tolist()]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return value.isoformat()
    return value


def rnd(value: Any, digits: int) -> float | None:
    """Round for display, None for missing values. Python's round (the one
    the legacy scripts used)."""
    v = clean(value)
    if v is None:
        return None
    return round(float(v), digits)


def records(df: pd.DataFrame, columns: list[str] | None = None) -> list[dict]:
    """DataFrame rows as JSON-safe dicts, in row order."""
    view = df if columns is None else df[columns]
    return [clean(r) for r in view.to_dict(orient="records")]


def build_info(build_id: str | None = None, now: dt.datetime | None = None) -> dict:
    """Build id (UTC timestamp plus the git commit when known) and time.
    Pages use the id to fetch matching data files and never mix builds."""
    now = now or dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    if build_id is None:
        sha = os.environ.get("GITHUB_SHA", "")[:7]
        if not sha:
            try:
                sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                     timeout=5, check=False).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                sha = ""
        build_id = now.strftime("%Y%m%dT%H%M%SZ") + (f"-{sha}" if sha else "")
    return {"id": build_id, "generated_at": now.isoformat().replace("+00:00", "Z")}


def with_meta(schema: str, version: int, build: dict, payload: dict) -> dict:
    """A page model file: `meta` first, then the page's own keys."""
    if "meta" in payload:
        raise ValueError(f"{schema}: payload may not use the reserved key 'meta'")
    meta = {"schema": schema, "schema_version": version, "build_id": build["id"],
            "generated_at": build["generated_at"]}
    return {"meta": meta, **clean(payload)}


def dump(payload: Any) -> str:
    """Compact JSON text. NaN is never written (clean() turns it into null)."""
    return json.dumps(clean(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")

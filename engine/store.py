"""Read and write canonical tables (Parquet, one file per table)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def canonical_dir(cache_root: Path, provider: str, league_id: int) -> Path:
    return cache_root / "canonical" / provider / str(league_id)


def write_tables(tables: dict[str, pd.DataFrame], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(out_dir / f"{name}.parquet", index=False)


def read_tables(in_dir: Path) -> dict[str, pd.DataFrame]:
    return {p.stem: pd.read_parquet(p) for p in sorted(in_dir.glob("*.parquet"))}

"""ADP (average draft position) for every season a league drafted.

Two sources, best first:

1. The provider's own ADP, saved by `engine pull` when the league's draft
   finished (for ESPN: adp_snapshot.json in the raw season cache). ESPN only
   serves a live ADP that keeps moving all season and resets once the season
   is over, so a copy taken more than `analysis.adp.snapshot_max_days` after
   the draft is not used.
2. The engine's shared ADP library, engine/data/adp/<library>/<season>.txt or
   .csv: market ADP exports (FantasyPros), one per season, the same for every
   league with that scoring. The provider's column is read (ESPN for ESPN
   leagues). Both FantasyPros layouts are read as downloaded: the older
   tab-separated text (header on one line, or one column name per line after a
   title line) and the newer CSV.

A season with neither gets no rows, and the ADP-based draft metrics are left
blank for it.

Output, the canonical `adp` table: season x player as the source lists them,
in source order (`rank`), with the league's `player_id` where the name and
position match exactly one player (null otherwise). Unmatched rows are kept:
they still count when ranking players within a position.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

LIBRARY_ROOT = Path(__file__).resolve().parents[1] / "data" / "adp"
DEFAULT_LIBRARY = "fantasypros_ppr"
DEFAULT_SNAPSHOT_MAX_DAYS = 3
SNAPSHOT_SOURCE = "draft_snapshot"

# The ADP export column that holds each provider's own ADP.
PROVIDER_COLUMNS = {"espn": "ESPN", "sleeper": "Sleeper", "yahoo": "Yahoo"}

ADP_COLUMNS = ["season", "source", "rank", "player_name", "pro_team", "position", "adp", "player_id"]

TEAM_BYE_RE = re.compile(r"\s+[A-Z]{2,3}\s*\(\d+\)\s*$")    # " CAR (13)", also " DST (8)"
BYE_RE = re.compile(r"\s*\(\d+\)\s*$")
TEAM_RE = re.compile(r"\s([A-Z]{2,3})\s*\(\d+\)")
POS_RE = re.compile(r"^([A-Z]+)")
SUFFIX_RE = re.compile(r"\b(Jr|Sr|II|III|IV|V)\.?$", re.IGNORECASE)

# Defenses are matched on the nickname. Franchises whose nickname changed
# map to the current one (the provider lists every season under it).
DST_NICKNAMES = {
    "washington football team": "Commanders",
    "washington redskins": "Commanders",
    "washington commanders": "Commanders",
}


def config(cfg: dict) -> dict:
    """analysis.adp with defaults filled in."""
    raw = (cfg.get("analysis") or {}).get("adp") or {}
    return {"library": raw.get("library", DEFAULT_LIBRARY),
            "snapshot_max_days": raw.get("snapshot_max_days", DEFAULT_SNAPSHOT_MAX_DAYS)}


# ---------------------------------------------------------------- names

def clean_name(raw: str) -> str:
    """'Christian McCaffrey CAR (13)' -> 'Christian McCaffrey'; 'Houston Texans DST (8)' -> 'Houston Texans'."""
    raw = re.sub(r"\s+", " ", str(raw)).strip()
    return BYE_RE.sub("", TEAM_BYE_RE.sub("", raw)).strip()


def team_of(raw: str) -> str | None:
    m = TEAM_RE.search(re.sub(r"\s+", " ", str(raw)))
    return m.group(1) if m and m.group(1) != "DST" else None


def dst_nickname(name: str) -> str:
    """'San Francisco 49ers' -> '49ers'; '49ers D/ST' -> '49ers'."""
    name = name.replace("D/ST", "").replace(" DST", "").strip()
    if name.lower() in DST_NICKNAMES:
        return DST_NICKNAMES[name.lower()]
    parts = name.split()
    return parts[-1] if parts else name


def match_key(name: str, position: str) -> str:
    """Loose key for joining names across sources: no periods, no Jr/Sr/II-V, lower case."""
    n = dst_nickname(name) if position == "D/ST" else str(name)
    n = SUFFIX_RE.sub("", n.replace(".", "")).strip()
    return re.sub(r"\s+", " ", n).lower()


def canonical_position(pos: str | None) -> str | None:
    return "D/ST" if pos == "DST" else pos


# ---------------------------------------------------------------- library files

def _split(line: str, delimiter: str) -> list[str]:
    return next(csv.reader([line], delimiter=delimiter)) if line else []


def read_export(path: Path, season: int, column: str) -> pd.DataFrame:
    """One ADP export -> rows with an ADP in `column`, in file order."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = delimiter = None
    for i, line in enumerate(lines):
        for d in ("\t", ","):
            if d in line and line.split(d)[0].strip().isdigit():
                start, delimiter = i, d
                break
        if start is not None:
            break
    if start is None:
        raise ValueError(f"{path}: no data rows found")

    header: list[str] = []
    for line in lines[:start]:
        header += [t.strip() for t in (_split(line, delimiter) if delimiter in line else [line])]
    header = [t for t in header if t]
    if "Rank" not in header or column not in header:
        raise ValueError(f"{path}: header has no '{column}' column ({header})")
    col = header.index(column) - header.index("Rank")

    rows = []
    for line in lines[start:]:
        f = _split(line, delimiter)
        if len(f) <= max(col, 2) or not f[0].strip().isdigit():
            continue
        name = clean_name(f[1])
        pos = POS_RE.match(f[2].strip())
        adp = pd.to_numeric(f[col].strip(), errors="coerce")
        if not name or not pos or pd.isna(adp):
            continue
        rows.append({"season": season, "rank": int(f[0]), "player_name": name, "pro_team": team_of(f[1]),
                     "position": canonical_position(pos.group(1)), "adp": float(adp)})
    return pd.DataFrame(rows, columns=["season", "rank", "player_name", "pro_team", "position", "adp"])


def library_file(library: str, season: int, root: Path = LIBRARY_ROOT) -> Path | None:
    for ext in (".txt", ".csv"):
        p = root / library / f"{season}{ext}"
        if p.exists():
            return p
    return None


def load_library(library: str, seasons: list[int], provider: str, root: Path = LIBRARY_ROOT) -> pd.DataFrame:
    column = PROVIDER_COLUMNS.get(provider)
    if column is None:
        raise ValueError(f"No ADP export column known for provider '{provider}'")
    frames = [read_export(p, s, column).assign(source=library)
              for s in seasons if (p := library_file(library, s, root)) is not None]
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=ADP_COLUMNS)


# ---------------------------------------------------------------- snapshots

def snapshot_age_days(meta: dict) -> float | None:
    """Days between the draft and the snapshot, or None when either date is unknown."""
    try:
        pulled = datetime.fromisoformat(meta["pulled_at"])
        drafted = datetime.fromisoformat(meta["draft_date"])
    except (KeyError, TypeError, ValueError):
        return None
    return (pulled - drafted).total_seconds() / 86400


def usable_snapshot(meta: dict, max_days: float) -> bool:
    age = snapshot_age_days(meta)
    return age is not None and 0 <= age <= max_days


def snapshot_table(season: int, rows: list[dict]) -> pd.DataFrame:
    """Provider snapshot rows (player_id, player_name, position, adp) -> adp rows, best ADP first."""
    df = pd.DataFrame(rows, columns=["player_id", "player_name", "position", "adp"]).dropna(subset=["adp"])
    df = df.sort_values("adp", kind="stable").reset_index(drop=True)
    return df.assign(season=season, source=SNAPSHOT_SOURCE, rank=range(1, len(df) + 1), pro_team=None)


# ---------------------------------------------------------------- matching

def name_pool(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Every (season, player_id, name, position) the provider listed."""
    cols = ["season", "player_id", "player_name", "position"]
    parts = [tables[t][cols] for t in ("player_seasons", "player_stats") if t in tables and len(tables[t])]
    if not parts:
        return pd.DataFrame(columns=cols)
    pool = pd.concat(parts, ignore_index=True).dropna(subset=["player_id", "player_name"])
    return pool.drop_duplicates(["season", "player_id", "player_name", "position"])


def match_players(adp: pd.DataFrame, pool: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """player_id for each adp row: the one player with the same season, position
    and name key. Ambiguous keys (two players) stay unmatched and are returned."""
    key = pool.assign(key=[match_key(n, p) for n, p in zip(pool["player_name"], pool["position"])])
    ids = key.groupby(["season", "position", "key"])["player_id"].agg(lambda s: sorted(set(s)))
    ambiguous = ids[ids.map(len) > 1]
    unique = ids[ids.map(len) == 1].map(lambda s: s[0])
    k = pd.MultiIndex.from_arrays([adp["season"], adp["position"],
                                   [match_key(n, p) for n, p in zip(adp["player_name"], adp["position"])]])
    matched = pd.Series(unique.reindex(k).to_numpy(), index=adp.index).astype("Int64")
    return matched, ambiguous.reset_index()


# ---------------------------------------------------------------- the table

def build_adp(tables: dict[str, pd.DataFrame], snapshots: dict[int, dict], cfg: dict,
              root: Path = LIBRARY_ROOT) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The canonical adp table, plus one report row per drafted season.

    snapshots: {season: {"pulled_at", "draft_date", "rows": [...]}} from the provider."""
    opts = config(cfg)
    provider = cfg["league"]["provider"]
    seasons = sorted(int(s) for s in tables["draft_picks"]["season"].unique())
    use_snap = {s for s in seasons if s in snapshots and usable_snapshot(snapshots[s], opts["snapshot_max_days"])}

    lib = load_library(opts["library"], [s for s in seasons if s not in use_snap], provider, root)
    pool = name_pool(tables)
    if len(lib):
        lib["player_id"], _ = match_players(lib, pool)
    snap = [snapshot_table(s, snapshots[s]["rows"]) for s in sorted(use_snap)]
    adp = pd.concat([f for f in [lib, *snap] if len(f)], ignore_index=True) if (len(lib) or snap) \
        else pd.DataFrame(columns=ADP_COLUMNS)
    adp = adp[ADP_COLUMNS].sort_values(["season", "rank"], kind="stable").reset_index(drop=True)
    adp["player_id"] = adp["player_id"].astype("Int64")
    adp["season"] = adp["season"].astype(int)
    adp["rank"] = adp["rank"].astype(int)
    return adp, report(tables, adp, snapshots, opts)


def report(tables: dict[str, pd.DataFrame], adp: pd.DataFrame, snapshots: dict[int, dict], opts: dict) -> pd.DataFrame:
    picks = tables["draft_picks"]
    matched = adp.dropna(subset=["player_id"])
    have = set(zip(matched["season"].astype(int), matched["player_id"].astype(int)))
    rows = []
    for season, g in picks.groupby("season"):
        src = adp.loc[adp["season"] == season, "source"]
        meta = snapshots.get(int(season))
        age = snapshot_age_days(meta) if meta else None
        rows.append({
            "season": int(season),
            "source": src.iloc[0] if len(src) else "none",
            "adp_rows": int(len(src)),
            "picks": int(len(g)),
            "picks_with_adp": int(sum((int(season), int(p)) in have for p in g["player_id"])),
            "snapshot": "none" if meta is None else (
                "date unknown" if age is None else f"{age:.1f} days after the draft"
                + ("" if 0 <= age <= opts["snapshot_max_days"] else " (too late, not used)")),
        })
    return pd.DataFrame(rows)


def position_order(adp: pd.DataFrame) -> pd.Series:
    """Rank of each row's ADP within its season and position (1 = drafted first);
    ties go to the source's own order."""
    return adp.groupby(["season", "position"])["adp"].rank(method="first", ascending=True)

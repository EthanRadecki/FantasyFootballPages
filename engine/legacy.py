"""Compare canonical tables with the site's existing (legacy) data files.

The legacy CSVs are the ground truth for phase 2: the new pipeline is trusted
only once it reproduces them. Each check maps both sides onto the same keys
(season, week, manager key, ...) and reports missing rows, extra rows, and
value mismatches, with a few examples of each.

Legacy name conventions handled here (and nowhere else):
- managers appear by name; names resolve to member keys through league.yaml
  (name plus aliases, e.g. "Carmine Pittelli Jr.")
- weeks appear as "Week N" or "Playoff Round K"
- the rosters file keeps only winners-bracket teams in playoff weeks
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Comparison:
    name: str
    expected_rows: int
    actual_rows: int
    missing: int = 0
    extra: int = 0
    mismatched: dict[str, int] = field(default_factory=dict)
    known: dict[str, int] = field(default_factory=dict)
    examples: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing or self.extra or any(self.mismatched.values()))

    def render(self) -> str:
        head = "PASS" if self.ok else "FAIL"
        lines = [f"{head}  {self.name}: expected {self.expected_rows} rows, got {self.actual_rows}"]
        if self.missing:
            lines.append(f"      missing (in legacy, not in engine): {self.missing}")
        if self.extra:
            lines.append(f"      extra (in engine, not in legacy):   {self.extra}")
        for col, n in self.mismatched.items():
            if n:
                lines.append(f"      mismatched {col}: {n}")
        for reason, n in self.known.items():
            lines.append(f"      known legacy difference ({n}): {reason}")
        lines += [f"      e.g. {e}" for e in self.examples]
        return "\n".join(lines)


def name_to_key(cfg: dict) -> dict[str, str]:
    """Every configured name and alias (case-insensitive) -> member key."""
    out: dict[str, str] = {}
    for m in cfg.get("managers") or []:
        for n in [m["name"], *(m.get("aliases") or [])]:
            out[n.strip().lower()] = m["id"]
    return out


def resolve_names(series: pd.Series, lookup: dict[str, str]) -> pd.Series:
    keys = series.str.strip().str.lower().map(lookup)
    unknown = sorted(series[keys.isna()].unique())
    if unknown:
        raise ValueError(f"Legacy names not in league.yaml (add them as aliases): {unknown}")
    return keys


def legacy_week(label: pd.Series, season: pd.Series, regular_periods: dict[int, int]) -> pd.Series:
    """'Week 7' -> 7; 'Playoff Round 2' -> regular season length + 2."""
    num = label.str.extract(r"(\d+)$")[0].astype(int)
    is_playoff_round = label.str.startswith("Playoff Round")
    offset = season.map(regular_periods).astype(int)
    return num.where(~is_playoff_round, offset + num)


def compare(name: str, expected: pd.DataFrame, actual: pd.DataFrame, keys: list[str],
            values: list[str], tolerance: float = 0.005, max_examples: int = 5,
            known: pd.DataFrame | None = None) -> Comparison:
    """Row-by-row comparison on `keys`.

    `known` lists legacy bugs to excuse: columns keys + ["column", "reason"].
    Excused rows are counted per reason instead of as mismatches.
    """
    exp = expected[keys + values].copy()
    act = actual[keys + values].copy()
    merged = exp.merge(act, on=keys, how="outer", suffixes=("_legacy", "_engine"), indicator=True)
    result = Comparison(name, len(exp), len(act))
    missing = merged[merged["_merge"] == "left_only"]
    extra = merged[merged["_merge"] == "right_only"]
    result.missing, result.extra = len(missing), len(extra)
    for _, row in missing.head(2).iterrows():
        result.examples.append("missing " + ", ".join(f"{k}={row[k]}" for k in keys))
    for _, row in extra.head(2).iterrows():
        result.examples.append("extra " + ", ".join(f"{k}={row[k]}" for k in keys))

    both = merged[merged["_merge"] == "both"]
    for col in values:
        a, b = both[f"{col}_legacy"], both[f"{col}_engine"]
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b) and not pd.api.types.is_bool_dtype(a):
            bad = (a.astype(float) - b.astype(float)).abs() > tolerance
        else:
            bad = a.astype(str) != b.astype(str)
        if known is not None and len(known):
            k = known[known["column"] == col]
            if len(k):
                flagged = both[keys].merge(k[keys + ["reason"]], on=keys, how="left")["reason"]
                excused = bad & flagged.notna().to_numpy()
                for reason, n in flagged[excused.to_numpy()].value_counts().items():
                    result.known[reason] = result.known.get(reason, 0) + int(n)
                bad = bad & ~excused
        result.mismatched[col] = int(bad.sum())
        room = max(0, max_examples - len(result.examples))
        for _, row in both[bad].head(room).iterrows():
            result.examples.append(
                f"{col}: " + ", ".join(f"{k}={row[k]}" for k in keys)
                + f" legacy={row[f'{col}_legacy']!r} engine={row[f'{col}_engine']!r}")
    return result


def check_matchups(tables: dict[str, pd.DataFrame], legacy: pd.DataFrame, cfg: dict) -> Comparison:
    """Legacy matchup_data.csv: one row per team per game, byes excluded,
    Is_Playoff = 'Yes' only for winners-bracket games."""
    lookup = name_to_key(cfg)
    regular = dict(zip(tables["seasons"]["season"], tables["seasons"]["regular_season_periods"]))
    exp = pd.DataFrame({
        "season": legacy["Season_Year"].astype(int),
        "week": legacy_week(legacy["Week"], legacy["Season_Year"], regular),
        "manager_key": resolve_names(legacy["Team_Name"], lookup),
        "opponent_manager_key": resolve_names(legacy["Opponent_Name"], lookup),
        "points": legacy["Team_Score"].astype(float),
        "opponent_points": legacy["Opponent_Score"].astype(float),
        "result": legacy["Outcome"].map({"Win": "W", "Loss": "L", "Tie": "T"}),
        "winners_bracket": legacy["Is_Playoff"].eq("Yes"),
    })
    m = tables["matchups"]
    m = m[~m["is_bye"] & m["season"].isin(exp["season"].unique())]
    act = m.assign(winners_bracket=m["tier"].eq("WINNERS_BRACKET"))

    # Legacy bug: games where the legacy file gives BOTH teams a loss (a tied
    # score decided by ESPN's tiebreak). ESPN's recorded winner is kept.
    pair = exp.merge(exp, left_on=["season", "week", "opponent_manager_key"],
                     right_on=["season", "week", "manager_key"], suffixes=("", "_opp"))
    both_lost = pair[(pair["result"] == "L") & (pair["result_opp"] == "L")]
    known = both_lost[["season", "week", "manager_key"]].assign(
        column="result", reason="legacy gave both teams a loss in a tiebreak game; ESPN's winner kept")
    return compare("matchups vs data/matchup_data.csv", exp, act,
                   keys=["season", "week", "manager_key"],
                   values=["opponent_manager_key", "points", "opponent_points", "result", "winners_bracket"],
                   known=known)


def check_rosters(tables: dict[str, pd.DataFrame], legacy: pd.DataFrame, cfg: dict) -> Comparison:
    """Legacy weekly_rosters_bracket_only.csv: every team's lineup in the regular
    season (2020 bye team included); in playoff weeks only teams playing a
    winners-bracket game."""
    lookup = name_to_key(cfg)
    exp = pd.DataFrame({
        "season": legacy["Season"].astype(int),
        "week": legacy["Week"].astype(int),
        "manager_key": resolve_names(legacy["Manager"], lookup),
        "player_id": legacy["Player_ID"].astype(int),
        "player_name": legacy["Player"],
        "position": legacy["Position"],
        "slot": legacy["Slot"],
        "started": legacy["Started"].astype(bool),
        "points": legacy["Points"].astype(float),
    })
    m = tables["matchups"]
    in_bracket = m[~m["is_playoff_week"] | (m["tier"].eq("WINNERS_BRACKET") & ~m["is_bye"])]
    keep = in_bracket[["season", "week", "team_id"]].drop_duplicates()
    lu = tables["lineups"].merge(keep, on=["season", "week", "team_id"])
    lu = lu[lu["season"].isin(exp["season"].unique())]

    # Legacy bug: ESPN reclassified some players (e.g. WR -> RB); the legacy
    # file applied the later position to earlier seasons. The engine keeps the
    # position ESPN listed that season. Excused only where the legacy value
    # equals a position ESPN gave that player in some other season.
    positions = tables["lineups"][["player_id", "season", "position"]].drop_duplicates()
    cand = exp.merge(lu[["season", "week", "manager_key", "player_id", "position"]],
                     on=["season", "week", "manager_key", "player_id"], suffixes=("", "_engine"))
    cand = cand[cand["position"] != cand["position_engine"]]
    later = cand.merge(positions.rename(columns={"season": "other_season", "position": "other_position"}),
                       on="player_id")
    later = later[(later["other_season"] != later["season"]) & (later["other_position"] == later["position"])]
    known = later[["season", "week", "manager_key", "player_id"]].drop_duplicates().assign(
        column="position", reason="legacy used a later-season position; the engine keeps that season's ESPN position")
    return compare("lineups vs weekly_rosters_bracket_only.csv", exp, lu,
                   keys=["season", "week", "manager_key", "player_id"],
                   values=["player_name", "position", "slot", "started", "points"],
                   known=known)


def config_consistency(tables: dict[str, pd.DataFrame], cfg: dict) -> list[str]:
    """Warn where league.yaml disagrees with what ESPN reports."""
    warnings: list[str] = []
    rules = cfg.get("rules") or {}
    reg = rules.get("regular_season_weeks") or {}
    for _, s in tables["seasons"].iterrows():
        configured = reg.get(int(s["season"]), reg.get("default"))
        if configured is not None and s["regular_season_periods"] and configured != s["regular_season_periods"]:
            warnings.append(f"{s['season']}: league.yaml says {configured} regular-season weeks, ESPN says {s['regular_season_periods']}")
    known = {m["id"] for m in cfg.get("managers") or []}
    for k in sorted(set(tables["managers"]["manager_key"]) - known):
        warnings.append(f"ESPN member {k} is not in league.yaml")
    return warnings

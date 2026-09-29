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
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)   # full detail, written by --verify

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
    result.frames["missing"] = missing.drop(columns="_merge")
    result.frames["extra"] = extra.drop(columns="_merge")
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
        if bad.any():
            result.frames[f"mismatched_{col}"] = both[bad].drop(columns="_merge")
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
    from engine.analytics.weeks import bracket_lineups

    lu = bracket_lineups(tables)
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


NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def surname(name: str) -> str:
    """Last name without punctuation or generational suffix: 'Aaron Jones Sr.' -> 'jones'."""
    parts = [p for p in "".join(c for c in str(name).lower() if c.isalnum() or c.isspace()).split()
             if p not in NAME_SUFFIXES]
    return parts[-1] if parts else ""


def check_draft(tables: dict[str, pd.DataFrame], legacy: pd.DataFrame, cfg: dict) -> Comparison:
    """Legacy draft_history_all_positions.csv: one row per pick, K and D/ST included.

    The legacy file numbers picks the way ESPN recorded them (before any
    draft-order correction), so picks are matched on ESPN's numbering. Player
    names come from ESPN's player data; spelling variants of the same surname
    (Jr./Sr., Marquise vs Hollywood Brown) are reported as known differences.
    """
    lookup = name_to_key(cfg)
    exp = pd.DataFrame({
        "season": legacy["season"].astype(int),
        "overall_pick": legacy["overall_pick"].astype(int),
        "round": legacy["round"].astype(int),
        "round_pick": legacy["pick_in_round"].astype(int),
        "draft_slot": legacy["draft_slot"].astype(int),
        "manager_key": resolve_names(legacy["manager"], lookup),
        "player_name": legacy["player_name"],
        "position": legacy["position"],
    })
    dp = tables["draft_picks"].copy()
    for col in ("overall_pick", "round_pick"):
        if f"espn_{col}" in dp:
            dp[col] = dp[f"espn_{col}"].fillna(dp[col])
    ps = tables["player_seasons"].rename(columns={"player_name": "ps_name", "position": "ps_position"})
    season_pos = (tables["lineups"].groupby(["season", "player_id"])["position"].last()
                  .rename("lineup_position").reset_index())
    act = (dp.merge(ps, on=["season", "player_id"], how="left")
             .merge(season_pos, on=["season", "player_id"], how="left"))
    act["player_name"] = act["ps_name"]
    act["position"] = act["lineup_position"].fillna(act["ps_position"])
    act = act[act["season"].isin(exp["season"].unique())]

    both = exp.merge(act[["season", "overall_pick", "player_name"]], on=["season", "overall_pick"],
                     suffixes=("", "_engine"))
    variant = both[(both["player_name"] != both["player_name_engine"])
                   & (both["player_name"].map(surname) == both["player_name_engine"].map(surname))]
    known = variant[["season", "overall_pick"]].assign(
        column="player_name", reason="same player, different spelling (suffix or nickname)")
    return compare("draft picks vs draft_history_all_positions.csv", exp, act,
                   keys=["season", "overall_pick"],
                   values=["round", "round_pick", "draft_slot", "manager_key", "player_name", "position"],
                   known=known)


def check_transactions(tables: dict[str, pd.DataFrame], legacy: pd.DataFrame, cfg: dict) -> Comparison:
    """Legacy transactions_clean.csv: one row per transaction item.

    Matched on ESPN transaction id + player id + item type. The legacy Player
    column is not compared: it is scrambled in that file (one player id carries
    several names), so names always come from ESPN's player data instead.
    """
    from engine.normalize.moves import executed_moves

    lookup = name_to_key(cfg)
    exp = pd.DataFrame({
        "season": legacy["Season"].astype(int),
        "transaction_id": legacy["Transaction_ID"],
        "player_id": legacy["Player_ID"].astype(int),
        "item_type": legacy["Move"],
        "type": legacy["Type"],
        "scoring_period": legacy["Scoring_Period"].astype(int),
        "bid_amount": legacy["Bid_Amount"].astype(int),
        "manager_key": resolve_names(legacy["Initiating_Manager"], lookup),
    })
    tx = tables["transactions"]
    tx = tx[tx["season"].isin(exp["season"].unique())]
    act = executed_moves(tx)
    result = compare("transactions vs transactions_clean.csv", exp, act,
                     keys=["transaction_id", "player_id", "item_type"],
                     values=["season", "type", "scoring_period", "bid_amount", "manager_key"])

    # Diagnostics: where the differences come from.
    keys = ["transaction_id", "player_id", "item_type"]
    counted = act[keys].assign(counted_by_engine=True)
    all_rows = (tx.merge(exp[keys].assign(in_legacy=True), on=keys, how="left")
                  .merge(counted, on=keys, how="left"))
    for col in ("in_legacy", "counted_by_engine"):
        all_rows[col] = all_rows[col].fillna(False).astype(bool)
    grp = (all_rows.groupby(["type", "status", "item_type"], dropna=False)
                   .agg(espn_rows=("in_legacy", "size"), in_legacy=("in_legacy", "sum"),
                        counted_by_engine=("counted_by_engine", "sum"))
                   .reset_index())
    result.frames["by_espn_type_status"] = grp
    for _, g in grp[grp["in_legacy"] != grp["counted_by_engine"]].iterrows():
        result.examples.append(
            f"{g['type']}/{g['status']}/{g['item_type']}: {g['espn_rows']} ESPN rows, "
            f"legacy has {int(g['in_legacy'])}, engine counts {int(g['counted_by_engine'])}")

    # Legacy rows with no ESPN row at all: is the transaction id known under another item?
    missing = exp.merge(tx[keys], on=keys, how="left", indicator=True)
    missing = missing[missing["_merge"] == "left_only"].drop(columns="_merge")
    id_info = (tx.groupby("transaction_id")
                 .agg(espn_type=("type", "first"), espn_status=("status", "first"),
                      espn_items=("item_type", lambda x: ",".join(sorted(set(map(str, x))))))
                 .reset_index())
    missing = missing.merge(id_info, on="transaction_id", how="left")
    result.frames["legacy_rows_not_in_espn"] = missing
    summary = (missing.assign(id_in_espn=missing["espn_type"].notna())
                      .groupby(["season", "type", "item_type", "id_in_espn"]).size()
                      .rename("rows").reset_index())
    result.frames["legacy_rows_not_in_espn_summary"] = summary
    for _, g in summary.iterrows():
        result.examples.append(
            f"legacy-only {g['season']} {g['type']}/{g['item_type']}: {g['rows']} rows "
            f"({'id exists in ESPN data' if g['id_in_espn'] else 'id not in ESPN data'})")
    return result


def _name_norm(name: str) -> str:
    parts = "".join(c for c in str(name).lower() if c.isalnum() or c.isspace() or c == "/").split()
    return " ".join(p for p in parts if p not in NAME_SUFFIXES)


def attach_player_ids(legacy: pd.DataFrame, lineups: pd.DataFrame, players: pd.DataFrame,
                      keys: list[str], name_col: str = "player") -> pd.DataFrame:
    """Give legacy rows that only carry a player name a player_id, matching
    within `keys` (for example manager and season) against every name ESPN used
    for the players on those rosters: exact, then ignoring punctuation and
    suffixes, then by surname. Adds player_id and name_match (how it matched)."""
    cand = pd.concat([lineups[keys + ["player_id", "player_name"]],
                      lineups[keys + ["player_id"]].drop_duplicates().merge(
                          players[["player_id", "player_name"]], on="player_id")]).drop_duplicates()
    out = legacy.copy()
    out["player_id"] = pd.NA
    out["name_match"] = None
    for how, f in [("exact", lambda n: n), ("normalized", _name_norm), ("surname", surname)]:
        todo = out["player_id"].isna().to_numpy()
        c = cand.assign(_k=cand["player_name"].map(f))
        uniq = c.groupby(keys + ["_k"])["player_id"].agg(lambda x: x.iloc[0] if x.nunique() == 1 else pd.NA).reset_index()
        found = out.loc[todo, keys].assign(_k=out.loc[todo, name_col].map(f)).merge(uniq, on=keys + ["_k"], how="left")
        out.loc[todo, "player_id"] = found["player_id"].to_numpy()
        out.loc[todo & out["player_id"].notna().to_numpy(), "name_match"] = how
    return out


SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}
LEGACY_FREE_AGENTS = 500


def legacy_stats_universe(player_stats: pd.DataFrame) -> pd.DataFrame:
    """The players the legacy stats pull saw: every rostered player plus the
    first 500 free agents / waiver players by percent owned (espn-api
    free_agents(size=500)), skill positions only."""
    ps = player_stats.sort_values(["season", "pool_rank"], kind="stable")
    rostered = ps[ps["pool_status"] == "ONTEAM"]
    free = ps[ps["pool_status"] != "ONTEAM"].groupby("season", sort=False).head(LEGACY_FREE_AGENTS)
    out = pd.concat([rostered, free])
    return out[out["position"].isin(SKILL_POSITIONS)]


def check_player_stats(tables: dict[str, pd.DataFrame], legacy: pd.DataFrame, cfg: dict) -> Comparison:
    """Legacy espn_player_stats_season.csv (pull_espn_stats.py, rerun 2026-09-29
    for 2020-2025): season fantasy totals per player.

    Known legacy differences, excused by pattern:
    - espn-api rounded the season average to 2 decimals before dividing, so
      players averaging under about 0.1 points got a games count off by one or
      more; excused where the legacy count equals total / rounded average
    - averages are compared within half a cent (half-cent rounding ties)
    - a later-season position, as in the lineups check
    Players with no games at the edge of the 500-free-agent cutoff can differ
    (ESPN breaks ownership ties its own way); they carry no stats and affect no
    metric, so they are set aside and counted."""
    exp = pd.DataFrame({
        "season": legacy["season"].astype(int), "player_id": legacy["player_id"].astype(int),
        "player_name": legacy["player_name"], "position": legacy["position"],
        "total_points": legacy["total_ppr"].astype(float), "games": legacy["games_played"].astype(int),
        "avg_points": legacy["ppr_per_game"].astype(float),
    })
    ps = tables["player_stats"]
    act = legacy_stats_universe(ps[ps["season"].isin(exp["season"].unique())])
    keys = ["season", "player_id"]
    in_act = exp[keys].merge(act[keys].assign(_x=True), on=keys, how="left")["_x"].eq(True).to_numpy()
    in_exp = act[keys].merge(exp[keys].assign(_x=True), on=keys, how="left")["_x"].eq(True).to_numpy()
    edge_exp = ~in_act & (exp["games"] == 0).to_numpy()
    edge_act = ~in_exp & (act["games"] == 0).to_numpy()
    exp, act = exp[~edge_exp], act[~edge_act]

    both = exp.merge(act, on=keys, suffixes=("", "_e"))
    rounded = both["avg_points_e"].round(2)
    legacy_games = (both["total_points_e"] / rounded).where(rounded > 0).round().fillna(0).astype(int)
    games_known = both.loc[(both["games"] != both["games_e"]) & (both["games"] == legacy_games), keys].assign(
        column="games", reason="espn-api divided by the average rounded to 2 decimals (tiny averages)")
    other = ps[["season", "player_id", "position"]].rename(columns={"season": "other_season"})
    pos = both[both["position"] != both["position_e"]][keys + ["position"]].merge(other, on=["player_id", "position"])
    pos_known = pos[pos["other_season"] != pos["season"]][keys].drop_duplicates().assign(
        column="position", reason="legacy used a later-season position; the engine keeps that season's ESPN position")
    r = compare("player stats vs espn_player_stats_season.csv", exp, act, keys=keys,
                values=["player_name", "position", "total_points", "games", "avg_points"], tolerance=0.0051,
                known=pd.concat([games_known, pos_known], ignore_index=True))
    n = int(edge_exp.sum() + edge_act.sum())
    if n:
        r.known["no-games players at the 500-free-agent cutoff (ESPN tie order); no effect on any metric"] = n
    return r

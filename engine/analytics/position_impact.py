"""Position impact: how much each position decides games, and the D/ST deep dive.

Every section works on four standardized inputs, so the same code runs on the
canonical tables (engine) and on the legacy files (verification):

    games     one row per game: season, week, label, is_regular, manager_a,
              manager_b, score_a, score_b (regular season and winners-bracket
              games only; consolation weeks never count)
    lineups   season, week, manager_key, player_key, player_name, position,
              slot, started, points (the weeks that count)
    picks     season, manager_key, round, overall_pick, player_key,
              player_name, position (every draft pick, every position)
    active    season, manager_key: the seasons each manager was in the league

Sections (each a function below):
    flips             remove one position's started points from both teams in
                      every game; the winner flips if the adjusted scores give
                      another result (a tie counts as a flip)
    consistency       week-to-week coefficient of variation per player-season
    nth pick          each manager's Nth pick at a position, N = the number of
                      starting slots at that position (Preach: 1 QB/TE/K/D/ST,
                      2 RB/WR)
    draft vs waiver   PPG of that Nth pick by round, against the PPG of players
                      the manager never drafted
    draft order       PPG by league-wide order of that Nth pick within a season
    draft capital     the round of the Nth pick per manager and season
    correlation       position PPG and Nth-pick round against regular-season win%
    acquisition       each manager's points at a position by how the player got
                      there: drafted, waiver/free agent, or traded
    D/ST deep dive    every game with and without D/ST, per-manager records and
                      flipped games, and whether each season's playoff field,
                      playoff games, and champion would change
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

POSITIONS = ["QB", "RB", "WR", "TE", "K", "D/ST"]
REAL_GAME_EXCLUDED_SLOT = "IR"
MIN_CV_STARTS = 4
BOX_MIN_WEEKS = 5
ROUND_NAMES_FROM_FINAL = ["Championship", "Semifinal", "Quarterfinal", "First Round"]


# ---------------------------------------------------------------- helpers

def nth_pick_rule(slots: list[str], positions: list[str] = POSITIONS) -> dict[str, int]:
    """N per position: the number of starting slots that take only that
    position (a flex slot does not add one)."""
    return {p: max(1, sum(1 for s in slots if s == p)) for p in positions}


def playoff_labels(games: pd.DataFrame) -> dict[tuple[int, int], str]:
    """(season, week) -> 'Week N' or the round name, counted back from the final."""
    out = {}
    for season, g in games.groupby("season"):
        reg_weeks = sorted(g.loc[g["is_regular"], "week"].unique())
        for w in reg_weeks:
            out[(int(season), int(w))] = f"Week {w}"
        po = sorted(g.loc[~g["is_regular"], "week"].unique())
        for i, w in enumerate(po):
            back = len(po) - 1 - i
            out[(int(season), int(w))] = ROUND_NAMES_FROM_FINAL[min(back, len(ROUND_NAMES_FROM_FINAL) - 1)]
    return out


def _pearson(xs, ys) -> float:
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = xs.sum() / n, ys.sum() / n
    cov = ((xs - mx) * (ys - my)).sum()
    sx, sy = (((xs - mx) ** 2).sum()) ** 0.5, (((ys - my) ** 2).sum()) ** 0.5
    return float(cov / (sx * sy)) if sx and sy else 0.0


def _linreg(xs, ys) -> tuple[float, float]:
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    n = len(xs)
    if n < 2:
        return 0.0, 0.0
    mx, my = xs.sum() / n, ys.sum() / n
    denom = ((xs - mx) ** 2).sum()
    slope = float(((xs - mx) * (ys - my)).sum() / denom) if denom else 0.0
    return slope, float(my - slope * mx)


def _quantile(sorted_vals: list[float], q: float) -> float:
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = q * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def pos_started(lineups: pd.DataFrame) -> dict:
    """(season, week, manager_key, position) -> started points."""
    s = lineups[lineups["started"]]
    return s.groupby(["season", "week", "manager_key", "position"])["points"].sum().to_dict()


# ---------------------------------------------------------------- flips

def flip_games(games: pd.DataFrame, started: dict, pos: str) -> pd.DataFrame:
    """Every game with one position's started points removed from both sides."""
    g = games.copy()
    g["pos_a"] = [started.get((s, w, m, pos), 0.0) for s, w, m in zip(g["season"], g["week"], g["manager_a"])]
    g["pos_b"] = [started.get((s, w, m, pos), 0.0) for s, w, m in zip(g["season"], g["week"], g["manager_b"])]
    g["adj_a"] = g["score_a"] - g["pos_a"]
    g["adj_b"] = g["score_b"] - g["pos_b"]
    g["actual_winner"] = np.where(g["score_a"] > g["score_b"], g["manager_a"], g["manager_b"])
    g["adj_winner"] = np.where(g["adj_a"] > g["adj_b"], g["manager_a"],
                               np.where(g["adj_b"] > g["adj_a"], g["manager_b"], "TIE"))
    g["flipped"] = g["adj_winner"] != g["actual_winner"]
    return g


def flip_summary(games: pd.DataFrame, started: dict, positions: list[str] = POSITIONS):
    """(flip_rates, season_flip_rate, net_impact) tables."""
    rates, seasons, net = [], [], []
    for pos in positions:
        f = flip_games(games, started, pos)
        n = len(f)
        flips = int(f["flipped"].sum())
        rates.append({"position": pos, "flips": flips, "total": n, "pct": round(flips / n * 100, 1) if n else 0.0})
        for season, g in f.groupby("season"):
            seasons.append({"position": pos, "season": int(season),
                            "pct": round(g["flipped"].sum() / len(g) * 100, 1)})
        fl = f[f["flipped"]]
        gained, lost = defaultdict(int), defaultdict(int)
        for r in fl.itertuples(index=False):
            for side in (r.manager_a, r.manager_b):
                won_actual, won_adj = r.actual_winner == side, r.adj_winner == side
                if won_adj and not won_actual:
                    gained[side] += 1
                elif won_actual and not won_adj:
                    lost[side] += 1
        for m in sorted(set(games["manager_a"]) | set(games["manager_b"])):
            net.append({"position": pos, "manager_key": m, "gained": gained[m], "lost": lost[m],
                        "net": gained[m] - lost[m]})
    return pd.DataFrame(rates), pd.DataFrame(seasons), pd.DataFrame(net)


# ---------------------------------------------------------------- consistency

def consistency(lineups: pd.DataFrame, positions: list[str] = POSITIONS, min_starts: int = MIN_CV_STARTS) -> pd.DataFrame:
    s = lineups[lineups["started"] & (lineups["slot"] != REAL_GAME_EXCLUDED_SLOT)]
    rows = []
    cvs = defaultdict(list)
    for (season, mk, pk, pos), g in s.groupby(["season", "manager_key", "player_key", "position"]):
        pts = g["points"].tolist()
        if len(pts) < min_starts:
            continue
        mean = sum(pts) / len(pts)
        if mean <= 0:
            continue
        var = sum((p - mean) ** 2 for p in pts) / (len(pts) - 1)
        cvs[pos].append(var ** 0.5 / mean)
    for pos in positions:
        v = cvs.get(pos, [])
        rows.append({"position": pos, "avg_cv": round(sum(v) / len(v), 3) if v else None, "sample": len(v)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- draft

def nth_picks(picks: pd.DataFrame, nth: dict[str, int]) -> pd.DataFrame:
    """Each manager's Nth pick at each position per season (round order)."""
    p = picks[picks["position"].isin(nth)].sort_values(["season", "manager_key", "position", "round", "player_name"],
                                                       kind="stable")
    p = p.assign(k=p.groupby(["season", "manager_key", "position"]).cumcount() + 1)
    return p[p["k"] == p["position"].map(nth)].drop(columns="k")


def _real_weeks(lineups: pd.DataFrame) -> pd.DataFrame:
    return lineups[lineups["started"] & (lineups["slot"] != REAL_GAME_EXCLUDED_SLOT)]


def draft_vs_waiver(lineups: pd.DataFrame, picks: pd.DataFrame, nth: dict[str, int],
                    hidden: set[str] = frozenset(), all_drafted: bool = False) -> pd.DataFrame:
    """PPG by round of each manager's Nth pick (or, all_drafted=True, of every
    pick at the position), and the PPG of players the manager never drafted.
    Hidden managers are left out of these averages, as in legacy."""
    real = _real_weeks(lineups)
    real = real[~real["manager_key"].isin(hidden)]
    ever = picks.groupby(["season", "manager_key", "position"])["player_key"].apply(set).to_dict()
    chosen = picks[picks["position"].isin(nth)] if all_drafted else nth_picks(picks, nth)
    chosen = chosen[~chosen["manager_key"].isin(hidden)]
    rows = []
    for pos in nth:
        rp = real[real["position"] == pos]
        c = chosen[chosen["position"] == pos][["season", "manager_key", "player_key", "round"]]
        d = rp.merge(c, on=["season", "manager_key", "player_key"])
        by_round = d.groupby("round")["points"].agg(["sum", "size"])
        drafted_sets = [ever.get((s, m, pos), set()) for s, m in zip(rp["season"], rp["manager_key"])]
        never = rp[[pk not in ds for pk, ds in zip(rp["player_key"], drafted_sets)]]
        tot_pts, tot_wk = float(by_round["sum"].sum()), int(by_round["size"].sum())
        for rnd, r in by_round.iterrows():
            rows.append({"position": pos, "round": int(rnd), "ppg": round(r["sum"] / r["size"], 2), "weeks": int(r["size"]),
                         "overall_drafted_ppg": round(tot_pts / tot_wk, 2) if tot_wk else 0,
                         "overall_drafted_weeks": tot_wk,
                         "waiver_ppg": round(never["points"].sum() / len(never), 2) if len(never) else 0,
                         "waiver_weeks": len(never), "nth_pick": nth[pos]})
    return pd.DataFrame(rows)


def draft_order(lineups: pd.DataFrame, picks: pd.DataFrame, nth: dict[str, int],
                hidden: set[str] = frozenset()) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(by order: ppg and weeks; box plot per order with 5+ real weeks)."""
    real = _real_weeks(lineups)
    np_ = nth_picks(picks[~picks["manager_key"].isin(hidden)], nth)
    np_ = np_.assign(order=np_.sort_values(["season", "position", "overall_pick"]).groupby(["season", "position"]).cumcount() + 1)
    rows, boxes = [], []
    for pos in nth:
        c = np_[np_["position"] == pos][["season", "manager_key", "player_key", "order", "overall_pick"]]
        d = real[real["position"] == pos].merge(c, on=["season", "manager_key", "player_key"])
        d = d.sort_values(["season", "overall_pick", "week"], kind="stable")
        for order, g in d.groupby("order"):
            total = 0.0
            for v in g["points"]:
                total += float(v)
            rows.append({"position": pos, "order": int(order), "ppg": round(total / len(g), 2), "weeks": len(g)})
            if len(g) >= BOX_MIN_WEEKS:
                sv = sorted(g["points"].tolist())
                boxes.append({"position": pos, "order": int(order), "min": round(sv[0], 1),
                              "q1": round(_quantile(sv, 0.25), 1), "median": round(_quantile(sv, 0.5), 1),
                              "q3": round(_quantile(sv, 0.75), 1), "max": round(sv[-1], 1), "n": len(sv)})
    return pd.DataFrame(rows), pd.DataFrame(boxes)


def draft_capital(picks: pd.DataFrame, active: pd.DataFrame, nth: dict[str, int], seasons: list[int],
                  hidden: set[str] = frozenset()) -> pd.DataFrame:
    """Round of each manager's Nth pick per season: a round, 'streamed' (no Nth
    pick that year), or 'not_in_league'; plus the career average round."""
    np_ = nth_picks(picks, nth).set_index(["position", "season", "manager_key"])["round"]
    act = set(zip(active["season"], active["manager_key"]))
    managers = sorted(set(active["manager_key"]))
    rows = []
    for pos in nth:
        for m in managers:
            rounds = []
            for s in seasons:
                if (s, m) not in act:
                    val = "not_in_league"
                elif (pos, s, m) in np_.index:
                    val = int(np_[(pos, s, m)])
                    rounds.append(val)
                else:
                    val = None
                rows.append({"position": pos, "manager_key": m, "season": s, "round": val})
            avg = round(sum(rounds) / len(rounds), 1) if rounds else None
            for r in rows[-len(seasons):]:
                r["career_avg_round"] = avg
                r["years_drafted"] = len(rounds)
                r["years_streamed"] = sum(1 for s in seasons if (s, m) in act) - len(rounds)
                r["hidden"] = m in hidden
    return pd.DataFrame(rows)


def correlation(standings: pd.DataFrame, started: dict, picks: pd.DataFrame, nth: dict[str, int],
                from_rounded: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Position PPG (started points per week with a start) and Nth-pick round
    against regular-season win%. standings: season, manager_key, wins, games.
    from_rounded=True fits on the displayed values (PPG to 2 places, win% to
    4), as generate_dst_impact.py did. Returns (points, stats)."""
    np_ = nth_picks(picks, nth).set_index(["position", "season", "manager_key"])["round"]
    ppg = defaultdict(lambda: [0.0, 0])
    for (season, week, mk, pos), pts in started.items():
        ppg[(pos, int(season), mk)][0] += pts
        ppg[(pos, int(season), mk)][1] += 1
    pts_rows, stat_rows = [], []
    for pos in nth:
        rows = []
        for r in standings.itertuples(index=False):
            key = (pos, int(r.season), r.manager_key)
            if key not in ppg or ppg[key][1] == 0:
                continue
            rnd = np_.get(key)
            rows.append({"position": pos, "season": int(r.season), "manager_key": r.manager_key,
                         "win_pct": r.wins / r.games, "ppg": ppg[key][0] / ppg[key][1],
                         "drafted_round": int(rnd) if rnd is not None and not pd.isna(rnd) else None})
        pts_rows += rows
        if from_rounded:
            rows = [dict(r, ppg=round(r["ppg"], 2), win_pct=round(r["win_pct"], 4)) for r in rows]
        xs, ys = [r["ppg"] for r in rows], [r["win_pct"] for r in rows]
        dr = [r for r in rows if r["drafted_round"] is not None]
        r1 = _pearson(xs, ys)
        s1, i1 = _linreg(xs, ys)
        r2 = _pearson([r["drafted_round"] for r in dr], [r["win_pct"] for r in dr]) if len(dr) > 1 else 0.0
        s2, i2 = _linreg([r["drafted_round"] for r in dr], [r["win_pct"] for r in dr]) if len(dr) > 1 else (0.0, 0.0)
        stat_rows.append({"position": pos, "ppg_r": round(r1, 3), "ppg_r2": round(r1 ** 2, 4), "ppg_slope": s1,
                          "ppg_intercept": i1, "ppg_n": len(rows), "round_r": round(r2, 3), "round_r2": round(r2 ** 2, 4),
                          "round_slope": s2, "round_intercept": i2, "round_n": len(dr)})
    return pd.DataFrame(pts_rows), pd.DataFrame(stat_rows)


def standings_from_games(games: pd.DataFrame) -> pd.DataFrame:
    """Regular-season wins and games per manager-season from the games table."""
    g = games[games["is_regular"]]
    rows = []
    for r in g.itertuples(index=False):
        rows.append((r.season, r.manager_a, float(r.score_a > r.score_b)))
        rows.append((r.season, r.manager_b, float(r.score_b > r.score_a)))
    d = pd.DataFrame(rows, columns=["season", "manager_key", "win"])
    return d.groupby(["season", "manager_key"], sort=False).agg(wins=("win", "sum"), games=("win", "size")).reset_index()


# ---------------------------------------------------------------- acquisition

def acquisition_by_week(lineups: pd.DataFrame, waiver_stints: pd.DataFrame, trade_in: pd.DataFrame) -> pd.DataFrame:
    """Each rostered week's points by how the player reached that roster: inside
    a waiver stint -> waiver; otherwise the latest trade into the team (traded)
    or else the draft (drafted). Sums per season, manager, and position.
    trade_in: season, manager_key, player_key, week (first week on the new team)."""
    lu = lineups[lineups["slot"] != REAL_GAME_EXCLUDED_SLOT][["season", "week", "manager_key", "player_key",
                                                              "position", "points"]].copy()
    ws = waiver_stints[["season", "manager_key", "player_key", "start_week", "end_week"]]
    m = lu.reset_index().merge(ws, on=["season", "manager_key", "player_key"], how="left")
    in_w = (m["week"] >= m["start_week"]) & (m["week"] < m["end_week"])
    waiver_rows = set(m.loc[in_w, "index"])
    lu["source"] = np.where(lu.index.isin(waiver_rows), "waiver", "drafted")
    t = lu.reset_index().merge(trade_in.rename(columns={"week": "trade_week"}),
                               on=["season", "manager_key", "player_key"], how="left")
    traded_rows = set(t.loc[(t["trade_week"] <= t["week"]), "index"])
    lu.loc[lu.index.isin(traded_rows) & (lu["source"] != "waiver"), "source"] = "traded"
    out = lu.pivot_table(index=["season", "manager_key", "position"], columns="source", values="points",
                         aggfunc="sum", fill_value=0.0).reset_index()
    for c in ("drafted", "waiver", "traded"):
        if c not in out:
            out[c] = 0.0
    return out


def acquisition_summary(acq: pd.DataFrame, positions: list[str] = POSITIONS,
                        hidden: set[str] = frozenset()) -> pd.DataFrame:
    """Per position and manager (and a league total row, manager_key None)."""
    a = acq[acq["position"].isin(positions)]
    per = a.groupby(["position", "manager_key"])[["drafted", "waiver", "traded"]].sum().reset_index()
    per["hidden"] = per["manager_key"].isin(hidden)
    league = per[~per["hidden"]].groupby("position")[["drafted", "waiver", "traded"]].sum().reset_index()
    league["manager_key"] = None
    league["hidden"] = False
    return pd.concat([per, league], ignore_index=True)


# ---------------------------------------------------------------- D/ST deep dive

def dst_games(games: pd.DataFrame, started: dict, labels: dict) -> pd.DataFrame:
    f = flip_games(games, started, "D/ST")
    f["label"] = [labels.get((s, w), f"Week {w}") for s, w in zip(f["season"], f["week"])]
    f["adj_a"] = f["adj_a"].round(2)
    f["adj_b"] = f["adj_b"].round(2)
    # flips are judged on the rounded adjusted scores, as displayed
    f["adj_winner"] = np.where(f["adj_a"] > f["adj_b"], f["manager_a"],
                               np.where(f["adj_b"] > f["adj_a"], f["manager_b"], "TIE"))
    f["flipped"] = f["adj_winner"] != f["actual_winner"]
    return f


def dst_managers(dg: pd.DataFrame, lineups_all: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(records per manager, flipped games per manager)."""
    stats = defaultdict(lambda: {"games": 0, "actual_w": 0, "actual_l": 0, "adj_w": 0, "adj_l": 0, "flipped": 0})
    flips = []
    for g in dg.itertuples(index=False):
        for side, other, sc, adj, osc, oadj in ((g.manager_a, g.manager_b, g.score_a, g.adj_a, g.score_b, g.adj_b),
                                                (g.manager_b, g.manager_a, g.score_b, g.adj_b, g.score_a, g.adj_a)):
            st = stats[side]
            st["games"] += 1
            won, won_adj = g.actual_winner == side, g.adj_winner == side
            st["actual_w" if won else "actual_l"] += 1
            if won_adj:
                st["adj_w"] += 1
            elif g.adj_winner != "TIE":
                st["adj_l"] += 1
            if g.flipped:
                st["flipped"] += 1
                direction = "gained_win" if won_adj and not won else ("lost_win" if won and not won_adj else "tie")
                flips.append({"manager_key": side, "season": g.season, "week": g.week, "label": g.label,
                              "opponent": other, "my_score": round(sc, 2), "opp_score": round(osc, 2),
                              "my_adj": adj, "opp_adj": oadj, "direction": direction})
    dst = lineups_all[(lineups_all["position"] == "D/ST") & lineups_all["started"]]
    ppg = dst.groupby("manager_key")["points"].agg(["sum", "size"])
    rows = [{"manager_key": m, **v, "dst_ppg": round(ppg.loc[m, "sum"] / ppg.loc[m, "size"], 2) if m in ppg.index else 0}
            for m, v in stats.items()]
    return pd.DataFrame(rows), pd.DataFrame(flips)


def season_playoffs(dg: pd.DataFrame, qualify) -> pd.DataFrame:
    """Per season: the playoff field with and without D/ST (qualify(season,
    standings) -> ordered list of qualifiers; standings rows: manager_key,
    wins, games, points), field changes, real playoff games that flip, and
    whether the champion's run survives."""
    rows = []
    for season, g in dg.groupby("season"):
        if not (g["label"] == "Championship").any():
            continue                      # a season still in progress has no field to compare
        reg = g[g["is_regular"]]
        st_a, st_e = defaultdict(lambda: [0, 0, 0.0]), defaultdict(lambda: [0, 0, 0.0])
        for r in reg.itertuples(index=False):
            for side, sc, adj, osc, oadj in ((r.manager_a, r.score_a, r.adj_a, r.score_b, r.adj_b),
                                             (r.manager_b, r.score_b, r.adj_b, r.score_a, r.adj_a)):
                for st, mine, theirs in ((st_a, sc, osc), (st_e, adj, oadj)):
                    st[side][1] += 1
                    st[side][2] += mine
                    if mine > theirs:
                        st[side][0] += 1
        to_df = lambda st: pd.DataFrame([{"manager_key": m, "wins": v[0], "games": v[1], "points": v[2]}
                                         for m, v in st.items()])
        actual, adj = qualify(int(season), to_df(st_a)), qualify(int(season), to_df(st_e))
        po = g[~g["is_regular"]]
        flips = po[po["flipped"]]
        champ_game = po[po["label"] == "Championship"]
        champion = champ_game["actual_winner"].iloc[0] if len(champ_game) else None
        path = po[(po["manager_a"] == champion) | (po["manager_b"] == champion)] if champion else po.iloc[:0]
        flipped_path = path[path["flipped"]]
        rows.append({"season": int(season), "actual_field": actual, "adj_field": adj,
                     "gained": [m for m in adj if m not in actual], "lost": [m for m in actual if m not in adj],
                     "playoff_flips": flips[["label", "manager_a", "manager_b", "score_a", "score_b", "adj_a", "adj_b",
                                             "actual_winner", "adj_winner"]].to_dict("records"),
                     "actual_champion": champion, "champion_changed": bool(champion) and len(flipped_path) > 0,
                     "champion_eliminated_round": flipped_path["label"].iloc[0] if len(flipped_path) else None})
    cols = ["season", "actual_field", "adj_field", "gained", "lost", "playoff_flips", "actual_champion",
            "champion_changed", "champion_eliminated_round"]
    return pd.DataFrame(rows, columns=cols).astype({"champion_eliminated_round": object}).replace({np.nan: None})


# ---------------------------------------------------------------- engine inputs

def engine_inputs(tables: dict[str, pd.DataFrame], waiver_stints: pd.DataFrame, trade_stints: pd.DataFrame) -> dict:
    """The four inputs (plus acquisition, N per position, seasons) from the
    canonical tables: counted games (no byes, no consolation), bracket-week
    lineups, every draft pick, players keyed by ESPN id."""
    from engine.analytics import lineups as lineups_mod
    from engine.analytics import weeks as weeks_mod

    cg = weeks_mod.counted_games(tables)
    rows = []
    for (season, week, game_id), pair in cg.groupby(["season", "week", "game_id"], sort=True):
        if len(pair) != 2:
            continue
        a, b = pair.iloc[-1], pair.iloc[0]
        rows.append({"season": int(season), "week": int(week), "is_regular": not bool(a["is_playoff_week"]),
                     "manager_a": a["manager_key"], "manager_b": b["manager_key"],
                     "score_a": float(a["points"]), "score_b": float(b["points"])})
    games = pd.DataFrame(rows)
    lu = weeks_mod.bracket_lineups(tables).assign(player_key=lambda d: d["player_id"])
    pos = tables["player_seasons"][["season", "player_id", "player_name", "position"]]
    dp = tables["draft_picks"].merge(pos, on=["season", "player_id"], how="left")
    picks = pd.DataFrame({"season": dp["season"].astype(int), "manager_key": dp["manager_key"],
                          "round": dp["round"].astype(int), "overall_pick": dp["overall_pick"].astype(int),
                          "player_key": dp["player_id"], "player_name": dp["player_name"], "position": dp["position"]})
    active = picks[["season", "manager_key"]].drop_duplicates()
    slots = lineups_mod.lineup_slots(tables["lineups"])
    nth = nth_pick_rule(slots[max(slots)])
    ws = waiver_stints.rename(columns={"player_id": "player_key"})
    ti = trade_stints.rename(columns={"player_id": "player_key", "scoring_period": "week"})[
        ["season", "manager_key", "player_key", "week"]]
    acq = acquisition_by_week(lu, ws, ti)
    return {"games": games, "lineups": lu, "picks": picks, "active": active, "acquisition": acq, "nth": nth,
            "seasons": sorted(int(s) for s in picks["season"].unique())}


def playoff_qualifier(tables: dict[str, pd.DataFrame], cutoff: int | None):
    """qualify(season, standings) -> ordered qualifiers: each division's best
    team (win%, then points), then the best other teams, up to the cutoff
    (league.yaml analysis.playoff_odds.cutoff, else ESPN's playoff team count)."""
    seasons = tables["seasons"].set_index("season")["playoff_team_count"]
    div = tables["teams"].set_index(["season", "manager_key"])["division_id"]

    def qualify(season: int, st: pd.DataFrame) -> list:
        n = int(cutoff or seasons.get(season, 0))
        st = st.assign(pct=st["wins"] / st["games"]).sort_values(["pct", "points"], ascending=False, kind="stable")
        st["div"] = [div.get((season, m)) for m in st["manager_key"]]
        winners = st.drop_duplicates("div")["manager_key"].tolist() if st["div"].nunique() > 1 else []
        rest = [m for m in st["manager_key"] if m not in winners]
        return (winners + rest)[:n] if winners else st["manager_key"].head(n).tolist()
    return qualify


def analyze_position_impact(tables: dict[str, pd.DataFrame], analysis: dict[str, pd.DataFrame],
                            exclude_managers: set[str] = frozenset(), cutoff: int | None = None) -> dict[str, pd.DataFrame]:
    if "waiver_stints" not in analysis or "trade_stints" not in analysis:
        return {}
    import json

    inp = engine_inputs(tables, analysis["waiver_stints"], analysis["trade_stints"])
    games, lu, picks, nth = inp["games"], inp["lineups"], inp["picks"], inp["nth"]
    started = pos_started(lu)
    rates, season_rates, net = flip_summary(games, started)
    net["hidden"] = net["manager_key"].isin(exclude_managers)
    dvw = draft_vs_waiver(lu, picks, nth, exclude_managers)
    order, box = draft_order(lu, picks, nth, exclude_managers)
    cap = draft_capital(picks, inp["active"], nth, inp["seasons"], exclude_managers)
    corr_pts, corr_stats = correlation(standings_from_games(games), started, picks, nth)
    corr_pts["hidden"] = corr_pts["manager_key"].isin(exclude_managers)
    acq = acquisition_summary(inp["acquisition"], hidden=exclude_managers)
    dg = dst_games(games, started, playoff_labels(games))
    mstats, mflips = dst_managers(dg, lu)
    mstats["hidden"] = mstats["manager_key"].isin(exclude_managers)
    po = season_playoffs(dg, playoff_qualifier(tables, cutoff))
    for c in ("actual_field", "adj_field", "gained", "lost", "playoff_flips"):
        po[c] = po[c].map(lambda v: json.dumps(v, default=float))
    return {
        "position_flip_rates": rates, "position_season_flips": season_rates, "position_net_impact": net,
        "position_consistency": consistency(lu), "position_draft_vs_waiver": dvw, "position_draft_order": order,
        "position_draft_order_box": box, "position_draft_capital": cap.astype({"round": object}).assign(
            round=lambda d: d["round"].map(lambda v: None if v is None else str(v))),
        "position_correlation_points": corr_pts, "position_correlation": corr_stats, "position_acquisition": acq,
        "dst_games": dg, "dst_managers": mstats, "dst_flipped_games": mflips, "dst_season_playoffs": po,
    }

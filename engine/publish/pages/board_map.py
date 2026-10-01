"""The draft board performance map on managers.html (inline HEATMAP_DATA).

Per visible manager (rules recovered from the page, which equals
generate_draft_heatmap.py's output, `draft/draft_heatmap.json`):
    board         {"round_slot": {round, slot, avg_surplus, n_seasons, picks[]}}: every pick the
                  manager made from that round and draft slot; avg_surplus is the mean of the
                  picks' surplus at 2 places, to 3 places (as `draft.heatmap`)
    tiers         per round tier (draft.HEATMAP_TIERS): the manager's and the league's mean
                  surplus and the manager's pick count
    positions     per skill position: the same, plus the share of picks with positive
                  surplus (hit_rate) for the manager and the league
    best_picks    the 3 highest surplus picks
    worst_picks   the 3 lowest surplus picks in the early and middle tiers (rounds 1-7):
                  late-round misses cost little and are left out
    career_wtd_avg, total_picks   the career grade (draft_career_grades.avg_surplus) and pick count

Surplus here is the unweighted surplus (the grades use the round-weighted one).
League averages count every pick in the table, excluded managers' included
(they are only hidden). Finished seasons only, as the page shows today.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.analytics import draft as draft_mod

SKILL = ["RB", "WR", "QB", "TE"]
PICKS_LISTED = 3
WORST_LAST_ROUND = next(hi for name, lo, hi in draft_mod.TIERS if name == "Middle")


def _r(x, n: int) -> float:
    return round(float(x), n)


def _cell_avg(s: pd.Series) -> float:
    return _r(np.mean([round(float(x), 2) for x in s]), 3)


def _pick(r) -> dict:
    return {"season": int(r.season), "round": int(r.round), "pick": int(r.overall_pick), "player": r.player_name,
            "pos": r.position, "surplus": _r(r.surplus, 2), "prv": _r(r.actual_prv, 2)}


def board_map_view(sur: pd.DataFrame, career: pd.DataFrame, seasons: list[int], hidden: set[str], names) -> dict:
    """HEATMAP_DATA from a draft_surplus table (any mode) and draft_career_grades."""
    s = sur[sur["season"].isin(seasons)]
    grades = career.set_index("manager_key")["avg_surplus"]
    tier_of = lambda rnd: next((n for n, lo, hi in draft_mod.HEATMAP_TIERS if lo <= rnd <= hi), None)
    s = s.assign(_tier=s["round"].map(tier_of))
    league_t = s.groupby("_tier")["surplus"].mean()
    league_p = s.groupby("position")["surplus"].mean()
    league_h = s.assign(_hit=s["surplus"] > 0).groupby("position")["_hit"].mean()
    out = {}
    for key, d in sorted(s[~s["manager_key"].isin(hidden)].groupby("manager_key"), key=lambda kv: names(kv[0])):
        board = {}
        for (rnd, slot), c in d.sort_values(["round", "draft_slot", "season"]).groupby(["round", "draft_slot"]):
            board[f"{int(rnd)}_{int(slot)}"] = {
                "round": int(rnd), "slot": int(slot), "avg_surplus": _cell_avg(c["surplus"]), "n_seasons": int(len(c)),
                "picks": [{"season": int(r.season), "player": r.player_name, "pos": r.position,
                           "surplus": _r(r.surplus, 2), "prv": _r(r.actual_prv, 2), "exp_prv": _r(r.expected_prv, 2),
                           "games": int(r.games), "zeroed": int(bool(r.zeroed))} for r in c.itertuples()]}
        tiers = {}
        for name, lo, hi in draft_mod.HEATMAP_TIERS:
            sel = d[d["_tier"] == name]
            tiers[name] = {"mgr_avg": _r(sel["surplus"].mean(), 3) if len(sel) else None,
                           "league_avg": _r(league_t[name], 3) if name in league_t else None, "n_picks": int(len(sel))}
        positions = {}
        for p in [x for x in SKILL if x in league_p]:
            sel = d[d["position"] == p]
            positions[p] = {"mgr_avg": _r(sel["surplus"].mean(), 3) if len(sel) else None,
                            "league_avg": _r(league_p[p], 3), "n_picks": int(len(sel)),
                            "hit_rate": _r((sel["surplus"] > 0).mean(), 3) if len(sel) else None,
                            "league_hit": _r(league_h[p], 3)}
        best = d.sort_values("surplus", ascending=False, kind="stable").head(PICKS_LISTED)
        worst = d[d["round"] <= WORST_LAST_ROUND].sort_values("surplus", kind="stable").head(PICKS_LISTED)
        g = grades.get(key)
        out[names(key)] = {"board": board, "tiers": tiers, "positions": positions,
                           "best_picks": [_pick(r) for r in best.itertuples()],
                           "worst_picks": [_pick(r) for r in worst.itertuples()],
                           "career_wtd_avg": None if g is None or pd.isna(g) else float(g),
                           "total_picks": int(len(d))}
    return out

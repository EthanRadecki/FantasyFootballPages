"""Shared inputs for the draft page publishers (PR A5).

The Stage A checks of the draft pages feed their view builders the draft
analysis rerun in legacy mode, exactly as `analyze --verify` runs it
(engine/legacy_draft.py): the legacy stats files, ESPN's pick numbering and
the hand-kept zero lists. The run is memoized per build, so the four draft
publishers share one.
"""

from __future__ import annotations

from engine.analytics import draft as draft_mod
from engine.analytics.weeks import live_seasons
from engine.config import excluded_manager_keys
from engine.legacy_draft import legacy_stats, legacy_zeroes


def legacy_draft(ctx) -> dict:
    """analyze_draft in legacy mode, with the inputs `verify_draft` uses."""
    def run():
        tables, golden = ctx.tables, ctx.golden
        stats = legacy_stats(golden)
        dp = tables["draft_picks"]
        live = live_seasons(tables)
        dp_live = dp[dp["season"].isin(live)][["season", "overall_pick", "player_id"]]
        injury, name_miss, hit_zero, _ = legacy_zeroes({**golden, "draft_picks_2026": dp_live}, stats)
        return draft_mod.analyze_draft(tables, excluded_manager_keys(ctx.cfg), legacy_mode=True,
                                       legacy_universe=stats, force_zero=injury, hit_force_zero=hit_zero,
                                       no_stats=name_miss)
    return ctx.memo("legacy_draft", run)


def player_names(ctx) -> dict:
    """(season, player_id) -> the player's name that season, as ESPN listed it."""
    def run():
        ps = ctx.tables["player_seasons"]
        return {(int(s), int(p)): n for s, p, n in zip(ps["season"], ps["player_id"], ps["player_name"])}
    return ctx.memo("draft_player_names", run)


def draft_method(rounds: int | None = None) -> dict:
    """The draft value method's constants (engine/analytics/draft.py), published with the draft pages so
    their method notes state the rules the numbers follow instead of typing them. `rounds`: the most
    rounds any of the graded drafts had (the last round weight runs to it)."""
    from engine.analytics import draft as d
    return {"rounds": rounds, "starter_rank": dict(d.STARTER_RANK), "min_games": d.MIN_GAMES, "window": d.WINDOW,
            "round_weights": [{"last_round": last, "weight": w} for last, w in d.ROUND_WEIGHTS]
            + [{"last_round": None, "weight": d.LATE_WEIGHT}],
            "hit_top_n": dict(d.HIT_TOP_N), "steal_min_round": d.STEAL_MIN_ROUND, "steal_min_games": d.STEAL_MIN_GAMES}

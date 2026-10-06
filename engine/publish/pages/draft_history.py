"""Draft history: draft-history.html.

Outputs
    data/v1/draft-history.json    page model (schema "draft-history"): every pick of every
                                  season with the drafting manager's key, and the round-1
                                  slot order
    pages/draft-history.html      the page with its inline DRAFT and SLOT_ORDER replaced

DRAFT (season -> round -> picks with PPG and games) and SLOT_ORDER (season ->
managers by draft slot) come from `draft_board` through `draft.board_data`,
the builder `analyze --verify` already checks. Hidden managers keep their
picks and slots (decision 7.3: real picks). The page's `MANAGERS` list is
config and stays as it is in Stage A.

Coverage: every drafted season. In legacy mode the live season has no PPG
(the page showed none); the engine fills it from the finished weeks.
"""

from __future__ import annotations

from engine.analytics import draft as draft_mod
from engine.analytics.weeks import live_seasons
from engine.config import excluded_manager_keys
from engine.legacy_draft import board_changes, check_board
from engine.publish.build import Output
from engine.publish.legacy_view import Names, page_roundtrip, read_literal, replace_literal
from engine.publish.pages.draft_common import legacy_draft
from engine.publish.writer import clean

SCHEMA, VERSION = "draft-history", 1
PAGE = "pages/draft-history.html"


def history_view(board, names) -> dict:
    """{"DRAFT": ..., "SLOT_ORDER": ...} as the page holds them (newest season first)."""
    data = draft_mod.board_data(board, {k: names(k) for k in board["manager_key"].unique()})
    return {k: dict(sorted(v.items(), key=lambda kv: -int(kv[0]))) for k, v in data.items()}


def history_model(board, live: set[int], hidden: set[str]) -> dict:
    seasons = []
    for season, g in board.groupby("season", sort=True):
        seasons.append({"season": int(season), "live": int(season) in live, "rounds": int(g["round"].max()),
                        "teams": int(g["draft_slot"].nunique())})
    picks = [{"season": int(r.season), "round": int(r.round), "overall_pick": int(r.overall_pick),
              "draft_slot": int(r.draft_slot), "manager_key": r.manager_key, "hidden": r.manager_key in hidden,
              "player_id": int(r.player_id), "name": r.player_name, "position": r.position,
              "ppg": clean(None if r.ppg != r.ppg else round(float(r.ppg), 2)),
              "games": clean(None if r.games != r.games else int(r.games))} for r in board.itertuples()]
    order = {str(int(s)): list(g.sort_values("draft_slot")["manager_key"])
             for s, g in board[board["round"] == 1].groupby("season", sort=True)}
    return {"seasons": seasons, "picks": picks, "slot_order": order}


def _page_names(ctx, text: str | None) -> Names:
    """The page's spelling ("Carmine Pittelli", "Ryan McQuaid")."""
    spelled = []
    if text is not None:
        try:
            spelled = [n for ms in read_literal(text, "SLOT_ORDER").values() for n in ms]
        except (KeyError, ValueError):
            pass
    return Names(ctx, spelled)


class DraftHistoryPublisher:
    name = "draft-history"

    def outputs(self, ctx) -> list[Output]:
        board = ctx.analysis.get("draft_board")
        if board is None or not len(board):
            return []
        path = ctx.site_root / PAGE
        out = [Output(f"data/v1/{SCHEMA}.json",
                      history_model(board, set(live_seasons(ctx.tables)), excluded_manager_keys(ctx.cfg)),
                      SCHEMA, VERSION)]
        if ctx.legacy_site and path.is_file():
            text = path.read_text(encoding="utf-8")
            view = history_view(board, _page_names(ctx, text))
            for var in ("DRAFT", "SLOT_ORDER"):
                text = replace_literal(text, var, view[var])
            out.append(Output(PAGE, text))
        return out

    def verify(self, ctx) -> list:
        board = ctx.analysis.get("draft_board")
        if board is None or not len(board):
            return []
        gold = ctx.golden["draft_board_page"]
        legacy = legacy_draft(ctx)
        names = Names(ctx, [n for ms in gold["SLOT_ORDER"].values() for n in ms])
        view = history_view(legacy["draft_board"], names)
        page = ctx.site_root / PAGE
        if page.is_file():
            view = page_roundtrip(page.read_text(encoding="utf-8"), view)
        # check_board rebuilds the page from a draft table; feed it the view instead
        checks = check_board({"draft_board": None}, gold, ctx.cfg, page_data=view)
        for c, var in zip(checks, ("DRAFT", "SLOT_ORDER")):
            c.name = f"legacy view {PAGE} {var} vs draft_board_page.json"
        return checks + [board_changes({"draft_board": board}, legacy)[0]]

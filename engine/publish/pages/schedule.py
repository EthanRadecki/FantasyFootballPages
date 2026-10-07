"""Schedule release: schedule_release.html.

Outputs
    data/v1/schedule.json            page model (schema "schedule"), keyed by manager key
    data/manager_schedule.json       legacy view: each manager's schedule with head-to-head history
    data/schedule_by_week.json       legacy view: the league schedule by week

Decision 7.7: the matchups come from ESPN (the season's played games plus
`future_matchups`), the history from `games` and `box_scores`, and the week
themes from the league's editorial `schedule_themes.yaml` (optional; weeks
without a theme are "Standard"). The builder was lost; the rules below were
recovered from the files (PR A8a):
    schedule       the schedule season's regular-season weeks, one pair per game,
                   interconference when the two managers' conferences differ that season
    history        every counted game between the two managers in the finished
                   seasons (playoffs included, consolation never), oldest first; a
                   playoff game is labelled by its distance from the championship
                   (Championship, Semifinal, Quarterfinal, First Round)
    record         my_wins, opp_wins, total_games over that history; game_log is
                   "win" / "loss" / "tie" per game from the manager's side
    highlights     most_recent (last game), closest (smallest margin) and blowout
                   (largest margin), earliest first on ties; scores from the
                   manager's side, margins to 2 places
    mvp            the winner's highest-scoring starter (1 place); in a tie game the
                   higher of the two teams' best starters
    highlights by theme
                   the themes file says what a theme's cards show: `rematch` (the pair's
                   deepest playoff meeting, the most recent on ties) or `trades` (trades
                   between them, one per trade); other weeks leave rematch and
                   trade_count null, as the page has them. The page model carries both
                   for every pair.
Highlight weeks are ESPN's week labels ("Playoff Round 2"), game lists use the
round names, as the files have them. The pairs' order within a week and which
team is listed first follow ESPN, not the hand-written CSV; the Stage A check
compares pairs regardless of order.
"""

from __future__ import annotations

import pandas as pd

from engine.publish.build import Output
from engine.publish.diff import compare_json
from engine.publish.editorial import load_editorial
from engine.publish.legacy_view import Names, site_json
from engine.publish.pages.champions import flag, round_name

SCHEMA = "schedule"
VERSION = 1
MANAGER_FILE = "data/manager_schedule.json"
WEEK_FILE = "data/schedule_by_week.json"
STANDARD = "Standard"


def _r(v, n):
    return None if v is None or pd.isna(v) else round(float(v), n)


# ---------------------------------------------------------------- inputs

def schedule_season(tables: dict) -> int | None:
    fm = tables.get("future_matchups")
    seasons = set() if fm is None or fm.empty else set(fm["season"].astype(int))
    return max(seasons) if seasons else None


def season_pairs(tables: dict, season: int) -> pd.DataFrame:
    """season, week, game_id, manager_key, opponent_key: one row per regular-season game, the
    first team ESPN lists first; played weeks from `matchups`, the rest from `future_matchups`."""
    cols = ["season", "week", "game_id", "manager_key", "opponent_manager_key"]
    fm = tables["future_matchups"]
    fm = fm[fm["season"] == season][cols]
    m = tables["matchups"]
    m = m[(m["season"] == season) & ~flag(m["is_playoff_week"]) & ~m["week"].isin(fm["week"])][cols]
    rows = pd.concat([m, fm], ignore_index=True).dropna(subset=["manager_key", "opponent_manager_key"])
    rows = rows.groupby(["week", "game_id"], sort=True).head(1)
    return rows.rename(columns={"opponent_manager_key": "opponent_key"}).reset_index(drop=True)


def themes(ctx, season: int) -> tuple[dict, dict]:
    """(week -> theme, theme -> what it highlights) from the league's schedule_themes.yaml."""
    f = load_editorial(ctx, "schedule_themes") or {}
    weeks = f.get("weeks") or {}
    by_week = {int(w): t for w, t in (weeks.get(season) or weeks.get(str(season)) or {}).items()}
    return by_week, dict(f.get("themes") or {})


def trade_counts(sides: pd.DataFrame, last_season: int) -> dict:
    """frozenset({a, b}) -> trades between the two managers (one per trade, however many
    transactions it took), every season through `last_season`."""
    out = {}
    for _, g in sides[sides["season"] <= last_season].groupby("group_id"):
        keys = sorted(set(g["manager_key"]))
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                out[frozenset((a, b))] = out.get(frozenset((a, b)), 0) + 1
    return out


def history(games: pd.DataFrame, box: pd.DataFrame, seasons: list[int]) -> pd.DataFrame:
    """Counted games of the finished seasons with round labels and the game's MVP."""
    g = games[games["season"].isin(seasons)].copy()
    po = flag(g["is_playoff"])
    final = g[po].groupby("season")["week"].max()
    rounds = g[po].groupby("season")["week"].nunique()
    g["label"] = [round_name(int(final[s]) - int(w), int(rounds[s])) if p else f"Week {int(w)}"
                  for s, w, p in zip(g["season"], g["week"], po)]
    st = box[box["role"] == "starter"].sort_values("order")
    best = st.sort_values("points", ascending=False, kind="stable").groupby(["season", "week", "manager_key"]).head(1)
    best = {(int(r.season), int(r.week), r.manager_key): r for r in best.itertuples()}
    mvp = []
    for r in g.itertuples():
        a, b = best.get((int(r.season), int(r.week), r.team_a_key)), best.get((int(r.season), int(r.week), r.team_b_key))
        if r.team_a_points != r.team_b_points:
            p = a if r.team_a_points > r.team_b_points else b
        else:
            p = a if (b is None or (a is not None and a.points >= b.points)) else b
        mvp.append(p)
    g["mvp"] = mvp
    return g.sort_values(["season", "week"], kind="stable").reset_index(drop=True)


def pair_history(hist: pd.DataFrame, me: str, opp: str) -> list[dict]:
    h = hist[((hist["team_a_key"] == me) & (hist["team_b_key"] == opp))
             | ((hist["team_a_key"] == opp) & (hist["team_b_key"] == me))]
    out = []
    for r in h.itertuples():
        mine = r.team_a_key == me
        pts, opp_pts = (r.team_a_points, r.team_b_points) if mine else (r.team_b_points, r.team_a_points)
        p = r.mvp
        out.append({"season": int(r.season), "week": int(r.week), "label": r.label, "week_label": r.week_label,
                    "is_playoff": bool(r.is_playoff), "points": float(pts),
                    "opponent_points": float(opp_pts),
                    "mvp": None if p is None else {"player_id": int(p.player_id), "name": p.player_name,
                                                   "position": p.position, "points": float(p.points),
                                                   "manager_key": p.manager_key}})
    return out


# ---------------------------------------------------------------- page model

def schedule_model(pairs: pd.DataFrame, conf: dict, week_themes: dict, hist: pd.DataFrame, trades: dict,
                   season: int, seasons: list[int]) -> dict:
    # a manager's conference that season, None when the league has none (a missing value never
    # makes a game interconference)
    conf = {k: (None if v is None or pd.isna(v) or v == "" else str(v)) for k, v in conf.items()}
    weeks = []
    for w, g in pairs.groupby("week", sort=True):
        weeks.append({"week": int(w), "theme": week_themes.get(int(w)),
                      "matchups": [{"manager_key": r.manager_key, "opponent_key": r.opponent_key,
                                    "interconference": conf.get(r.manager_key) is not None
                                    and conf.get(r.opponent_key) is not None
                                    and conf.get(r.manager_key) != conf.get(r.opponent_key)}
                                   for r in g.itertuples()]})
    keys = sorted({k for k in pairs["manager_key"]} | {k for k in pairs["opponent_key"]})
    rivalries = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            games = pair_history(hist, a, b)
            n = trades.get(frozenset((a, b)), 0)
            if games or n:
                rivalries.append({"manager_key": a, "opponent_key": b, "trades": n, "games": games})
    conferences = {k: conf.get(k) for k in keys}
    return {"season": season, "history_seasons": list(seasons), "weeks": weeks, "rivalries": rivalries,
            "conferences": conferences if any(v is not None for v in conferences.values()) else {}}


# ---------------------------------------------------------------- legacy views

ROUND_DEPTH = {"Championship": 0, "Semifinal": 1, "Quarterfinal": 2, "First Round": 3}


def rematch(games: list[dict]) -> dict | None:
    """The pair's biggest playoff meeting: the deepest round, the most recent on ties."""
    po = [g for g in games if g["is_playoff"]]
    if not po:
        return None
    g = min(po, key=lambda g: (ROUND_DEPTH.get(g["label"], len(ROUND_DEPTH)), -g["season"]))
    return {"season": str(g["season"]), "round": g["label"]}


def _game_view(g: dict, me: str, opp: str, names) -> dict:
    winner = me if g["points"] > g["opponent_points"] else opp if g["points"] < g["opponent_points"] else None
    return {"season": str(g["season"]), "week": g["week_label"], "score_a": _r(g["points"], 2),
            "score_b": _r(g["opponent_points"], 2), "winner": names(winner) if winner else "Tie",
            "margin": _r(abs(g["points"] - g["opponent_points"]), 2)}


def schedule_views(model: dict, names, order: list[str], highlights: dict | None = None) -> tuple[dict, list]:
    """(manager_schedule.json, schedule_by_week.json) as the page reads them. `order`: manager keys
    in the order the file lists them (the page sorts them itself). `highlights`: theme -> what
    its cards show (`rematch`, `trades`); other weeks leave rematch and trade_count null."""
    highlights = highlights or {}
    hist, trades = {}, {}
    for r in model["rivalries"]:
        trades[frozenset((r["manager_key"], r["opponent_key"]))] = r["trades"]
        hist[(r["manager_key"], r["opponent_key"])] = r["games"]
        hist[(r["opponent_key"], r["manager_key"])] = [
            {**g, "points": g["opponent_points"], "opponent_points": g["points"]} for g in r["games"]]
    by_week = []
    per = {k: [] for k in order}
    for w in model["weeks"]:
        theme = w["theme"] or STANDARD
        by_week.append({"week": w["week"], "week_type": theme,
                        "matchups": [{"team_a": names(m["manager_key"]), "team_b": names(m["opponent_key"]),
                                      "interconference": m["interconference"]} for m in w["matchups"]]})
        for m in w["matchups"]:
            for me, opp in ((m["manager_key"], m["opponent_key"]), (m["opponent_key"], m["manager_key"])):
                games = hist.get((me, opp), [])
                res = ["win" if g["points"] > g["opponent_points"] else "loss" if g["points"] < g["opponent_points"]
                       else "tie" for g in games]
                margin = lambda g: abs(g["points"] - g["opponent_points"])
                pick = lambda key: _game_view(key(games), me, opp, names) if games else None
                per.setdefault(me, []).append({
                    "week": w["week"], "week_type": theme, "opponent": names(opp),
                    "interconference": m["interconference"], "my_wins": res.count("win"),
                    "opp_wins": res.count("loss"), "total_games": len(games),
                    "most_recent": pick(lambda gs: gs[-1]),
                    "closest": pick(lambda gs: min(gs, key=margin)),
                    "blowout": pick(lambda gs: max(gs, key=margin)),
                    "game_log": res,
                    "rematch": rematch(games) if highlights.get(theme) == "rematch" else None,
                    "trade_count": trades.get(frozenset((me, opp)), 0) if highlights.get(theme) == "trades" else None,
                    "games": [{**{k: v for k, v in _game_view(g, me, opp, names).items() if k not in ("week", "margin")},
                               "season": g["season"], "label": g["label"],
                               "mvp_name": g["mvp"]["name"] if g["mvp"] else None,
                               "mvp_pos": g["mvp"]["position"] if g["mvp"] else None,
                               "mvp_pts": _r(g["mvp"]["points"], 1) if g["mvp"] else None} for g in games]})
    managers = {names(k): sorted(v, key=lambda e: e["week"]) for k, v in per.items() if v}
    return managers, by_week


# ---------------------------------------------------------------- comparison

SCORE_CORRECTED = ("score from before an ESPN stat correction (the file was written before ESPN's final "
                   "score for the game)")


def compare_views(managers: dict, by_week: list, gold_m: dict, gold_w: list) -> list:
    """Weeks keyed by week and pair (ESPN's order within a week and its first-listed team differ
    from the hand-written CSV), manager entries by week and their games by season and label."""
    def week_keyed(w):
        return {str(x["week"]): {"week_type": x["week_type"],
                                 "matchups": {"|".join(sorted((m["team_a"], m["team_b"]))): m["interconference"]
                                              for m in x["matchups"]}} for x in w}

    def mgr_keyed(m):
        return {n: {str(e["week"]): {**e, "games": {f"{g['season']} {g['label']}": g for g in e["games"]}}
                    for e in es} for n, es in m.items()}

    # games whose score changed since the file was written (same winner): (manager, week, season, label)
    corrected, highlights = set(), set()
    for n, es in gold_m.items():
        mine = {e["week"]: e for e in managers.get(n, [])}
        for e in es:
            ours = {f"{g['season']} {g['label']}": g for g in mine.get(e["week"], {}).get("games", [])}
            moved = {(str(g["season"]), g["label"]) for g in e["games"]
                     if (o := ours.get(f"{g['season']} {g['label']}")) is not None and o["winner"] == g["winner"]
                     and (o["score_a"], o["score_b"]) != (g["score_a"], g["score_b"])}
            corrected |= {(n, str(e["week"]), f"{s} {lab}") for s, lab in moved}
            seasons_moved = {s for s, _ in moved}
            for h in ("most_recent", "closest", "blowout"):
                if e[h] and e[h]["season"] in seasons_moved:
                    highlights.add((n, str(e["week"]), h))

    def known(path, eng, leg):
        p = path.strip("/").split("/")
        if len(p) == 5 and p[2] == "games" and (p[0], p[1], p[3]) in corrected and p[4] in (
                "score_a", "score_b", "mvp_name", "mvp_pos", "mvp_pts"):
            return SCORE_CORRECTED
        if len(p) == 4 and (p[0], p[1], p[2]) in highlights and p[3] in ("score_a", "score_b", "margin"):
            return SCORE_CORRECTED
        return None

    return (compare_json(f"legacy view {WEEK_FILE}", week_keyed(by_week), week_keyed(gold_w), by_section=False)
            + compare_json(f"legacy view {MANAGER_FILE}", mgr_keyed(managers), mgr_keyed(gold_m), known=known,
                           by_section=False))


# ---------------------------------------------------------------- publisher

class SchedulePublisher:
    name = "schedule"
    NEEDS = ("games", "box_scores", "manager_seasons", "trade_sides")

    def _model(self, ctx, seasons: list[int], trades_through: int | None = None) -> dict | None:
        """The schedule season's model; history over `seasons`, trades through `trades_through`
        (default: the schedule season, so this season's trades count)."""
        season = schedule_season(ctx.tables)
        if season is None:
            return None
        a = ctx.analysis
        ms = a["manager_seasons"]
        now = ms[ms["season"] == season]
        conf = dict(zip(now["manager_key"], now["conference"]))
        hist = ctx.memo(("schedule_history", tuple(seasons)), lambda: history(a["games"], a["box_scores"], seasons))
        trades = trade_counts(a["trade_sides"], trades_through or season)
        week_themes, highlights = themes(ctx, season)
        model = schedule_model(season_pairs(ctx.tables, season), conf, week_themes, hist, trades, season, seasons)
        return {**model, "theme_highlights": highlights}

    def _order(self, ctx, model: dict) -> list[str]:
        keys = {m[k] for w in model["weeks"] for m in w["matchups"] for k in ("manager_key", "opponent_key")}
        listed = [m["id"] for m in ctx.cfg["managers"] if m["id"] in keys]
        return listed + sorted(keys - set(listed))

    def outputs(self, ctx) -> list[Output]:
        if not all(n in ctx.analysis for n in self.NEEDS):
            return []
        model = self._model(ctx, list(ctx.config["finished_seasons"]))
        if model is None:
            return []
        gold = site_json(ctx, MANAGER_FILE)
        names = Names(ctx, list(gold) if gold else None)
        managers, by_week = schedule_views(model, names, self._order(ctx, model), model["theme_highlights"])
        return [Output(f"data/v1/{SCHEMA}.json", model, SCHEMA, VERSION), Output(MANAGER_FILE, managers),
                Output(WEEK_FILE, by_week)]

    def verify(self, ctx) -> list:
        if not all(n in ctx.analysis for n in self.NEEDS):
            return []
        gold_m, gold_w = ctx.golden["manager_schedule"], ctx.golden["schedule_by_week"]
        seasons = sorted({int(g["season"]) for es in gold_m.values() for e in es for g in e["games"]})
        model = self._model(ctx, seasons, max(seasons))
        if model is None:
            return []
        managers, by_week = schedule_views(model, Names(ctx, list(gold_m)), self._order(ctx, model),
                                           model["theme_highlights"])
        return compare_views(managers, by_week, gold_m, gold_w) + self.info(ctx, gold_m, gold_w)

    def info(self, ctx, gold_m: dict, gold_w: list) -> list[str]:
        model = self._model(ctx, list(ctx.config["finished_seasons"]))
        managers, by_week = schedule_views(model, Names(ctx, list(gold_m)), self._order(ctx, model),
                                           model["theme_highlights"])
        diffs = compare_views(managers, by_week, gold_m, gold_w)
        n = sum(sum(c.mismatched.values()) + int(c.missing) + int(c.extra) for c in diffs)
        return [f"INFO  schedule_release, engine data vs the live files: {n} values differ beyond ESPN's stat "
                f"corrections (history through {max(model['history_seasons'])}, trade counts through "
                f"{model['season']}); pairs listed in ESPN's order"]

"""Champions: champions.html.

Outputs
    data/v1/champions.json     page model (schema "champions"), keyed by manager key
    pages/champions.html       the page with its data replaced

The page's builder was lost (the cards were built once by hand); the rules
below were recovered from the page and reproduce it (PR A8a):
    CHAMPS     one card per finished season, newest first: champion, team name, regular
               season record ("W-L", "-T" when there are ties) and points per game, playoff
               points per game (the mean of the champion's playoff game scores), runner-up,
               and one round per playoff game the champion played. Rounds are named by their
               distance from the championship (Championship, Semifinal, Quarterfinal, First
               Round, then "Round N"), so a bye week simply has no round.
    roster     each round's starters with their slot (flex slots shown as "FLEX"), the
               week's points (2 places) and the player's points per game for this team
               before the playoff run (1 place): the weeks before the champion's first
               playoff game, on this team's roster, not on IR, and not a benched zero (a bye
               week); null when there are none (picked up for the playoffs).
    FINALS     one row per season, oldest first: champion and runner-up with their
               championship game scores.

Starters are listed in the box-score order every page shares (the engine's
`box_scores`), not the page's hand order (FLEX before TE, K before D/ST); the
Stage A check compares each card's starters by slot and name. Team names
follow the league's editorial team_names.yaml where a page shortened one.
The trophy photo and the page copy are editorial.
"""

from __future__ import annotations

import re

import pandas as pd

from engine.publish.build import Output
from engine.publish.diff import compare_json
from engine.publish.editorial import team_names
from engine.publish.legacy_view import Names, read_literal, replace_literal

SCHEMA = "champions"
VERSION = 1
PAGE = "pages/champions.html"
VARS = ["CHAMPS", "FINALS"]
ROUND_NAMES = ["Championship", "Semifinal", "Quarterfinal", "First Round"]


def _r(v, n):
    return None if v is None or pd.isna(v) else round(float(v), n)


def round_name(from_final: int, rounds: int) -> str:
    """0 = the championship; past the named rounds, "Round N" counted from the first."""
    return ROUND_NAMES[from_final] if from_final < len(ROUND_NAMES) else f"Round {rounds - from_final}"


def slot_label(slot: str) -> str:
    return "FLEX" if "/" in slot and slot != "D/ST" else slot


def flag(s: pd.Series) -> pd.Series:
    return s.astype("boolean").fillna(False).astype(bool)


# ---------------------------------------------------------------- page model

def champion_runs(ms: pd.DataFrame, games: pd.DataFrame, box: pd.DataFrame, lineups: pd.DataFrame,
                  seasons: list[int]) -> list[dict]:
    """One entry per finished season with a champion, by manager key and player id."""
    out = []
    champs = ms[flag(ms["champion"]) & ms["season"].isin(seasons)].sort_values("season")
    po = games[flag(games["is_playoff"])]
    final_week = po.groupby("season")["week"].max()
    for c in champs.itertuples():
        s, k = int(c.season), c.manager_key
        mine = po[(po["season"] == s) & ((po["team_a_key"] == k) | (po["team_b_key"] == k))].sort_values("week")
        if mine.empty or int(mine["week"].iloc[-1]) != int(final_week[s]):
            continue
        first = int(mine["week"].iloc[0])
        before = lineups[(lineups["season"] == s) & (lineups["manager_key"] == k) & (lineups["week"] < first)
                         & (lineups["slot"] != "IR")]
        before = before[flag(before["started"]) | (before["points"] != 0)]
        ppg = before.groupby("player_id")["points"].mean()
        rounds = []
        for i, g in enumerate(mine.itertuples()):
            a = g.team_a_key == k
            st = box[(box["season"] == s) & (box["week"] == g.week) & (box["manager_key"] == k)
                     & (box["role"] == "starter")].sort_values("order")
            rounds.append({"label": round_name(len(mine) - 1 - i, len(mine)), "week": int(g.week),
                           "points": float(g.team_a_points if a else g.team_b_points),
                           "opponent_key": g.team_b_key if a else g.team_a_key,
                           "opponent_points": float(g.team_b_points if a else g.team_a_points),
                           "starters": [{"slot": p.slot, "player_id": int(p.player_id), "name": p.player_name,
                                         "position": p.position, "points": float(p.points),
                                         "ppg": None if p.player_id not in ppg.index else float(ppg[p.player_id])}
                                        for p in st.itertuples()]})
        out.append({"season": s, "manager_key": k, "wins": int(c.wins), "losses": int(c.losses),
                    "ties": int(c.ties), "pf_per_game": float(c.pf_per_game),
                    "playoff_ppg": sum(r["points"] for r in rounds) / len(rounds),
                    "runner_up_key": rounds[-1]["opponent_key"], "rounds": rounds})
    return out


def champions_model(runs: list[dict], teams: dict) -> dict:
    return {"seasons": [{**r, "team_name": teams.get((r["season"], r["manager_key"]))} for r in runs]}


# ---------------------------------------------------------------- legacy view

def champions_view(runs: list[dict], teams: dict, names, player=lambda s, w, p: p["name"]) -> dict:
    """CHAMPS and FINALS as the page declares them. `player(season, week, starter)` gives the
    spelling a player is shown with (the legacy roster file's, for the Stage A check)."""
    record = lambda r: f"{r['wins']}-{r['losses']}" + (f"-{r['ties']}" if r["ties"] else "")
    champs = [{"year": r["season"], "manager": names(r["manager_key"]),
               "team": teams.get((r["season"], r["manager_key"])), "record": record(r),
               "rs_ppg": _r(r["pf_per_game"], 2), "po_ppg": _r(r["playoff_ppg"], 2),
               "runner_up": names(r["runner_up_key"]),
               "rounds": [{"label": d["label"], "week": d["week"], "total_score": _r(d["points"], 2),
                           "roster": [{"pos": slot_label(p["slot"]), "name": player(r["season"], d["week"], p),
                                       "week_score": _r(p["points"], 2), "ppg": _r(p["ppg"], 1)}
                                      for p in d["starters"]]} for d in r["rounds"]]}
              for r in sorted(runs, key=lambda r: -r["season"])]
    finals = [{"year": r["season"], "champ": names(r["manager_key"]), "champ_score": _r(r["rounds"][-1]["points"], 2),
               "runner": names(r["runner_up_key"]), "runner_score": _r(r["rounds"][-1]["opponent_points"], 2)}
              for r in runs]
    return {"CHAMPS": champs, "FINALS": finals}


def write_page(text: str, data: dict) -> str:
    for var in VARS:
        text = replace_literal(text, var, data[var])
    return text


def read_page(text: str) -> dict:
    return {v: read_literal(text, v) for v in VARS}


def spellings(page: dict) -> list[str]:
    """Every manager name the page spells (champions and runners-up)."""
    return sorted({n for f in page["FINALS"] for n in (f["champ"], f["runner"])}
                  | {n for c in page["CHAMPS"] for n in (c["manager"], c["runner_up"])})


# ---------------------------------------------------------------- comparison

ORDER_REASON = ("starters listed in the box-score order every page shares; the page's hand order put FLEX "
                "before TE and K before D/ST (each card's starters are checked by slot and name)")
PPG_TYPED = "regular season PF/G typed to 1 place on the older cards (the engine writes 2 places on every card)"
NAME_TYPED = "player name typed by hand without (or with) a suffix such as Jr. or II"
TEAM_CASE = "team name capitalized by hand (ESPN's name otherwise)"


def _norm(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", "", name.lower()).split()
    return " ".join(w for w in words if w not in ("jr", "sr", "ii", "iii", "iv", "v"))


def known(path: str, eng, leg):
    if path.endswith("/rs_ppg") and isinstance(eng, float) and isinstance(leg, float) and round(eng, 1) == leg:
        return PPG_TYPED
    if path.endswith("/name") and isinstance(eng, str) and isinstance(leg, str) and _norm(eng) == _norm(leg):
        return NAME_TYPED
    if path.endswith("/team") and isinstance(eng, str) and isinstance(leg, str) and eng.casefold() == leg.casefold():
        return TEAM_CASE
    return None


def compare_view(data: dict, gold: dict) -> list:
    """Cards keyed by year and each round's starters by slot and name (order is the one change)."""
    def keyed(d):
        cards = {}
        for c in d["CHAMPS"]:
            rounds = {r["label"]: {**{k: v for k, v in r.items() if k != "roster"},
                                   "roster": {f"{p['pos']}|{_norm(p['name'])}": p for p in r["roster"]}}
                      for r in c["rounds"]}
            cards[str(c["year"])] = {**{k: v for k, v in c.items() if k != "rounds"}, "rounds": rounds}
        return {"CHAMPS": cards, "FINALS": {str(f["year"]): f for f in d["FINALS"]}}

    out = compare_json(f"legacy view {PAGE}", keyed(data), keyed(gold), known=known)
    order = lambda d: [[f"{p['pos']}|{_norm(p['name'])}" for p in r["roster"]] for c in d["CHAMPS"] for r in c["rounds"]]
    moved = sum(a != b for a, b in zip(order(data), order(gold)))
    return out + ([f"INFO  {PAGE} card order: {moved} of {len(order(gold))} rounds list their starters in a "
                   f"different order ({ORDER_REASON})"] if moved else [])


# ---------------------------------------------------------------- publisher

class ChampionsPublisher:
    name = "champions"
    NEEDS = ("manager_seasons", "games", "box_scores")

    def _runs(self, ctx) -> list[dict]:
        a = ctx.analysis
        return champion_runs(a["manager_seasons"], a["games"], a["box_scores"], ctx.tables["lineups"],
                             list(ctx.config["finished_seasons"]))

    def outputs(self, ctx) -> list[Output]:
        if not all(n in ctx.analysis for n in self.NEEDS):
            return []
        runs, teams = self._runs(ctx), team_names(ctx)
        out = [Output(f"data/v1/{SCHEMA}.json", champions_model(runs, teams), SCHEMA, VERSION)]
        path = ctx.site_root / PAGE
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            names = Names(ctx, spellings(read_page(text)))
            out.append(Output(PAGE, write_page(text, champions_view(runs, teams, names))))
        return out

    def verify(self, ctx) -> list:
        if not all(n in ctx.analysis for n in self.NEEDS):
            return []
        gold = ctx.golden["champions_inline"]
        seasons = sorted(c["year"] for c in gold["CHAMPS"])
        a = ctx.analysis
        runs = champion_runs(a["manager_seasons"], a["games"], a["box_scores"], ctx.tables["lineups"], seasons)
        names = Names(ctx, spellings(gold))
        ros = ctx.golden["weekly_rosters_bracket_only"]
        spelled = {(int(s), int(w), int(p)): n for s, w, p, n in
                   zip(ros["Season"], ros["Week"], ros["Player_ID"], ros["Player"])}
        player = lambda s, w, p: spelled.get((s, w, p["player_id"]), p["name"])
        data = champions_view(runs, team_names(ctx), names, player)
        path = ctx.site_root / PAGE
        if path.is_file():
            data = read_page(write_page(path.read_text(encoding="utf-8"), data))
        return compare_view(data, gold) + self.info(ctx, runs)

    def info(self, ctx, runs) -> list[str]:
        finished = list(ctx.config["finished_seasons"])
        new = [r["season"] for r in self._runs(ctx) if r["season"] not in {x["season"] for x in runs}]
        return [f"INFO  {PAGE}: champion cards for seasons {finished[0]}-{finished[-1]}"
                + (f" (new: {', '.join(map(str, new))})" if new else "")
                + "; player names as ESPN spells them today (the page used the spelling of the week)"]

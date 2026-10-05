"""Extra analytics: extra-analytics.html.

Outputs
    data/v1/extra-analytics.json   page model (schema "extra-analytics"), keyed by manager key
    pages/extra-analytics.html     the page with its data replaced

PR A7a covers the matchup sections; A7b the model sections (quarterly
model, positional production, win% attribution, championship gauntlet).

Matchup sections and their rules (the builders were lost or one-off; the rules
are `analytics/matchup_history.py` and `analytics/schedule.py`, checked by
`analyze --verify`, plus the page layer here):
    managers, h2h          visible managers by name; {manager: {opponent: {w, l, pct}}},
                           pct to 3 places
    CLOSEST                {all, regular, playoff}: the 10 smallest winning margins
                           (`matchup_history.closest`), visible managers only
    luckData               career schedule luck per visible manager (actual, expected
                           and luck summed over the seasons), luck ascending
    SCHEDULE_SWAP_DATA     {season: {manager: {actual, alt {schedule: record}, avg_pct,
                           wins_gained}}}
    conference HTML        the teams grid, the six totals, the manager table (by
                           conference, win % descending), the season table (REP's
                           record), the 8 longest rivalries (`order_rivalries`)
The prose between the tables (and its numbers) is editorial and stays as it
is until Stage B.

Model sections (A7b; the fits are `analytics/regressions.py`,
`analytics/attribution.py` and `analytics/gauntlet.py`, checked by `analyze
--verify`; finished seasons):
    labels, coefs, corrs, pvals   the quarterly playoff model: per quarter of the regular
                                  season, the label "Qn (Wks a-b)", coefficient, correlation
                                  and p-value (3 places)
    POSITIONS, DATA, STD_COEF, COEF_PVAL, CORR_R
                                  positional production: per visible manager, career win %
                                  and the mean and SD of started points per position, win %
                                  descending; the positional regression (p-values 4 places)
    DATA#1, LEAGUE_INTERCEPT, COEF_LABELS, COEF_VALS
                                  win% attribution: each visible manager's waterfall, and the
                                  standardized coefficients, largest first
    R2_VALS                       the model's refinement history is editorial; its last bar
                                  is the current fit's R2
    CHAMPION_RANKS, CHAMPIONS, HARDEST, EASIEST
                                  the championship gauntlet: each champion's rank among
                                  every window of the same length, the champion cards, and
                                  the five hardest and easiest three-game stretches
                                  (`sameLength` marks a champion window other than 3 weeks;
                                  card team names from `teams`, overridden by the league's
                                  editorial team_names.yaml where the page shortened them)

Coverage: finished seasons, as the page shows today (decision 7.8, Stage A).
The head-to-head, closest and conference sections are recomputed here on the
finished seasons' games, because their analysis tables have no season
column; the luck and swap tables are filtered by season. Stage B shows the
live season's finished weeks (decision 7.8) and adds a season filter to the
luck chart (Ethan, session 7), reading `schedule_luck` per season from the
page model.
"""

from __future__ import annotations

import re

import pandas as pd

from engine.analytics import matchup_history as mh
from engine.analytics.records import games as record_games
from engine.config import conference_labels, excluded_games, excluded_manager_keys
from engine.legacy import Comparison, name_to_key
from engine.publish.build import Output
from engine.publish.diff import compare_json
from engine.publish.editorial import load_editorial
from engine.publish.legacy_view import (Names, page_roundtrip, read_html, read_literal, replace_html,
                                        replace_literal)

SCHEMA, VERSION = "extra-analytics", 1
PAGE = "pages/extra-analytics.html"
VARS = ["managers", "h2h", "CLOSEST", "luckData", "SCHEDULE_SWAP_DATA"]
MODEL_VARS = ["labels", "coefs", "corrs", "pvals", "POSITIONS", "DATA", "STD_COEF", "COEF_PVAL", "CORR_R", "DATA#1",
              "LEAGUE_INTERCEPT", "COEF_LABELS", "COEF_VALS", "R2_VALS", "CHAMPION_RANKS", "CHAMPIONS", "HARDEST",
              "EASIEST"]
HTML = {  # name: (anchor, opening tag) of typed markup
    "conference_teams": (None, '<div class="conf-teams-grid">'),
    "conference_cards": (None, '<div class="conf-stat-grid">'),
    "conference_managers": ('<table class="conf-mgr-table">', "<tbody>"),
    "conference_seasons": ('<table class="conf-year-table">', "<tbody>"),
    "rivalries": ('<table class="rivalry-table">', "<tbody>"),
}
CLOSEST_LISTED = 10
RIVALRIES_LISTED = 8
CARDS = [("Championships", "titles", 0), ("Title Game Trips", "title_games", 0), ("Playoff Trips", "playoff_trips", 0),
         ("H2H Regular Season", "wins_regular", 0), ("H2H Playoffs", "wins_playoff", 0), ("Avg PF/Game", "pf_per_game", 1)]


def _r(x, n: int) -> float:
    return round(float(x), n)


def _num(v):
    """A count as an int, a half win as a float."""
    f = float(v)
    return int(f) if f.is_integer() else f


def finished(tables: dict, seasons: list[int]) -> dict:
    out = dict(tables)
    for t in ("matchups", "teams", "seasons"):
        if t in tables:
            out[t] = tables[t][tables[t]["season"].isin(seasons)]
    return out


# ---------------------------------------------------------------- inline data

def h2h_view(h2h: pd.DataFrame, names) -> tuple[list, dict]:
    h = h2h[~h2h["hidden"]] if "hidden" in h2h else h2h
    keys = sorted(set(h["manager_key"]), key=names)
    out = {}
    for k in keys:
        rows = h[h["manager_key"] == k]
        out[names(k)] = {names(r.opponent_key): {"w": int(r.wins), "l": int(r.losses), "pct": _r(r.win_pct, 3)}
                         for r in sorted(rows.itertuples(), key=lambda r: names(r.opponent_key))}
    return [names(k) for k in keys], out


def _when(r) -> str:
    return f"{r.week_label.replace('Playoff ', '')}, {r.season}"


def closest_view(games: pd.DataFrame, hidden: set[str], names, k: int = CLOSEST_LISTED) -> dict:
    out = {}
    for scope in ("all", "regular", "playoff"):
        c = mh.closest(games, scope, k=k, exclude_managers=hidden)
        out[scope] = [{"w": names(r.winner_key), "ws": _r(r.winner_points, 2), "l": names(r.loser_key),
                       "ls": _r(r.loser_points, 2), "m": _r(r.margin, 2), "po": bool(r.is_playoff), "when": _when(r)}
                      for r in c.itertuples()]
    return out


def luck_view(luck: pd.DataFrame, names) -> list[dict]:
    s = luck[~luck["hidden"]] if "hidden" in luck else luck
    car = s.groupby("manager_key")[["actual_wins", "expected_wins", "schedule_luck"]].sum()
    rows = [{"name": names(k), "actual": _num(r.actual_wins), "predicted": _num(r.expected_wins),
             "luck": _num(r.schedule_luck)} for k, r in car.iterrows()]
    return sorted(rows, key=lambda r: (r["luck"], r["name"]))


def swap_view(swap: pd.DataFrame, summary: pd.DataFrame, names) -> dict:
    p = swap[~swap["hidden"]] if "hidden" in swap else swap
    s = summary[~summary["hidden"]] if "hidden" in summary else summary
    out: dict = {}
    for r in s.sort_values(["season"]).itertuples():
        alt = p[(p["season"] == r.season) & (p["manager_key"] == r.manager_key)]
        out.setdefault(str(int(r.season)), {})[names(r.manager_key)] = {
            "actual": {"w": _num(r.wins), "l": _num(r.losses), "pct": _r(r.pct, 4)},
            "alt": {names(a.schedule_key): {"w": _num(a.wins), "l": _num(a.losses), "games": int(a.games),
                                            "pct": _r(a.pct, 4)}
                    for a in sorted(alt.itertuples(), key=lambda a: names(a.schedule_key))},
            "avg_pct": _r(r.avg_alt_pct, 4), "wins_gained": _r(r.wins_gained, 2)}
    return {season: dict(sorted(d.items())) for season, d in out.items()}


# ---------------------------------------------------------------- conference markup

def _pct3(v: float) -> str:
    return f"{v:.3f}".lstrip("0") if v < 1 else f"{v:.3f}"


def _badge(conf: str) -> str:
    return f'<span class="conf-badge conf-{conf.lower()}">{conf}</span>'


def conference_html(res: dict, names, short, logo, season_colors: dict, order: list[str]) -> dict:
    """The typed markup of the conference section. order: the conferences in page order."""
    m = res["conference_managers"]
    m = m[~m["hidden"]]
    teams = []
    for conf in order:
        chips = "".join(
            f'\n          <div class="conf-team-chip"><img src="../{logo(k)}" alt="" onerror="this.remove()">'
            f'<span>{names(k)}</span></div>'
            for k in sorted(m.loc[m["conference"] == conf, "manager_key"], key=names))
        teams.append(f'\n      <div class="conf-teams-col conf-col-{conf.lower()} glass">\n'
                     f'        <div class="conf-teams-header conf-{conf.lower()}-text">{conf}</div>\n'
                     f'        <div class="conf-teams-list">{chips}\n        </div>\n      </div>')
    s = res["conference_summary"].set_index("conference")
    cards = []
    for label, col, digits in CARDS:
        vals = "".join(
            f'\n          <div class="conf-stat-val"><div class="conf-stat-num conf-{c.lower()}-text">'
            f'{(f"{float(s.loc[c, col]):.{digits}f}" if digits else int(s.loc[c, col])) if c in s.index else "-"}'
            f'</div><div class="conf-stat-tag conf-{c.lower()}-text">{c}</div></div>' for c in order)
        cards.append(f'\n      <div class="conf-stat-card glass">\n        <div class="conf-stat-label">{label}</div>\n'
                     f'        <div class="conf-stat-vals">{vals}\n        </div>\n      </div>')
    rows = []
    rank = {c: i for i, c in enumerate(order)}
    for r in sorted(m.itertuples(), key=lambda r: (rank.get(r.conference, 99), -r.win_pct, names(r.manager_key))):
        margin = f"{r.margin:+.1f}"
        rows.append(f'\n          <tr><td class="conf-mgr-name">{names(r.manager_key)}</td><td>{_badge(r.conference)}</td>'
                    f'<td class="num">{int(r.wins)}-{int(r.losses)}</td><td class="num">{_pct3(r.win_pct)}</td>'
                    f'<td class="num">{r.pf_per_game:.1f}</td><td class="num">{r.pa_per_game:.1f}</td>'
                    f'<td class="num attr-{"good" if r.margin >= 0 else "bad"}">{margin}</td></tr>')
    y = res["conference_seasons"]
    first = order[-1]                                    # the page reads the record as REP-DEM
    seasons = []
    for r in y[y["conference"] == first].sort_values("season").itertuples():
        color = season_colors.get(str(int(r.season)), "var(--muted)")
        seasons.append(f'\n          <tr><td><span class="season-pill" style="background:{color}">{int(r.season)}</span>'
                       f'</td><td class="num">{int(r.wins)}-{int(r.losses)}</td><td class="num">{_pct3(r.win_pct)}</td>'
                       f'<td class="num">{int(r.games)}</td></tr>')
    riv = mh.order_rivalries(res["rivalries"], {k: names(k) for k in set(res["rivalries"]["manager_key"])
                                                | set(res["rivalries"]["opponent_key"])}, k=RIVALRIES_LISTED)
    conf = m.set_index("manager_key")["conference"]
    rivals = []
    for r in riv.itertuples():
        a, b = int(r.first_wins), int(r.second_wins)
        record = f"{max(a, b)}-{min(a, b)} " + ("Tied" if a == b else short(r.first_key if a > b else r.second_key))
        rivals.append(f'\n          <tr><td>{names(r.first_key)} vs {names(r.second_key)}</td><td>{record}</td>'
                      f'<td>{int(r.games)}</td><td>{_badge(conf.get(r.first_key, ""))} '
                      f'{_badge(conf.get(r.second_key, ""))}</td></tr>')
    return {"conference_teams": "".join(teams) + "\n    ", "conference_cards": "".join(cards) + "\n    ",
            "conference_managers": "".join(rows) + "\n        ", "conference_seasons": "".join(seasons) + "\n        ",
            "rivalries": "".join(rivals) + "\n        "}


def parse_conference(html: dict) -> dict:
    """The typed markup read back into the analyze golden's shape (matchup_history/extra_analytics_matchups)."""
    cards = {}
    for block in html["conference_cards"].split('class="conf-stat-card')[1:]:
        label = re.search(r'conf-stat-label">([^<]*)<', block).group(1)
        cards[label] = {tag: float(num) for num, tag in
                        re.findall(r'conf-stat-num[^"]*">([^<]*)</div><div class="conf-stat-tag[^"]*">([^<]*)<', block)}
    cell = lambda s: re.sub(r"<[^>]+>", "", s).strip()
    table = lambda h: [[cell(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
                       for tr in re.findall(r"<tr>(.*?)</tr>", h, re.S)]
    riv = [[r[0], r[1], r[2], " ".join(re.findall(r'conf-badge[^"]*">([^<]*)<', tr))]
           for r, tr in zip(table(html["rivalries"]), re.findall(r"<tr>(.*?)</tr>", html["rivalries"], re.S))]
    teams = {}
    for block in html["conference_teams"].split('class="conf-teams-col')[1:]:
        teams[re.search(r'conf-teams-header[^"]*">([^<]*)<', block).group(1)] = re.findall(r"<span>([^<]*)</span>", block)
    return {"conference_cards": cards,
            "conference_managers": [["Manager", "Conf", "Record", "Win%", "Avg PF", "Avg PA", "Margin"]]
            + table(html["conference_managers"]),
            "conference_seasons": [["Season", "Record", "REP Win%", "Games"]] + table(html["conference_seasons"]),
            "rivalries": [["Rivalry", "Record", "Games", "Conference"]] + riv, "teams": teams}


# ---------------------------------------------------------------- model sections

FACTOR_LABELS = {"draft": "Draft", "waiver": "Waiver", "lineup": "Lineup", "trade": "Trade", "luck": "Luck"}


def quarterly_view(coefs: pd.DataFrame) -> dict:
    c = coefs.reset_index(drop=True)
    return {"labels": [f"{q} (Wks {w})" for q, w in zip(c["quarter"], c["weeks"])],
            "coefs": [_r(v, 3) for v in c["coef"]], "corrs": [_r(v, 3) for v in c["corr"]],
            "pvals": [_r(v, 3) for v in c["p_value"]]}


def positional_view(career: pd.DataFrame, coefs: pd.DataFrame, win_pct: pd.Series, positions: list[str], names) -> dict:
    """career: manager_key, <pos>_avg, <pos>_sd; win_pct: manager_key -> career win %."""
    rows = []
    for d in career.to_dict("records"):     # records keep "D/ST_avg" (itertuples renames it)
        k = d["manager_key"]
        if k not in win_pct.index:
            continue
        rows.append({"_wp": float(win_pct[k]), "mgr": names(k), "winpct": _r(win_pct[k], 1),
                     "avg": {p: _r(d[f"{p}_avg"], 2) for p in positions},
                     "std": {p: _r(d[f"{p}_sd"], 2) for p in positions}})
    rows.sort(key=lambda r: (-r["_wp"], r["mgr"]))     # unrounded win %, as the page sorted
    rows = [{k: v for k, v in r.items() if k != "_wp"} for r in rows]
    c = coefs.set_index("position")
    return {"POSITIONS": list(positions), "DATA": rows,
            "STD_COEF": {p: _r(c.loc[p, "std_coef"], 3) for p in positions},
            "COEF_PVAL": {p: _r(c.loc[p, "p_value"], 4) for p in positions},
            "CORR_R": {p: _r(c.loc[p, "corr"], 3) for p in positions}}


def attribution_view(managers: pd.DataFrame, coefs: pd.DataFrame, fit: pd.Series, r2_history: list, names) -> dict:
    m = managers[~managers["hidden"]] if "hidden" in managers else managers
    data = {names(r.manager_key): {"winpct": _r(r.win_pct, 1), "draft": _r(r.draft, 2), "waiver": _r(r.waiver, 2),
                                   "lineup": _r(r.lineup, 2), "trade": _r(r.trade, 2), "luck": _r(r.luck, 2),
                                   "predicted": _r(r.predicted, 2), "residual": _r(r.residual, 2)}
            for r in m.itertuples()}
    c = coefs.sort_values("std_coef", ascending=False, kind="stable")
    hist = list(r2_history[:-1]) + [_r(fit["r2"], 3)] if r2_history else [_r(fit["r2"], 3)]
    return {"DATA#1": dict(sorted(data.items())), "LEAGUE_INTERCEPT": _r(fit["league_intercept"], 2),
            "COEF_LABELS": [FACTOR_LABELS.get(f, f.title()) for f in c["factor"]],
            "COEF_VALS": [_r(v, 3) for v in c["std_coef"]], "R2_VALS": hist}


def _window_games(detail: pd.DataFrame, r) -> pd.DataFrame:
    return detail[(detail["season"] == r.season) & (detail["manager_key"] == r.manager_key) & (detail["n"] == r.n)
                  & (detail["start_week"] == r.start_week)].sort_values("week")


def gauntlet_view(win: pd.DataFrame, detail: pd.DataFrame, champs: pd.DataFrame, pf_per_game: dict, team: dict,
                  names) -> dict:
    """pf_per_game, team: (season, manager key) -> PF/G, team name."""
    from engine.analytics import gauntlet as gt

    hi, lo = gt.extremes(win)
    listed = lambda sel: [{"season": int(r.season), "manager": names(r.manager_key), "s_pts": _r(r.s_pts, 1),
                           "s_dom": _r(r.s_dom, 1), "s_streak": _r(r.s_streak, 1), "gs": _r(r.gs, 2),
                           "games": [{"week": g.week_label, "opponent": names(g.opponent_key),
                                      "own_score": _r(g.own_score, 1), "opp_score": _r(g.opp_score, 1),
                                      "margin": _r(g.margin, 1), "opp_dom": _r(g.opp_dom, 3),
                                      "opp_surge": _r(g.opp_surge, 1)} for g in _window_games(detail, r).itertuples()]}
                          for r in sel.itertuples()]
    # the page says "3-week stretches" unless sameLength names another window size
    ranks = {f"{int(r.season)}_{names(r.manager_key)}": {"rank": int(r.rank), "total": int(r.total),
                                                          **({"sameLength": int(r.n)} if int(r.n) != 3 else {})}
             for r in champs.sort_values("rank").itertuples()}
    cards = []
    for r in champs.sort_values("gs", ascending=False).itertuples():
        cards.append({"year": int(r.season), "champion": names(r.manager_key), "team": team.get((r.season, r.manager_key)),
                      "gs": _r(r.gs, 1), "n": int(r.n), "s_pts": _r(r.s_pts, 1), "s_dom": _r(r.s_dom, 1),
                      "s_streak": _r(r.s_streak, 1), "raw_pts": _r(r.raw_pts, 4), "raw_dom": _r(r.raw_dom, 4),
                      "raw_streak": _r(r.raw_streak, 4),
                      "games": [{"r": g.week_label.replace("Playoff ", ""), "opp": names(g.opponent_key),
                                 "ot": team.get((r.season, g.opponent_key)), "cs": _r(g.own_score, 1),
                                 "os": _r(g.opp_score, 1), "m": _r(g.margin, 1), "dom": _r(g.opp_dom, 3),
                                 "rppg": _r(pf_per_game.get((r.season, g.opponent_key), float("nan")), 1),
                                 "streak": _r(g.opp_surge, 1)} for g in _window_games(detail, r).itertuples()]})
    return {"CHAMPION_RANKS": ranks, "CHAMPIONS": cards, "HARDEST": listed(hi), "EASIEST": listed(lo)}


# ---------------------------------------------------------------- inputs

def matchup_inputs(tables: dict, cfg: dict, seasons: list[int], legacy_mode: bool) -> dict:
    """The matchup sections' tables on the finished seasons' games."""
    t = finished(tables, seasons)
    hidden = excluded_manager_keys(cfg)
    return {"head_to_head": mh.head_to_head(t, hidden), "games": record_games(t),
            "conference": mh.conference_tables(t, conference_labels(cfg), hidden, excluded_games(cfg, "ppg"),
                                               legacy_mode=legacy_mode)}


def page_data(inp: dict, luck: pd.DataFrame, swap: pd.DataFrame, swap_summary: pd.DataFrame, names, ctx) -> dict:
    hidden = excluded_manager_keys(ctx.cfg)
    mgrs, h2h = h2h_view(inp["head_to_head"], names)
    cfg_m = {m["key"]: m for m in ctx.config["managers"]}
    order = sorted(set(inp["conference"]["conference_managers"]["conference"].dropna()))   # DEM, REP
    return {"managers": mgrs, "h2h": h2h, "CLOSEST": closest_view(inp["games"], hidden, names),
            "luckData": luck_view(luck, names), "SCHEDULE_SWAP_DATA": swap_view(swap, swap_summary, names),
            **conference_html(inp["conference"], names, lambda k: cfg_m[k]["short"],
                              lambda k: cfg_m[k]["logo"], ctx.config["theme"].get("season_colors", {}), order)}


def write_page(text: str, data: dict) -> str:
    for var in VARS + [v for v in MODEL_VARS if v in data]:
        text = replace_literal(text, var, data[var])
    for name, (anchor, opening) in HTML.items():
        text = replace_html(text, opening, data[name], anchor)
    return text


def read_page(text: str) -> dict:
    out = {v: read_literal(text, v) for v in VARS + MODEL_VARS}
    out.update({name: read_html(text, opening, anchor) for name, (anchor, opening) in HTML.items()})
    return out


def team_names(ctx) -> dict:
    """(season, manager key) -> team name as the site shows it (editorial team_names.yaml
    overrides ESPN's name where the page shortened or cleaned it up)."""
    shown = {int(s_): m for s_, m in (load_editorial(ctx, "team_names") or {}).items()}
    t = ctx.tables["teams"]
    return {(int(s_), k): shown.get(int(s_), {}).get(n, n)
            for s_, k, n in zip(t["season"], t["manager_key"], t["team_name"])}


def engine_models(ctx, names, r2_history: list) -> dict:
    """The model sections from the engine's analysis tables ({} when they are missing)."""
    a = ctx.analysis
    need = ("quarterly_coefficients", "position_career", "position_coefficients", "attribution_managers",
            "attribution_coefficients", "attribution_fit", "gauntlet_windows", "gauntlet_window_games",
            "gauntlet_champions", "manager_seasons")
    if not all(n in a and len(a[n]) for n in need):
        return {}
    pc = a["position_career"]
    pc = pc[~pc["hidden"]]
    positions = list(a["position_coefficients"]["position"])
    ms = a["manager_seasons"]
    return {**quarterly_view(a["quarterly_coefficients"]),
            **positional_view(pc, a["position_coefficients"], pc.set_index("manager_key")["win_pct"] * 100, positions,
                              names),
            **attribution_view(a["attribution_managers"], a["attribution_coefficients"], a["attribution_fit"].iloc[0],
                               r2_history, names),
            **gauntlet_view(a["gauntlet_windows"], a["gauntlet_window_games"], a["gauntlet_champions"],
                            {(s_, k): v for s_, k, v in zip(ms["season"], ms["manager_key"], ms["pf_per_game"])},
                            team_names(ctx), names)}


def legacy_models(ctx, names, r2_history: list) -> dict:
    """The model sections on legacy inputs, as `analyze --verify` fits them (legacy gauntlet
    rows name managers, so the names pass through)."""
    from engine.analytics import attribution as attr
    from engine.analytics import regressions as rg
    from engine.legacy_attribution import published_factors
    from engine.legacy_gauntlet import legacy_run
    from engine.legacy_regressions import LAST_SEASON, _keys, legacy_regular, legacy_weekly

    g, cfg = ctx.golden, ctx.cfg
    reg = legacy_regular(g["matchup_data"], cfg)
    stats = g["preach_manager_stats"]
    stats = stats[stats["Year"] <= LAST_SEASON]
    playoffs = pd.DataFrame({"season": stats["Year"].astype(int), "manager_key": _keys(stats["Manager"], cfg),
                             "made": stats["Playoffs"].astype(int)})
    q = rg.quarterly_fit(reg[["season", "manager_key", "week", "points"]], playoffs, rg.LEGACY_QUARTERS)
    wp = reg.groupby(["season", "manager_key"])["win"].mean().rename("win_pct").reset_index()
    pos = rg.position_fit(legacy_weekly(g["weekly_rosters_bracket_only"], g["matchup_data"], cfg), wp)
    career = pos["career"].reset_index() if "manager_key" not in pos["career"] else pos["career"]
    att = attr.fit(published_factors(g, cfg).assign(hidden=False), sample_sd=False)
    win, detail, champs, dom = legacy_run(g, cfg)
    lk = name_to_key(cfg)
    team_of = team_names(ctx)
    as_name = lambda k: k if not str(k).startswith("m_") else names(k)
    models = {**quarterly_view(q["quarterly_coefficients"]),
            **positional_view(career, pos["coefficients"], reg.groupby("manager_key")["win"].mean() * 100,
                              list(pos["coefficients"]["position"]), names),
            **attribution_view(att["attribution_managers"], att["attribution_coefficients"],
                               att["attribution_fit"].iloc[0], r2_history, names),
            **gauntlet_view(win, detail, champs,
                            {(s_, m): v for s_, m, v in zip(dom["season"], dom["manager_key"], dom["pf_per_game"])},
                            {(s_, m): team_of.get((s_, lk[m.strip().lower()])) for s_, m in
                             zip(dom["season"], dom["manager_key"])}, as_name)}
    _raw_dom_cards(models["CHAMPIONS"], champs, detail)
    models["_rank_ties"] = rank_ties(champs, win, as_name)
    return models


def rank_ties(champs: pd.DataFrame, win: pd.DataFrame, names) -> dict:
    """CHAMPION_RANKS key -> (first, last) rank of its tied group. Legacy ranked on the score
    rounded to 2 places with pandas' default (unstable) sort, so the order inside a tie depends
    on the pandas version (legacy_gauntlet.check_ranks excuses the same)."""
    out = {}
    for r in champs.itertuples():
        pool = [round(float(v), 2) for v in win.loc[win["n"] == r.n, "gs"]]
        mine = round(float(r.gs), 2)
        lo, hi = sum(v > mine for v in pool) + 1, sum(v >= mine for v in pool)
        if lo < hi:
            out[f"{int(r.season)}_{names(r.manager_key)}"] = (lo, hi)
    return out


def _raw_dom_cards(cards: list[dict], champs: pd.DataFrame, detail: pd.DataFrame) -> None:
    """The page's cards came from a script variant that scored dominance on the raw mean of the
    opponents' dominance, not its z-score (METRICS_REFERENCE, gauntlet); rebuild that variant so
    the legacy view reproduces the cards (analyze --verify checks them the same way)."""
    from engine.analytics import gauntlet as gt

    for c in cards:
        r = champs[champs["season"] == c["year"]].iloc[0]
        raw = _r(_window_games(detail, r)["opp_dom"].mean(), 4)
        c["raw_dom"] = raw
        c["s_dom"] = _r(gt.logistic(raw * c["n"] / (c["n"] + 1)), 1)


# ---------------------------------------------------------------- page model

def extra_model(inp: dict, luck: pd.DataFrame, swap: pd.DataFrame, swap_summary: pd.DataFrame, hidden: set[str],
                seasons: list[int]) -> dict:
    ident = lambda k: k
    h = inp["head_to_head"]
    h = h[~h["hidden"]]
    res = inp["conference"]
    cm = res["conference_managers"]
    l_ = luck[~luck["manager_key"].isin(hidden)]
    return {
        "seasons": list(seasons),
        "head_to_head": [{"manager_key": r.manager_key, "opponent_key": r.opponent_key, "wins": int(r.wins),
                          "losses": int(r.losses), "ties": int(r.ties), "win_pct": float(r.win_pct)}
                         for r in h.sort_values(["manager_key", "opponent_key"]).itertuples()],
        "closest": closest_view(inp["games"], hidden, ident),
        "schedule_luck": {
            "career": luck_view(l_, ident),
            "seasons": [{"season": int(r.season), "manager_key": r.manager_key, "games": int(r.games),
                         "actual_wins": float(r.actual_wins), "expected_wins": float(r.expected_wins),
                         "luck": float(r.schedule_luck)} for r in l_.sort_values(["season", "manager_key"]).itertuples()]},
        "schedule_swap": swap_view(swap[~swap["manager_key"].isin(hidden)],
                                   swap_summary[~swap_summary["manager_key"].isin(hidden)], ident),
        "conference": {
            "summary": [{k: (v if isinstance(v, str) else float(v)) for k, v in r.items()}
                        for r in res["conference_summary"].to_dict(orient="records")],
            "managers": [{"manager_key": r.manager_key, "conference": r.conference, "wins": int(r.wins),
                          "losses": int(r.losses), "win_pct": float(r.win_pct), "pf_per_game": float(r.pf_per_game),
                          "pa_per_game": float(r.pa_per_game), "margin": float(r.margin)}
                         for r in cm[~cm["hidden"]].itertuples()],
            "seasons": [{"season": int(r.season), "conference": r.conference, "wins": int(r.wins),
                         "losses": int(r.losses), "games": int(r.games), "win_pct": float(r.win_pct)}
                        for r in res["conference_seasons"].itertuples()],
            "rivalries": [{"first_key": r.first_key, "second_key": r.second_key, "first_wins": int(r.first_wins),
                           "second_wins": int(r.second_wins), "games": int(r.games)}
                          for r in mh.order_rivalries(res["rivalries"], {k: k for k in set(res["rivalries"]["manager_key"])
                                                                        | set(res["rivalries"]["opponent_key"])},
                                                      k=RIVALRIES_LISTED).itertuples()]},
    }


def models_model(a: dict) -> dict:
    """The model sections in the data file, by manager key ({} without the analysis tables).
    The R2 history stays on the page until Stage B (editorial: it names past model versions)."""
    need = ("quarterly_coefficients", "position_career", "position_coefficients", "attribution_managers",
            "attribution_coefficients", "attribution_fit", "gauntlet_windows", "gauntlet_window_games",
            "gauntlet_champions")
    if not all(n in a and len(a[n]) for n in need):
        return {}
    from engine.analytics import gauntlet as gt

    num = lambda v: None if pd.isna(v) else float(v)
    pc = a["position_career"]
    pc = pc[~pc["hidden"]]
    positions = list(a["position_coefficients"]["position"])
    am = a["attribution_managers"]
    am = am[~am["hidden"]] if "hidden" in am else am
    fit = a["attribution_fit"].iloc[0]
    detail = a["gauntlet_window_games"]

    def window(r) -> dict:
        return {"season": int(r.season), "manager_key": r.manager_key, "n": int(r.n), "start_week": int(r.start_week),
                **{f: float(getattr(r, f)) for f in ("raw_pts", "raw_dom", "raw_streak", "s_pts", "s_dom", "s_streak",
                                                     "gs")},
                "rank": int(r.rank), "total": int(r.total),
                "games": [{"week": int(g.week), "week_label": g.week_label, "opponent_key": g.opponent_key,
                           "own_score": float(g.own_score), "opp_score": float(g.opp_score),
                           "margin": float(g.margin), "opp_dom": float(g.opp_dom), "opp_surge": float(g.opp_surge)}
                          for g in _window_games(detail, r).itertuples()]}

    hi, lo = gt.extremes(a["gauntlet_windows"])
    return {
        "quarterly": [{"quarter": r.quarter, "weeks": str(r.weeks), "coef": float(r.coef),
                       "p_value": float(r.p_value), "corr": num(r.corr)}
                      for r in a["quarterly_coefficients"].itertuples()],
        "positional": {
            "positions": positions,
            "coefficients": [{"position": r.position, "coef": float(r.coef), "std_coef": float(r.std_coef),
                              "p_value": float(r.p_value), "corr": num(r.corr)}
                             for r in a["position_coefficients"].itertuples()],
            "managers": [{"manager_key": d["manager_key"], "win_pct": float(d["win_pct"]),
                          "avg": {p: num(d[f"{p}_avg"]) for p in positions},
                          "sd": {p: num(d[f"{p}_sd"]) for p in positions}}
                         for d in pc.sort_values("manager_key").to_dict("records")]},
        "attribution": {
            "fit": {"n": int(fit["n"]), "r2": float(fit["r2"]), "adj_r2": float(fit["adj_r2"]),
                    "league_intercept": float(fit["league_intercept"])},
            "coefficients": [{"factor": r.factor, "coef": float(r.coef), "std_coef": float(r.std_coef),
                              "p_value": float(r.p_value)} for r in a["attribution_coefficients"].itertuples()],
            "managers": [{"manager_key": r.manager_key, "seasons": int(r.seasons),
                          **{f: float(getattr(r, f)) for f in ("win_pct", "draft", "waiver", "lineup", "trade", "luck",
                                                               "predicted", "residual")}}
                         for r in am.sort_values("manager_key").itertuples()]},
        "gauntlet": {"champions": [window(r) for r in a["gauntlet_champions"].sort_values("season").itertuples()],
                     "hardest": [window(r) for r in hi.itertuples()],
                     "easiest": [window(r) for r in lo.itertuples()]},
    }


# ---------------------------------------------------------------- Stage A check

def _page_names(ctx, text: str | None) -> Names:
    spelled = []
    if text is not None:
        try:
            spelled = read_literal(text, "managers")
        except (KeyError, ValueError):
            pass
    return Names(ctx, spelled)


class ExtraAnalyticsPublisher:
    name = "extra-analytics"
    NEEDS = ("schedule_luck", "schedule_swap", "schedule_swap_summary")

    def _seasons(self, ctx) -> list[int]:
        return list(ctx.config["finished_seasons"])

    def _engine(self, ctx):
        a, seasons = ctx.analysis, self._seasons(ctx)
        cut = lambda df: df[df["season"].isin(seasons)]
        inp = ctx.memo("extra_engine_inputs", lambda: matchup_inputs(ctx.tables, ctx.cfg, seasons, False))
        return inp, cut(a["schedule_luck"]), cut(a["schedule_swap"]), cut(a["schedule_swap_summary"]), seasons

    def outputs(self, ctx) -> list[Output]:
        if not all(n in ctx.analysis for n in self.NEEDS):
            return []
        inp, luck, swap, summ, seasons = self._engine(ctx)
        hidden = excluded_manager_keys(ctx.cfg)
        model = {**extra_model(inp, luck, swap, summ, hidden, seasons), **models_model(ctx.analysis)}
        out = [Output(f"data/v1/{SCHEMA}.json", model, SCHEMA, VERSION)]
        path = ctx.site_root / PAGE
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            names = _page_names(ctx, text)
            data = page_data(inp, luck, swap, summ, names, ctx)
            data.update(engine_models(ctx, names, read_literal(text, "R2_VALS")))
            out.append(Output(PAGE, write_page(text, data)))
        return out

    def verify(self, ctx) -> list:
        if not all(n in ctx.analysis for n in self.NEEDS):
            return []
        from engine.analytics import schedule as schedule_mod

        gold = ctx.golden["extra_analytics_inline"]
        seasons = sorted(int(s) for s in gold["SCHEDULE_SWAP_DATA"])
        inp = matchup_inputs(ctx.tables, ctx.cfg, seasons, legacy_mode=True)
        t = finished(ctx.tables, seasons)
        sched = schedule_mod.analyze_schedule(t, excluded_manager_keys(ctx.cfg), legacy_mode=True)
        names = Names(ctx, gold["managers"])
        data = page_data(inp, sched["schedule_luck"], sched["schedule_swap"], sched["schedule_swap_summary"], names, ctx)
        models = legacy_models(ctx, names, gold["R2_VALS"])
        ties = models.pop("_rank_ties")
        data.update(models)
        path = ctx.site_root / PAGE
        if path.is_file():
            data = read_page(write_page(path.read_text(encoding="utf-8"), data))
        hidden = excluded_manager_keys(ctx.cfg)
        full = {scope: closest_view(inp["games"], hidden, names, k=len(inp["games"]))[scope]
                for scope in ("regular", "playoff")}
        return compare_view(data, gold, ctx, full) + compare_models(data, gold, ties) + self.info(ctx)

    def info(self, ctx) -> list[str]:
        path = ctx.site_root / PAGE
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8")
        inp, luck, swap, summ, _ = self._engine(ctx)
        eng = page_data(inp, luck, swap, summ, _page_names(ctx, text), ctx)
        live = {r["name"]: r["luck"] for r in read_literal(text, "luckData")}
        moved = [f"{r['name']} {live[r['name']]:+g} -> {r['luck']:+g}" for r in eng["luckData"]
                 if r["name"] in live and r["luck"] != live[r["name"]]]
        return [f"INFO  extra-analytics matchup sections, engine data vs the live page: career luck changes "
                + (", ".join(moved) or "none") + " (engine: half wins for ties with the median, finished weeks); "
                "the closest regular-season and playoff lists include the closer games the page skipped; "
                "conference prose stays typed until Stage B"] + self.model_info(ctx, text)

    def model_info(self, ctx, text: str) -> list[str]:
        live = read_page(text)
        eng = engine_models(ctx, _page_names(ctx, text), live["R2_VALS"])
        if not eng:
            return []
        ranks = lambda d: ", ".join(f"{k.replace('_', ' ')} {v['rank']}/{v['total']}"
                                    for k, v in d["CHAMPION_RANKS"].items())
        return [f"INFO  extra-analytics model sections, engine vs the live page: R2 {live['R2_VALS'][-1]} -> "
                f"{eng['R2_VALS'][-1]}; attribution order {', '.join(live['COEF_LABELS'])} -> "
                f"{', '.join(eng['COEF_LABELS'])}; quarterly coefficients {live['coefs']} -> {eng['coefs']} "
                f"(decision, session 4); champion ranks {ranks(live)} -> {ranks(eng)} (engine ranks on the "
                f"unrounded score and keeps excluded managers' games)"]


# ---------------------------------------------------------------- comparison

CLOSEST_SKIP = ("closer games the page's list skips (its all-games list includes some of them; analyze --verify "
                "lists them); every page game is checked in the engine's margin order")
LUCK_FILE = "career luck from schedule_luck_season.csv, built from an older matchup_data.csv (analyze excuses the rows)"
LUCK_TYPED = "page contradicts its own source file (schedule_luck_season.csv sums to the engine's value)"
PF_TYPED = ("conference average PF/game typed by hand: no combination of games and seasons gives the page's value "
            "(as analyze --verify)")


def compare_view(data: dict, gold: dict, ctx, full_closest: dict) -> list:
    """full_closest: {regular, playoff: every decided game in margin order, view-shaped}."""
    checks: list = compare_json(f"legacy view {PAGE} head-to-head", {"managers": data["managers"], "h2h": data["h2h"]},
                                {"managers": gold["managers"], "h2h": gold["h2h"]})
    # CLOSEST: the all list must match exactly; the regular and playoff lists must hold every page game in
    # the same order, the closer games the page skipped excused
    all_ = compare_json(f"legacy view {PAGE} CLOSEST all", data["CLOSEST"]["all"], gold["CLOSEST"]["all"],
                        by_section=False)
    checks += all_
    for scope in ("regular", "playoff"):
        full = full_closest[scope]
        c = Comparison(f"legacy view {PAGE} CLOSEST {scope} vs published", len(gold["CLOSEST"][scope]),
                       len(data["CLOSEST"][scope]))
        key = lambda r: (r["w"], r["l"], r["when"])
        at = {key(r): i for i, r in enumerate(full)}
        pos = [at.get(key(r)) for r in gold["CLOSEST"][scope]]
        c.missing = sum(p is None for p in pos)
        bad = [r for r, p in zip(gold["CLOSEST"][scope], pos) if p is not None and full[p] != r]
        found = [p for p in pos if p is not None]
        c.mismatched["values"] = len(bad)
        c.mismatched["order"] = int(found != sorted(found))
        skipped = (max(found) + 1 - len(found)) if found else 0
        if skipped:
            c.known[CLOSEST_SKIP] = skipped
        c.examples = [f"{r}" for r in bad[:3]]
        checks.append(c)
    # luck chart
    lk = name_to_key(ctx.cfg)
    file = ctx.golden["schedule_luck_season"].assign(k=lambda d: d["Manager"].str.strip().str.lower().map(lk))
    fsum = file.groupby("k")[["actual_wins", "expected_wins", "schedule_luck"]].sum()
    from engine.legacy_schedule import legacy_luck_rerun
    rerun = legacy_luck_rerun(ctx.golden["matchup_data"], ctx.cfg).groupby("manager_key")[
        ["actual_wins", "expected_wins", "schedule_luck"]].sum()
    col = {"actual": "actual_wins", "predicted": "expected_wins", "luck": "schedule_luck"}

    def luck_known(path, eng, leg):
        m = re.match(r"/(.+)/(actual|predicted|luck)$", path)
        if not m:
            return None
        k, c_ = lk[m.group(1).strip().lower()], col[m.group(2)]
        if abs(fsum.loc[k, c_] - leg) < 1e-9 and abs(rerun.loc[k, c_] - eng) < 1e-9:
            return LUCK_FILE
        if abs(fsum.loc[k, c_] - eng) < 1e-9:
            return LUCK_TYPED
        return None
    checks += compare_json(f"legacy view {PAGE} luckData", {r["name"]: r for r in data["luckData"]},
                           {r["name"]: r for r in gold["luckData"]}, known=luck_known, by_section=False)
    checks += compare_json(f"legacy view {PAGE} SCHEDULE_SWAP_DATA", data["SCHEDULE_SWAP_DATA"],
                           gold["SCHEDULE_SWAP_DATA"], by_section=False)
    # conference markup: read back into the analyze golden's shape and compared with it
    got = parse_conference(data)
    want = parse_conference(gold)
    pf = lambda path, e, l: PF_TYPED if path.startswith("/conference_cards/Avg PF/Game") else None
    checks += compare_json(f"legacy view {PAGE} conference", got, want, known=pf)
    return checks


QUARTERLY_REASON = "page coefficients from a run that cannot be reproduced; replaced with the correct fit (Ethan, session 4)"
POS_REASON = "page fit from a slightly earlier data version (within {:g} of the legacy inputs' fit, as analyze --verify)"
CARD_PTS_REASON = "champion card built on an earlier data version (league averages differ slightly; raw points within 0.03)"
CARD_SURGE_REASON = "champion card surges from a lost script variant (not reproducible; analyze --verify checks the rest)"
RANK_TIE_REASON = "tied score (ranks {}-{}); legacy's sort order inside a tie depends on the pandas version (as analyze --verify)"
TEAM_REASON = "team name as typed on the page (case or emoji differ from ESPN's name)"


def _team_key(name: str) -> str:
    return re.sub(r"[^0-9a-z]", "", name.encode("ascii", "ignore").decode().casefold())


def compare_models(data: dict, gold: dict, ties: dict | None = None) -> list[Comparison]:
    from engine.legacy_regressions import COEF_CLOSE, P_CLOSE

    ties = ties or {}

    def known(path, eng, leg):
        m = re.match(r"/CHAMPION_RANKS/(.+)/rank$", path)
        if m and m.group(1) in ties and isinstance(eng, int) and isinstance(leg, int):
            lo, hi = ties[m.group(1)]
            return RANK_TIE_REASON.format(lo, hi) if lo <= eng <= hi and lo <= leg <= hi else None
        if re.match(r"/(coefs|pvals)\[\d+\]$", path):
            return QUARTERLY_REASON
        m = re.match(r"/(STD_COEF|CORR_R|COEF_PVAL)/", path)
        if m and isinstance(eng, float):
            bound = P_CLOSE if m.group(1) == "COEF_PVAL" else COEF_CLOSE
            return POS_REASON.format(bound) if abs(eng - leg) <= bound + 1e-9 else None
        if re.match(r"/CHAMPIONS/\d+/(team|games\[\d+\]/ot)$", path) and isinstance(eng, str) and _team_key(eng) == _team_key(leg):
            return TEAM_REASON
        m = re.match(r"/CHAMPIONS/(\d+)/(raw_pts|s_pts|gs|s_streak|raw_streak|games\[\d+\]/streak)$", path)
        if m:
            if m.group(2) == "raw_pts":
                return CARD_PTS_REASON if abs(eng - leg) <= 0.03 + 1e-9 else None
            return CARD_SURGE_REASON
        return None

    # tied win % (three managers at 48.1) sort in the legacy script's own order: rows are checked by
    # manager and the order by the sequence of win %
    keyed = lambda d: {**{k: d[k] for k in MODEL_VARS}, "CHAMPIONS": {str(c["year"]): c for c in d["CHAMPIONS"]},
                       "DATA": {r["mgr"]: r for r in d["DATA"]}, "DATA order": [r["winpct"] for r in d["DATA"]]}
    out = compare_json(f"legacy view {PAGE} models", keyed(data), keyed(gold), known=known)
    return out

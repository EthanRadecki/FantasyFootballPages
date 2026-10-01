"""Extra analytics: extra-analytics.html.

Outputs
    data/v1/extra-analytics.json   page model (schema "extra-analytics"), keyed by manager key
    pages/extra-analytics.html     the page with its data replaced

PR A7a covers the matchup sections; A7b adds the model sections (quarterly
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
from engine.publish.legacy_view import (Names, page_roundtrip, read_html, read_literal, replace_html,
                                        replace_literal)

SCHEMA, VERSION = "extra-analytics", 1
PAGE = "pages/extra-analytics.html"
VARS = ["managers", "h2h", "CLOSEST", "luckData", "SCHEDULE_SWAP_DATA"]
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
    for var in VARS:
        text = replace_literal(text, var, data[var])
    for name, (anchor, opening) in HTML.items():
        text = replace_html(text, opening, data[name], anchor)
    return text


def read_page(text: str) -> dict:
    out = {v: read_literal(text, v) for v in VARS}
    out.update({name: read_html(text, opening, anchor) for name, (anchor, opening) in HTML.items()})
    return out


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
        out = [Output(f"data/v1/{SCHEMA}.json", extra_model(inp, luck, swap, summ, hidden, seasons), SCHEMA, VERSION)]
        path = ctx.site_root / PAGE
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            out.append(Output(PAGE, write_page(text, page_data(inp, luck, swap, summ, _page_names(ctx, text), ctx))))
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
        path = ctx.site_root / PAGE
        if path.is_file():
            data = read_page(write_page(path.read_text(encoding="utf-8"), data))
        hidden = excluded_manager_keys(ctx.cfg)
        full = {scope: closest_view(inp["games"], hidden, names, k=len(inp["games"]))[scope]
                for scope in ("regular", "playoff")}
        return compare_view(data, gold, ctx, full) + self.info(ctx)

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
                "conference prose stays typed until Stage B"]


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

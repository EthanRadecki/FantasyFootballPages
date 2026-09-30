"""Compare matchup history with extra-analytics.html.

Golden file:
    matchup_history/extra_analytics_matchups.json.gz   the page's inline
                                                        head-to-head matrix
                                                        and closest games, and
                                                        its conference analysis
                                                        tables (parsed from the
                                                        HTML)

The page was built after the 2025 season, so the checks cut the engine's
tables at 2025. Legacy mode: excluded managers' games dropped from the
conference analysis (the head-to-head matrix and closest games only show
visible managers).

Excused by pattern:
- closest games: the regular-season and playoff lists skip games the page's
  own all-games list includes (Pittelli-Quigley 2021 week 5 at 0.18, for
  example). Every listed game must be a real game, in margin order; the
  skipped games are listed as INFO.
- conference average PF/game: no combination of games and seasons gives the
  page's 111.9 and 110.9; typed by hand.
The page left the Castaldo 2024 week 14 forfeit out of both teams' PF and
PA averages (the result counts); legacy mode does the same.
"""

from __future__ import annotations

import pandas as pd

from engine.analytics import matchup_history as mh
from engine.analytics.records import games as record_games
from engine.config import conference_labels, excluded_games, excluded_manager_keys
from engine.legacy import Comparison, compare, name_to_key, resolve_names

LAST_SEASON = 2025


def _cut(tables: dict) -> dict:
    out = dict(tables)
    for t in ("matchups", "teams", "seasons"):
        out[t] = tables[t][tables[t]["season"] <= LAST_SEASON]
    return out


def _key(name: str, lk: dict) -> str:
    return lk[name.strip().lower()]


def check_h2h(tables: dict, page: dict, cfg: dict) -> Comparison:
    lk = name_to_key(cfg)
    exp = pd.DataFrame([{"manager_key": _key(a, lk), "opponent_key": _key(b, lk), "wins": v["w"], "losses": v["l"],
                         "pct": v["pct"]} for a, row in page["h2h"].items() for b, v in row.items()])
    act = mh.head_to_head(tables, excluded_manager_keys(cfg))
    act = act[~act["hidden"]].assign(pct=lambda d: [round(float(x), 3) for x in d["win_pct"]])
    return compare("head-to-head vs extra-analytics.html h2h", exp, act, keys=["manager_key", "opponent_key"],
                   values=["wins", "losses", "pct"], tolerance=1e-9)


def _when(r) -> str:
    label = r.week_label.replace("Playoff ", "")
    return f"{label}, {r.season}"


def _closest_frame(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"winner_key": df["winner_key"], "loser_key": df["loser_key"],
                         "ws": [round(float(v), 2) for v in df["winner_points"]],
                         "ls": [round(float(v), 2) for v in df["loser_points"]],
                         "m": [round(float(v), 2) for v in df["margin"]], "po": df["is_playoff"].astype(bool),
                         "when": [_when(r) for r in df.itertuples()]})


def check_closest(tables: dict, page: dict, cfg: dict) -> tuple[list[Comparison], list[str]]:
    lk, ex = name_to_key(cfg), excluded_manager_keys(cfg)
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    g = record_games(tables)
    checks, info = [], []
    for scope in ("all", "regular", "playoff"):
        exp = pd.DataFrame([{"winner_key": _key(p["w"], lk), "loser_key": _key(p["l"], lk), "ws": p["ws"],
                             "ls": p["ls"], "m": p["m"], "po": p["po"], "when": p["when"]} for p in page["CLOSEST"][scope]])
        exp["pos"] = range(len(exp))
        full = _closest_frame(mh.closest(g, scope, k=len(g), exclude_managers=ex))
        full["engine_pos"] = range(len(full))
        if scope == "all":
            act = full.head(len(exp)).assign(pos=lambda d: d["engine_pos"])
            checks.append(compare("closest games (all) vs extra-analytics.html CLOSEST", exp, act, keys=["pos"],
                                  values=["winner_key", "loser_key", "ws", "ls", "m", "po", "when"], tolerance=1e-9))
            continue
        matched = exp[["pos", "winner_key", "when"]].merge(full, on=["winner_key", "when"], how="left")
        act = matched.sort_values("engine_pos").assign(pos=range(len(matched)))
        checks.append(compare(f"closest games ({scope}) vs extra-analytics.html CLOSEST", exp,
                              act.dropna(subset=["engine_pos"]), keys=["pos"],
                              values=["winner_key", "loser_key", "ws", "ls", "m", "po", "when"], tolerance=1e-9))
        last = int(matched["engine_pos"].max()) if matched["engine_pos"].notna().all() else len(full)
        skipped = full[(full["engine_pos"] <= last) & ~full["engine_pos"].isin(matched["engine_pos"])]
        if len(skipped):
            info.append(f"INFO  closest games ({scope}): the page skips {len(skipped)} closer game(s) its own list "
                        "of all games includes: " + ", ".join(
                            f"{names.get(r.winner_key)} over {names.get(r.loser_key)} {r.m} ({r.when})"
                            for r in skipped.itertuples()))
    return checks, info


def _parse_record(s: str) -> tuple[int, int]:
    a, b = s.split()[0].split("-")
    return int(a), int(b)


def check_conference(tables: dict, page: dict, cfg: dict) -> list[Comparison]:
    lk, ex = name_to_key(cfg), excluded_manager_keys(cfg)
    labels = conference_labels(cfg)
    res = mh.conference_tables(tables, labels, ex, excluded_games(cfg, "ppg"), legacy_mode=True)
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}

    cards = page["conference_cards"]
    col = {"Championships": "titles", "Title Game Trips": "title_games", "Playoff Trips": "playoff_trips",
           "H2H Regular Season": "wins_regular", "H2H Playoffs": "wins_playoff", "Avg PF/Game": "pf_per_game"}
    exp_s = pd.DataFrame([{"conference": c, **{col[k]: v[c] for k, v in cards.items()}} for c in ("DEM", "REP")])
    act_s = res["conference_summary"].copy()
    act_s["pf_per_game"] = [round(float(v), 1) for v in act_s["pf_per_game"]]
    known = pd.DataFrame({"conference": ["DEM", "REP"], "column": "pf_per_game",
                          "reason": "typed by hand: no combination of games and seasons gives the page's value; the engine "
                                    "uses points per game over all counted games"})
    checks = [compare("conference totals vs extra-analytics.html", exp_s, act_s, keys=["conference"],
                      values=list(col.values()), tolerance=1e-9, known=known)]

    rows = page["conference_managers"][1:]
    exp_m = pd.DataFrame([{"manager_key": _key(r[0], lk), "conference": r[1], "wins": _parse_record(r[2])[0],
                           "losses": _parse_record(r[2])[1], "pct": r[3], "pf": float(r[4]), "pa": float(r[5]),
                           "margin": float(r[6])} for r in rows])
    m = res["conference_managers"]
    m = m[~m["hidden"]]
    act_m = pd.DataFrame({"manager_key": m["manager_key"], "conference": m["conference"], "wins": m["wins"],
                          "losses": m["losses"], "pct": [f"{v:.3f}".lstrip("0") for v in m["win_pct"]],
                          "pf": [round(float(v), 1) for v in m["pf_per_game"]],
                          "pa": [round(float(v), 1) for v in m["pa_per_game"]],
                          "margin": [round(float(v), 1) for v in m["margin"]]})
    checks.append(compare("conference manager records vs extra-analytics.html", exp_m, act_m, keys=["manager_key"],
                          values=["conference", "wins", "losses", "pct", "pf", "pa", "margin"], tolerance=0.051))

    exp_y = pd.DataFrame([{"season": int(r[0]), "wins": _parse_record(r[1])[0], "losses": _parse_record(r[1])[1],
                           "pct": r[2], "games": int(r[3])} for r in page["conference_seasons"][1:]])
    y = res["conference_seasons"]
    y = y[y["conference"] == "REP"]
    act_y = pd.DataFrame({"season": y["season"].astype(int), "wins": y["wins"], "losses": y["losses"],
                          "pct": [f"{v:.3f}".lstrip("0") for v in y["win_pct"]], "games": y["games"]})
    checks.append(compare("conference records by season vs extra-analytics.html", exp_y, act_y, keys=["season"],
                          values=["wins", "losses", "pct", "games"], tolerance=1e-9))

    display = {k: n for n, k in ((m_["name"], m_["id"]) for m_ in cfg["managers"])}
    for n in page["h2h_managers"]:
        display[_key(n, lk)] = n                     # the page's own spelling decides the name order
    riv = mh.order_rivalries(res["rivalries"], display, k=len(page["rivalries"]) - 1)
    exp_r = []
    for i, r in enumerate(page["rivalries"][1:]):
        a, b = [x.strip() for x in r[0].split(" vs ")]
        wa, wb = _parse_record(r[1])
        leader = r[1].split()[1]
        if leader != "Tied" and _key(a, lk) and not names[_key(a, lk)].split()[-1] == leader:
            wa, wb = wb, wa
        ca, cb = r[3].split()
        exp_r.append({"pos": i, "first_key": _key(a, lk), "second_key": _key(b, lk), "first_wins": wa,
                      "second_wins": wb, "games": int(r[2]), "first_conf": ca, "second_conf": cb})
    conf = res["conference_managers"].set_index("manager_key")["conference"]
    act_r = riv.assign(pos=range(len(riv)), first_conf=riv["first_key"].map(conf),
                       second_conf=riv["second_key"].map(conf))
    checks.append(compare("rivalries vs extra-analytics.html", pd.DataFrame(exp_r), act_r, keys=["pos"],
                          values=["first_key", "second_key", "first_wins", "second_wins", "games", "first_conf",
                                  "second_conf"], tolerance=1e-9))
    return checks


def _summary_line(res: dict) -> str:
    s = res["conference_summary"].set_index("conference")
    y = res["conference_seasons"]
    y = y[y["conference"] == "REP"]
    return ("; ".join(f"{c}: titles {int(r.titles)}, title games {int(r.title_games)}, playoff trips "
                      f"{int(r.playoff_trips)}, wins {int(r.wins_regular)} + {int(r.wins_playoff)} playoff, "
                      f"PF/G {r.pf_per_game:.1f}" for c, r in s.iterrows())
            + " | REP by season: " + ", ".join(f"{int(r.season)} {int(r.wins)}-{int(r.losses)}" for r in y.itertuples()))


def _manager_moves(leg: dict, eng: dict, names: dict) -> str:
    a = leg["conference_managers"].set_index("manager_key")
    b = eng["conference_managers"]
    b = b[~b["hidden"]].set_index("manager_key")
    moves = [f"{names.get(k, k)} {a.loc[k, 'wins']}-{a.loc[k, 'losses']} PF {a.loc[k, 'pf_per_game']:.1f} "
             f"PA {a.loc[k, 'pa_per_game']:.1f} -> {b.loc[k, 'wins']}-{b.loc[k, 'losses']} PF "
             f"{b.loc[k, 'pf_per_game']:.1f} PA {b.loc[k, 'pa_per_game']:.1f}"
             for k in a.index if k in b.index and (
                 (a.loc[k, "wins"], a.loc[k, "losses"]) != (b.loc[k, "wins"], b.loc[k, "losses"])
                 or abs(a.loc[k, "pf_per_game"] - b.loc[k, "pf_per_game"]) > 0.05
                 or abs(a.loc[k, "pa_per_game"] - b.loc[k, "pa_per_game"]) > 0.05)]
    return "manager rows: " + (", ".join(moves) or "no change")


def engine_changes(tables: dict, cfg: dict) -> list[str]:
    labels, ex, ppg = conference_labels(cfg), excluded_manager_keys(cfg), excluded_games(cfg, "ppg")
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    cut = _cut(tables)
    leg = mh.conference_tables(cut, labels, ex, ppg, legacy_mode=True)
    lines = [f"INFO  legacy rules, 2020-{LAST_SEASON}: {_summary_line(leg)}"]
    for fix, text in mh.ENGINE_CHANGES.items():
        eng = mh.conference_tables(cut, labels, ex, ppg, fixes={fix})
        lines.append(f"INFO  engine fix [{fix}] {text}")
        lines.append(f"INFO      2020-{LAST_SEASON}: {_summary_line(eng)}")
        lines.append(f"INFO      {_manager_moves(leg, eng, names)}")
    lines.append(f"INFO  engine, every finished week (the live season's too): "
                 f"{_summary_line(mh.conference_tables(tables, labels, ex, ppg))}")
    return lines


def verify_matchup_history(tables: dict, golden: dict, cfg: dict) -> tuple[list[Comparison], list[str]]:
    page = golden["extra_analytics_matchups"]
    cut = _cut(tables)
    closest_checks, closest_info = check_closest(cut, page, cfg)
    checks = [check_h2h(cut, page, cfg), *closest_checks, *check_conference(cut, page, cfg)]
    info = [f"INFO  tables cut at {LAST_SEASON} (the page's build); legacy rules"] + closest_info
    return checks, info + engine_changes(tables, cfg)

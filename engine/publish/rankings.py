"""Weekly rankings: editorial files, frozen snapshots, and the fields every build derives.

Decisions 7.9 and 7.13 (layout agreed 2026-10-05). A ranked week has three parts:

    editorial  leagues/<league>/editorial/rankings/<season>_weekNN.json
               what the commissioner writes: per manager rank, synopsis, blurb,
               screenshots; the week's label; the matchup of the week (the two
               managers and its blurb); hide_archetype_link
    snapshot   leagues/<league>/snapshots/rankings/<season>_weekNN.json
               the computed fields that are true only on the day the week is
               published (projections, projected SOS, draft surplus to date,
               the draft-day record, season point totals, rosters, projected
               lineups). `engine rankings new` writes one for the live week and
               never rewrites it, so a week's numbers never move after its
               blurbs are written against them
    derived    recomputed every build: record, PPG, last score and streak
               through the week before (regular-season games), prev_rank,
               rank_change, avg_rank (from the editorial ranks), and the manifest

Other editorial files in the folder (`<season>_playoff_<round>.json`, the
playoff previews) are published as written.

Rules (METRICS_REFERENCE, Weekly Rankings):
    record_to_date  "W-L" ("W-L-T" with ties) over the season's regular-season
                    games before the week
    ppg_to_date     mean of those scores, Python round to 2 places (a game in
                    analysis.exclude_games with from: [ppg] is left out); None
                    before the first game
    last_score      the latest of those scores; streak "W3" / "L1" / "T1"
    prev_rank       the manager's rank in the season's previous ranked week;
                    rank_change = prev_rank - rank
    avg_rank        mean of the manager's ranks this season through this week,
                    1 place; None in the season's first ranked week (Ethan,
                    2026-10-05: one rule for every season; files before 2026
                    used the prior weeks' average)
    adp_value       week 1: mean adp_deviation (ADP - overall pick) over the
                    QB/RB/WR/TE picks, 2 places
    position_spend  week 1: share of QB/RB/WR/TE draft capital by position,
                    1 place; a pick's capital halves every three rounds
                    (0.5 ** (round / 3)), recovered exactly from 2026 week 1
    draft_archetype week 1: the draft's cluster in the draft-fingerprints model,
                    its name (editorial archetypes.yaml), the three nearest
                    finished manager-seasons, the distance to its cluster's
                    center and the margin over the next center ("clear" from
                    a margin of 1.0, else "borderline")
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from engine.config import excluded_games
from engine.legacy import name_to_key

EDITORIAL_DIR = Path("editorial") / "rankings"
SNAPSHOT_DIR = Path("snapshots") / "rankings"
WEEK_FILE = re.compile(r"^(\d{4})_week(\d{2})\.json$")
PREVIEW_FILE = re.compile(r"^(\d{4})_playoff_([a-z0-9_]+)\.json$")

EDITORIAL_WEEK = ("season", "week", "label", "blurb_label", "hide_archetype_link")
EDITORIAL_TEAM = ("manager", "rank", "synopsis", "blurb", "screenshots")
DERIVED_TEAM = ("prev_rank", "rank_change", "avg_rank", "ppg_to_date", "record_to_date", "last_score", "streak")
MOTW = "matchup_of_the_week"
MOTW_DERIVED = ("rank", "record")
SKILL = ("QB", "RB", "WR", "TE")
KOTH_POOL = 20                 # the rankings page's King of the Hill pools show the top 20 per position
CLEAR_MARGIN = 1.0             # archetype "clear" when its center is at least this much nearer than the next
CAPITAL_HALF_LIFE_ROUNDS = 3   # position_spend: a pick's draft capital halves every 3 rounds

# key order of a merged (legacy-shaped) team row; keys not listed follow in their own order
TEAM_ORDER = ["manager", "rank", "prev_rank", "rank_change", "avg_rank", "ppg_to_date", "record_to_date",
              "last_score", "streak", "proj_ppg", "adp_value", "position_spend", "sos_avg_opp_ppg", "sos_rank",
              "synopsis", "blurb", "draft_archetype", "draft_grade", "draft_surplus_total", "draft_picks",
              "screenshots", "proj_ppg_ros"]


def week_stem(season: int, week: int) -> str:
    return f"{int(season)}_week{int(week):02d}"


# ---------------------------------------------------------------- files

def league_dir(ctx) -> Path | None:
    base = getattr(ctx, "league_dir", None)
    return None if base is None else Path(base)


def read_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def load_folder(base: Path | None, sub: Path) -> dict[str, dict]:
    """file name -> parsed JSON, for every .json file in `base/sub` (empty when absent)."""
    if base is None or not (base / sub).is_dir():
        return {}
    return {p.name: read_json(p) for p in sorted((base / sub).glob("*.json"))}


def week_files(files: dict[str, dict]) -> dict[tuple[int, int], tuple[str, dict]]:
    out = {}
    for name, data in files.items():
        m = WEEK_FILE.match(name)
        if m:
            out[(int(m.group(1)), int(m.group(2)))] = (name, data)
    return dict(sorted(out.items()))


def preview_files(files: dict[str, dict]) -> dict[str, dict]:
    return {n: d for n, d in sorted(files.items()) if PREVIEW_FILE.match(n)}


# ---------------------------------------------------------------- split and merge

def split(file: dict) -> tuple[dict, dict | None]:
    """A published week file -> (editorial, snapshot or None). Lossless: merge()
    with the derived fields rebuilds the file. Anything that is neither editorial
    nor derived belongs to the snapshot."""
    ed = {k: file[k] for k in EDITORIAL_WEEK if k in file}
    snap: dict = {"season": file["season"], "week": file["week"]}
    ed["teams"], teams = [], []
    for t in file.get("teams") or []:
        ed["teams"].append({k: t[k] for k in EDITORIAL_TEAM if k in t})
        rest = {k: v for k, v in t.items() if k not in EDITORIAL_TEAM and k not in DERIVED_TEAM}
        if rest:
            teams.append({"manager": t["manager"], **rest})
    if teams:
        snap["teams"] = teams
    motw = file.get(MOTW)
    if motw:
        ed[MOTW] = {"team_a": motw["team_a"]["manager"], "team_b": motw["team_b"]["manager"]}
        ed[MOTW].update({k: v for k, v in motw.items() if k not in ("team_a", "team_b")})
        lineups = {}
        for side in ("team_a", "team_b"):
            rest = {k: v for k, v in motw[side].items() if k != "manager" and k not in MOTW_DERIVED}
            if rest:
                lineups[motw[side]["manager"]] = rest
        if lineups:
            snap["lineups"] = lineups
    for k, v in file.items():
        if k not in EDITORIAL_WEEK and k not in ("teams", MOTW):
            snap[k] = v
    return ed, (snap if len(snap) > 2 else None)


def _ordered(row: dict, order: list[str]) -> dict:
    out = {k: row[k] for k in order if k in row}
    out.update({k: v for k, v in row.items() if k not in out})
    return out


def merge(editorial: dict, snapshot: dict | None, derived: dict, lookup: dict[str, str]) -> dict:
    """editorial + snapshot + derived -> the week file the page reads.
    derived: manager key -> {derived field: value}; lookup: name -> key."""
    key = lambda n: lookup.get(str(n).strip().lower(), n)
    snap = snapshot or {}
    snap_teams = {key(t["manager"]): t for t in snap.get("teams") or []}
    lineups = {key(m): v for m, v in (snap.get("lineups") or {}).items()}
    out = {k: editorial[k] for k in EDITORIAL_WEEK if k in editorial}
    teams = []
    for t in editorial.get("teams") or []:
        k = key(t["manager"])
        row = {**t, **derived.get(k, {}),
               **{f: v for f, v in snap_teams.get(k, {}).items() if f != "manager"}}
        teams.append(_ordered(row, TEAM_ORDER))
    motw = editorial.get(MOTW)
    if motw:
        m = {}
        for side in ("team_a", "team_b"):
            k = key(motw[side])
            d = derived.get(k, {})
            m[side] = {"manager": motw[side], "rank": next((t["rank"] for t in editorial["teams"]
                                                            if key(t["manager"]) == k), None),
                       "record": d.get("record_to_date"), **lineups.get(k, {})}
        m.update({f: v for f, v in motw.items() if f not in ("team_a", "team_b")})
        out[MOTW] = m
    out["teams"] = teams
    for f, v in snap.items():
        if f not in ("season", "week", "teams", "lineups"):
            out[f] = v
    return out


# ---------------------------------------------------------------- derived fields

def results_from_games(games: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """season, week, manager_key, points, result (W/L/T), is_playoff, counts_ppg: one row per
    team and counted game."""
    skip = excluded_games(cfg, "ppg")
    rows = []
    for r in games.itertuples():
        for k, pts, res in ((r.team_a_key, r.team_a_points, r.team_a_result),
                            (r.team_b_key, r.team_b_points, r.team_b_result)):
            rows.append({"season": int(r.season), "week": int(r.week), "manager_key": k, "points": float(pts),
                         "result": str(res), "is_playoff": bool(r.is_playoff),
                         "counts_ppg": (int(r.season), int(r.week), k) not in skip})
    return pd.DataFrame(rows, columns=["season", "week", "manager_key", "points", "result", "is_playoff",
                                       "counts_ppg"])


def record_fields(res: pd.DataFrame) -> dict:
    """The record fields from one manager's earlier games (sorted by week)."""
    if not len(res):
        return {"ppg_to_date": None, "record_to_date": "0-0", "last_score": None, "streak": None}
    w, l, t = (int((res["result"] == x).sum()) for x in ("W", "L", "T"))
    pts = res.loc[res["counts_ppg"], "points"].to_numpy(float)
    seq = list(res["result"])
    n = 1
    while n < len(seq) and seq[-1 - n] == seq[-1]:
        n += 1
    return {"ppg_to_date": round(float(np.mean(pts)), 2) if len(pts) else None,
            "record_to_date": f"{w}-{l}" + (f"-{t}" if t else ""),
            "last_score": float(res["points"].iloc[-1]), "streak": f"{seq[-1]}{n}"}


def derived_fields(weeks: dict[tuple[int, int], dict], results: pd.DataFrame, lookup: dict[str, str]) -> dict:
    """(season, week) -> manager key -> derived fields, for every editorial week."""
    key = lambda n: lookup.get(str(n).strip().lower(), n)
    reg = results[~results["is_playoff"]].sort_values(["season", "week"], kind="stable")
    by_mgr = {k: g for k, g in reg.groupby(["season", "manager_key"], sort=False)}
    out: dict = {}
    history: dict = {}
    prev_ranks: dict = {}
    for (season, week), ed in sorted(weeks.items()):
        if season not in history:
            history[season], prev_ranks = {}, {}
        ranks = {key(t["manager"]): t.get("rank") for t in ed.get("teams") or []}
        cur = {}
        for k, rank in ranks.items():
            g = by_mgr.get((season, k), reg.iloc[0:0])
            row = record_fields(g[g["week"] < week])
            prev = prev_ranks.get(k)
            hist = history[season].setdefault(k, [])
            if rank is not None:
                hist.append(rank)
            first = not prev_ranks
            row.update({"prev_rank": prev, "rank_change": (prev - rank) if prev is not None and rank is not None
                        else None,
                        "avg_rank": None if first or not hist else round(sum(hist) / len(hist), 1)})
            cur[k] = row
        out[(season, week)] = cur
        prev_ranks = {k: r for k, r in ranks.items() if r is not None}
    return out


def manifest(editorial: dict[str, dict]) -> list[dict]:
    """rankings/manifest.json from the editorial files present: seasons newest first, each
    with its ranked weeks, playoff preview rounds and week labels."""
    seasons: dict[int, dict] = {}
    for (season, week), (_, ed) in week_files(editorial).items():
        s = seasons.setdefault(season, {"season": season, "weeks": []})
        s["weeks"].append(week)
        if ed.get("label"):
            s.setdefault("weekLabels", {})[str(week)] = ed["label"]
    for name in preview_files(editorial):
        m = PREVIEW_FILE.match(name)
        s = seasons.setdefault(int(m.group(1)), {"season": int(m.group(1)), "weeks": []})
        s.setdefault("playoffRounds", []).append(m.group(2))
    out = []
    for season in sorted(seasons, reverse=True):
        s = seasons[season]
        out.append(_ordered(s, ["season", "weeks", "playoffRounds", "weekLabels"]))
    return out


# ---------------------------------------------------------------- draft-day fields

def capital(rnd: int) -> float:
    return 0.5 ** (int(rnd) / CAPITAL_HALF_LIFE_ROUNDS)


def adp_value(picks: list[dict]) -> float | None:
    devs = [p["adp_deviation"] for p in picks if p.get("pos") in SKILL and p.get("adp_deviation") is not None]
    return round(float(np.mean(devs)), 2) if devs else None


def position_spend(picks: list[dict]) -> dict | None:
    tot = {pos: 0.0 for pos in SKILL}
    for p in picks:
        if p.get("pos") in SKILL:
            tot[p["pos"]] += capital(p["round"])
    s = sum(tot.values())
    return {pos: round(100 * v / s, 1) for pos, v in tot.items()} if s else None


# ---------------------------------------------------------------- the snapshot generator

def _r(v, n):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA else round(float(v), n)


def _abbrevs(tables: dict, season: int) -> dict[int, str]:
    pt = tables.get("pro_teams")
    if pt is None or not len(pt):
        return {}
    pt = pt[pt["season"] == season] if (pt["season"] == season).any() else pt
    return {int(i): a for i, a in zip(pt["pro_team_id"], pt["abbrev"])}


def _player_teams(tables: dict, season: int) -> dict[int, int]:
    """player id -> NFL team id now: the live projections, else the season's player stats."""
    out = {}
    ps = tables.get("player_stats")
    if ps is not None and len(ps):
        ps = ps[ps["season"] == season]
        out.update({int(p): int(t) for p, t in zip(ps["player_id"], ps["pro_team_id"])})
    pr = tables.get("projections")
    if pr is not None and len(pr):
        pr = pr[pr["season"] == season]
        out.update({int(p): int(t) for p, t in zip(pr["player_id"], pr["pro_team_id"])})
    return out


def _opponents(tables: dict, season: int, week: int, abbrev: dict[int, str]) -> dict[int, str]:
    """NFL team id -> "PHI" (home) or "@PHI" (away) that week; empty when the pull has no pro schedule."""
    pg = tables.get("pro_games")
    if pg is None or not len(pg):
        return {}
    pg = pg[(pg["season"] == season) & (pg["week"] == week)]
    return {int(t): ("" if bool(h) else "@") + abbrev.get(int(o), str(o))
            for t, o, h in zip(pg["pro_team_id"], pg["opponent_pro_team_id"], pg["home"])}


def draft_record(tables: dict, analysis: dict, season: int, names) -> dict[str, list[dict]]:
    """manager key -> the season's picks as the rankings page lists them (draft-day fields)."""
    dp = tables["draft_picks"]
    dp = dp[dp["season"] == season].sort_values("overall_pick")
    pl = tables["players"].set_index("player_id")
    adp = tables.get("adp")
    adp = {} if adp is None else {int(p): float(a) for p, a in zip(adp.loc[adp["season"] == season, "player_id"],
                                                                     adp.loc[adp["season"] == season, "adp"])
                                   if not pd.isna(p)}
    team = _player_teams(tables, season)
    abbrev = _abbrevs(tables, season)
    out: dict[str, list[dict]] = {}
    for r in dp.itertuples():
        pid = int(r.player_id)
        a = adp.get(pid)
        out.setdefault(r.manager_key, []).append({
            "player": pl.loc[pid, "player_name"] if pid in pl.index else None,
            "nfl_team": abbrev.get(team.get(pid)), "pos": pl.loc[pid, "position"] if pid in pl.index else None,
            "round": int(r.round), "pick_in_round": int(r.round_pick), "overall": int(r.overall_pick),
            "espn_adp": a, "adp_deviation": None if a is None else round(a - int(r.overall_pick), 1),
            "grade": None, "_player_id": pid})
    return out


def archetype_fields(analysis: dict, season: int, meta: dict[int, dict], names) -> dict[str, dict]:
    m = analysis.get("draft_archetype_matches")
    if m is None or not len(m):
        return {}
    ms = analysis.get("manager_seasons")
    ppg = {} if ms is None else {(int(s), k): v for s, k, v in zip(ms["season"], ms["manager_key"], ms["pf_per_game"])}
    out = {}
    for k, g in m[m["season"] == season].sort_values("rank").groupby("manager_key", sort=False):
        r = g.iloc[0]
        margin = _r(r["margin_over_2nd"], 2)
        out[k] = {"cluster_id": int(r["cluster"]), "name": meta.get(int(r["cluster"]), {}).get("name"),
                  "confidence": "clear" if margin is not None and margin >= CLEAR_MARGIN else "borderline",
                  "comparisons": [{"manager": names(c["comp_manager_key"]), "season": int(c["comp_season"]),
                                   "archetype": meta.get(int(c["comp_cluster"]), {}).get("name"),
                                   "ppg": _r(ppg.get((int(c["comp_season"]), c["comp_manager_key"])), 1),
                                   "dist": _r(c["comp_dist"], 2)} for _, c in g.iterrows()],
                  "dist_to_nearest": _r(r["dist_to_nearest"], 2), "margin_over_2nd": margin}
    return out


def projected_lineups(tables: dict, analysis: dict, season: int, week: int, names) -> dict[str, dict]:
    """manager name -> {proj_total, starters}: the engine's projected starting lineup for the week."""
    from engine.analytics import lineups as lineups_mod
    from engine.publish.pages.champions import slot_label

    pl = analysis.get("projected_lineups")
    if pl is None or not len(pl):
        return {}
    pl = pl[(pl["season"] == season) & (pl["week"] == week)]
    abbrev = _abbrevs(tables, season)
    team = _player_teams(tables, season)
    opp = _opponents(tables, season, week, abbrev)
    out = {}
    for k, g in pl.groupby("manager_key", sort=True):
        order = {s: i for i, s in enumerate(lineups_mod.display_order(list(g["slot"])))}
        g = g.assign(_o=g["slot"].map(order)).sort_values(["_o", "projected_points"], ascending=[True, False],
                                                           kind="stable")
        starters = []
        for r in g.itertuples():
            t = team.get(int(r.player_id)) if not pd.isna(r.player_id) else None
            starters.append({"player": r.player_name, "nfl_team": abbrev.get(t), "pos": r.position,
                             "slot": slot_label(r.slot), "opp": opp.get(t), "proj": _r(r.projected_points, 1)})
        out[names(k)] = {"proj_total": _r(g["projected_points"].sum(), 1), "starters": starters}
    return out


def rosters_and_totals(tables: dict, season: int, picks: dict[str, list[dict]], names) -> tuple[dict, list[dict]]:
    """(player_season_totals, undrafted_players). Totals: season points to date for every drafted
    QB/RB/WR/TE and every listed undrafted player. Undrafted players: each QB/RB/WR/TE on a roster now
    who is not on that manager's own draft list (with the manager), plus the best free agents never
    drafted, enough to fill the page's King of the Hill pools (top 20 per position)."""
    ps = tables["player_stats"]
    ps = ps[ps["season"] == season]
    pts = {int(p): float(v) for p, v in zip(ps["player_id"], ps["total_points"])}
    pl = tables["players"].set_index("player_id")
    abbrev = _abbrevs(tables, season)
    team = _player_teams(tables, season)
    drafted_by = {p["_player_id"]: k for k, lst in picks.items() for p in lst}
    pr = tables.get("projections")
    roster = pd.DataFrame(columns=["player_id", "manager_key"])
    if pr is not None and len(pr) and (pr["season"] == season).any():
        cur = pr[(pr["season"] == season) & (pr["source"] == "roster")]
        cur = cur[cur["week"] == cur["week"].min()]
        roster = cur[["player_id", "manager_key"]].drop_duplicates("player_id")
    else:
        lu = tables["lineups"]
        lu = lu[lu["season"] == season]
        if len(lu):
            roster = lu[lu["week"] == lu["week"].max()][["player_id", "manager_key"]].drop_duplicates("player_id")
    on_roster = {int(p): k for p, k in zip(roster["player_id"], roster["manager_key"])}

    def entry(pid, k=None):
        e = {"player": pl.loc[pid, "player_name"], "pos": pl.loc[pid, "position"], "nfl_team": abbrev.get(team.get(pid))}
        if k is not None:
            e["manager"] = names(k)
        return e

    undrafted = []
    for pid, k in sorted(on_roster.items(), key=lambda x: (str(pl.loc[x[0], "player_name"]) if x[0] in pl.index
                                                           else "")):
        if pid in pl.index and pl.loc[pid, "position"] in SKILL and drafted_by.get(pid) != k:
            undrafted.append((pid, k))
    fa = ps[~ps["player_id"].isin(set(drafted_by) | set(on_roster)) & ps["position"].isin(SKILL)]
    fa = fa[fa["total_points"] > 0].sort_values(["total_points", "player_id"], ascending=[False, True])
    fa = fa.groupby("position", sort=False).head(KOTH_POOL)
    undrafted += [(int(p), None) for p in fa["player_id"] if int(p) in pl.index]
    undrafted.sort(key=lambda x: (str(pl.loc[x[0], "player_name"]), x[1] or ""))
    listed = [entry(p, k) for p, k in undrafted]
    totals = {}
    for pid in sorted({p["_player_id"] for lst in picks.values() for p in lst if p.get("pos") in SKILL}
                      | {p for p, _ in undrafted}):
        if pid in pl.index:
            totals[f"{pl.loc[pid, 'player_name']}|{pl.loc[pid, 'position']}"] = _r(pts.get(pid, 0.0), 2)
    return dict(sorted(totals.items())), listed


def generate_snapshot(ctx, season: int, week: int, earlier: dict | None, names, archetypes: dict[int, dict]) -> dict:
    """The computed fields of a live week, from the current tables. `earlier`: the season's first
    snapshot (the draft-day record is copied from it; without one this is week one of the season
    and the draft-day fields, adp_value, position_spend and the archetype are computed)."""
    t, a = ctx.tables, ctx.analysis
    keys = sorted(set(t["teams"].loc[t["teams"]["season"] == season, "manager_key"]))
    ptw = a.get("projected_team_weeks")
    proj = {} if ptw is None else {k: v for k, v in zip(ptw.loc[(ptw["season"] == season) & (ptw["week"] == week),
                                                                 "manager_key"],
                                                         ptw.loc[(ptw["season"] == season) & (ptw["week"] == week),
                                                                 "proj_points"])}
    sos = a.get("projected_sos")
    sos = {} if sos is None else {r["manager_key"]: r for r in sos[sos["season"] == season].to_dict("records")}
    grades = a.get("draft_season_grades")
    grades = {} if grades is None else dict(zip(grades.loc[grades["season"] == season, "manager_key"],
                                                grades.loc[grades["season"] == season, "draft_grade"]))
    ds = a.get("draft_surplus")
    surplus = {} if ds is None else {int(o): v for o, v in zip(ds.loc[ds["season"] == season, "overall_pick"],
                                                              ds.loc[ds["season"] == season, "surplus"])}
    fresh = draft_record(t, a, season, names)
    lookup = name_to_key(ctx.cfg)
    old = {}
    for tm in (earlier or {}).get("teams") or []:
        if tm.get("draft_picks"):
            old[lookup.get(str(tm["manager"]).strip().lower(), tm["manager"])] = tm["draft_picks"]
    arche = {} if earlier else archetype_fields(a, season, archetypes, names)
    teams = []
    for k in keys:
        row: dict = {"manager": names(k), "proj_ppg": _r(proj.get(k), 1)}
        s = sos.get(k, {})
        row.update({"proj_ppg_ros": _r(s.get("own_avg_proj_ppg"), 2), "sos_avg_opp_ppg": _r(s.get("sos_avg_opp_ppg"), 2),
                    "sos_rank": None if s.get("sos_rank") is None else int(s["sos_rank"])})
        g = _r(grades.get(k), 2)
        row.update({"draft_grade": g, "draft_surplus_total": g})
        if k in old:
            picks = [{f: v for f, v in p.items() if f != "surplus_value"} for p in old[k]]
        else:
            picks = [{f: v for f, v in p.items() if f != "_player_id"} for p in fresh.get(k, [])]
        for p in picks:
            p["surplus_value"] = None if p.get("pos") not in SKILL else _r(surplus.get(int(p["overall"])), 4)
        row["draft_picks"] = picks
        if not earlier:
            row["adp_value"] = adp_value(picks)
            row["position_spend"] = position_spend(picks)
            if k in arche:
                row["draft_archetype"] = arche[k]
        teams.append(row)
    totals, undrafted = rosters_and_totals(t, season, fresh, names)
    return {"season": int(season), "week": int(week), "teams": teams,
            "lineups": projected_lineups(t, a, season, week, names),
            "player_season_totals": totals, "undrafted_players": undrafted}

"""The change report: what the live pages show differently in a new build.

At milestone M1 (docs/PUBLISH_PLAN.md section 8) the live root switched from the files the
PC wrote to the engine's legacy views; the report listed every changed number for review
first (M1a). From M1 on it is each deploy's release notes: the deploy fetches the site that
is live (fetch() below), compares each legacy view in the new build (dist/) with it, and
publishes `changes.html` (and `changes.json`) beside the build. Against an engine build the
curated M1 reasons are left out (report() below).

Per page:
    why          the reasons, in plain words, each tied to a decision or a METRICS_REFERENCE
                 section (curated below; a change with no reason here is a question for review)
    summary      the build's own INFO lines for that page (engine vs the live file)
    counts       per file, by kind (Tally below): values changed, filled in or left blank,
                 records only one side has; counted apart, since they are not changes:
                 numbers that differ only in rounding, pairings listed with their sides
                 the other way round, and records from the live season the live file
                 does not have yet
    examples     the first differences of each file

Comparison rules (the files are not all keyed): JSON, CSV, the .js globals and the data
literals inline in the pages are compared value by value; a list of records is matched
by what it is about (identity() below), so a reordered list is not a change and a changed
number shows as a changed value.
"""

from __future__ import annotations

import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from engine.publish.legacy_view import read_js_globals, read_literal
from engine.publish.pages.headshots import norm

TOL = 1e-6
EXAMPLES = 6
VAR = re.compile(r"(?:var|const|let)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=")

# page -> (title, legacy files, INFO line markers, reasons)
PAGES = [
    ("matchups", "Matchups", ["data/matchups.json", "data/matchup_data.csv"], ["matchups.json", "matchup_data.csv"], [
        "Box scores list starters by slot and the bench by points, one shared order on every page, so some bench rows "
        "trade places; no score changes from this.",
        "Players are named and positioned the way ESPN lists them today (for example Travis Etienne Jr., and "
        "Cordarrelle Patterson as a WR), not the spelling or position of that week.",
        "Team A and B in late-2025 and 2026 games follow ESPN's order (counted as sides swapped, not as changes).",
        "The 2020 consolation game that ended 11 to 11 is a Gegwich win, as ESPN records it; the live file had both "
        "teams losing.",
    ]),
    ("managers", "Home and Managers", ["data/preach_manager_stats.csv", "data/franchise_leaders.json",
                                         "data/best_single_week.json", "data/roster_stints.json", "pages/managers.html"],
     ["preach_manager_stats", "franchise_leaders", "best_single_week", "roster_stints", "managers.html"], [
        "Point differential is per game played: 2020 teams with a bye were divided by 13 weeks for 12 games "
        "(METRICS_REFERENCE, Manager Season Stats).",
        "Castaldo's 2024 week 14 forfeit leaves his points per game; the loss still counts (league.yaml exclude_games).",
        "PF/G and PA/G ranks and the luck rating rank the visible managers only (Sullivan and Serafin are hidden).",
        "Draft board map: surplus is the pick-weighted mean, career pooled (session 5 decision), and 2021 picks use the "
        "corrected draft order.",
        "Franchise leaders, best weeks and the roster timeline use ESPN's current player names and add the weeks the "
        "live files do not have yet.",
        "The overall-rank columns of preach_manager_stats.csv (Rank_Win%_Overall, Rank_PPG_Overall, Weighted_Rank_Ovr, "
        "Weighted_Rank_Overall_Value) are left blank: no page reads them.",
    ]),
    ("rankings", "Weekly Rankings", ["data/rankings/", "data/player_headshots.json"],
     ["playoff odds", "rankings", "headshots"], [
        "Average rank is the running average including the week, 1 place, in every season; files before 2026 averaged "
        "the prior weeks (decision 7.13).",
        "Two files typed PPG and last score to 1 place (2023 week 15, 2026 week 2); the engine shows the exact values.",
        "Playoff odds: flat week 1, division winners seeded first, one seed per week, and the live week blended with "
        "projections (METRICS_REFERENCE, Playoff Odds).",
        "Fields some files left blank are filled in: last score and streak in 2023 week 15, average rank in 2024 "
        "weeks 7 and 8.",
        "Headshots come from ESPN by player id (decision 7.5), every page with player pictures. The list covers every "
        "spelling of every player in the league's data; the few names it drops are players the league data does not have.",
    ]),
    ("trade-value", "Trade Value", ["data/page_data.js", "data/network_data.js", "data/winpct_data.js",
                                     "data/trade_explorer_data.js", "data/trade_week_data.js", "data/most_traded_data.js",
                                     "pages/trade-value.html"], ["trade-value", "average QUAD"], [
        "IR weeks do not count as started, and the weekly position baseline leaves IR players out (2026-09-29 rules).",
        "A stint keeps counting across a drop and re-add by the same manager (2026-09-29 rules).",
        "Players are matched by ESPN id instead of by name, which fixes the legacy name mix-ups.",
        "Every grade is relative to all trades, so a change in some trades moves the scales and z-scores of the rest.",
    ]),
    ("waiver-value", "Waiver Value", ["pages/waiver-value.html"], ["waiver-value"], [
        "IR weeks are not counted (no weeks, points or z while a player sits on IR), and the baseline excludes IR.",
        "A same-week drop right after a re-add ends that stint; the legacy file double-counted the next pickup's weeks.",
        "An add, drop and re-add in one week takes the re-add's type.",
    ]),
    ("lineup-efficiency", "Lineup Efficiency", ["pages/lineup-efficiency.html"], ["lineup-efficiency"], [
        "Excluded managers' benches count in the bench average (decision 7.12).",
        "The career grid places playoff weeks by round, counted back from the championship (decision 7.11).",
    ]),
    ("extra-analytics", "Extra Analytics", ["pages/extra-analytics.html"], ["extra-analytics"], [
        "Schedule luck: a tie with the median is half a win, finished weeks only, excluded managers count "
        "(METRICS_REFERENCE, Schedule Luck).",
        "Schedule swap: wins gained scale to each season's length (13 weeks in 2020 and 2021).",
        "Conference records: games against the excluded managers count; the forfeit leaves only Castaldo's PF/G.",
        "Models: the quarterly model is refit correctly (session 4 decision), the attribution fit keeps the excluded "
        "managers' seasons and uses sample SDs, and the gauntlet ranks on unrounded scores.",
    ]),
    ("position-impact", "Position Impact and Life Without Defense",
     ["data/position_impact_data.json", "data/dst_removed_data.json"], ["position impact"], [
        "Games and flip rates cover every counted game the engine has, the live season's finished weeks included.",
        "Players are matched by ESPN id; production by acquisition uses the trade and waiver stints above.",
    ]),
    ("draft", "Draft Analysis, Surplus Value, Draft History, Draft Fingerprints",
     ["pages/draft-analysis.html", "pages/surplus-value.html", "pages/draft-history.html",
      "pages/draft-fingerprints.html"],
     ["draft board", "draft-fingerprints", "surplus-value", "draft-analysis"], [
        "Surplus is the pick-weighted mean with careers pooled over every finished-season pick (session 5 decision).",
        "2021 picks use the corrected draft order (the draft was done offline; ESPN's pick numbers are wrong).",
        "The draft board shows PPG for every pick (K, D/ST and the live season too) and replaces eight hand-kept zeros "
        "with the players' real stats.",
        "Draft analysis: Champ % and PF/G come from the real data (the page contradicted its own file); slot 15 is "
        "listed in who drafted from each slot (decision 7.4).",
        "Draft fingerprints: archetypes from the engine's 10-measure model (session 5 decision), names from the "
        "league's editorial file.",
    ]),
    ("champions", "Champions", ["pages/champions.html"], ["champions.html"], [
        "Starters are listed in the shared box-score order (the page put FLEX before TE and K before D/ST).",
        "Player names as ESPN spells them today; older cards' PF/G to 2 places.",
    ]),
    ("schedule", "Schedule Release", ["data/manager_schedule.json", "data/schedule_by_week.json"],
     ["schedule_release"], [
        "Matchups are listed in ESPN's order (counted as sides swapped, not as changes).",
        "Kelly's 2025 week 14 game: the live file had his opponent at 84.46 in one place and 86.46 everywhere else; "
        "the engine shows 86.46, the score ESPN has.",
    ]),
]


# ---------------------------------------------------------------- loading

def load(path: Path, rel: str):
    """A legacy file as plain values (None when missing)."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if rel.endswith(".json"):
        return json.loads(text)
    if rel.endswith(".csv"):
        d = pd.read_csv(path)
        d = d[[c for c in d.columns if not str(c).startswith("Unnamed")]]
        return {"rows": json.loads(d.to_json(orient="records"))}
    if rel.endswith(".js"):
        return read_js_globals(text)
    out = {}
    for name in dict.fromkeys(VAR.findall(text)):
        try:
            out[name] = read_literal(text, name)
        except Exception:          # a declaration that is not a data literal (a function, an expression)
            continue
    return out


# ---------------------------------------------------------------- comparing

def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


ID_NUMBERS = {"season", "s", "year", "Year", "Season_Year", "week", "wk", "Week", "round", "pick", "pick_in_round",
              "overall", "sp", "start_week", "seed"}
ID_TEXT = {"id", "name", "player", "p", "manager", "m", "Manager", "Team_Name", "Opponent_Name", "team_a", "team_b",
           "manager_a", "manager_b", "opponent", "label", "week_label", "weekLabel", "Week", "a", "b", "champion"}
PICK_NUMBERS = {"round", "pick", "pick_in_round", "overall"}
PLAYER_TEXT = {"player", "p", "name"}


def identity(rec: dict) -> tuple:
    """What a record is about: its naming fields (player, manager, season, week, round, pick, the two sides
    of a pairing in either order; names compared without case, accents or suffixes, so a player ESPN now
    calls "Travis Etienne Jr." is the same record with a changed name). A pick with a player is that player's
    pick in that season whatever its number (the corrected 2021 order renumbers picks). A record with no
    naming field is named by the ones in its own records (a trade by its managers), else by all its text."""
    nums = tuple(sorted((k, v) for k, v in rec.items() if k in ID_NUMBERS and _num(v)))
    text = sorted(norm(v) for k, v in rec.items() if k in ID_TEXT and isinstance(v, str))
    if any(k in PLAYER_TEXT and isinstance(rec[k], str) for k in rec):
        nums = tuple(x for x in nums if x[0] not in PICK_NUMBERS)
    if not text:
        text = sorted(norm(c[k]) for v in rec.values() if isinstance(v, list) for c in v if isinstance(c, dict)
                      for k in c if k in ID_TEXT and isinstance(c[k], str))
    if not text:
        text = sorted(str(v) for v in rec.values() if isinstance(v, (str, bool)))
    return nums, tuple(text)


SIDES = [("teamA", "teamB"), ("team_a", "team_b"), ("score_a", "score_b"), ("manager_a", "manager_b"),
         ("a", "b"), ("Team_Name", "Opponent_Name"), ("Team_Score", "Opponent_Score"), ("seed_a", "seed_b")]
KINDS = ("changed", "filled", "blanked", "rounding", "swapped", "only_engine", "only_live", "newer")


def swapped(rec: dict) -> dict | None:
    """The record with its two sides exchanged (team A for team B), or None when it has no sides."""
    pairs = [(x, y) for x, y in SIDES if x in rec and y in rec]
    if not pairs:
        return None
    out = dict(rec)
    for x, y in pairs:
        out[x], out[y] = rec[y], rec[x]
    return out


def _decimals(x) -> int:
    if isinstance(x, int):
        return 0
    s = repr(float(x))
    if "e" in s:
        return 15
    return len(s.split(".")[1].rstrip("0"))


def rounding_only(old, new) -> bool:
    """True when the two numbers differ only in how many places they are written to (135.1 and 135.05;
    4.33 and 4.3): the less precise one has at least one place and equals the other rounded."""
    d = min(_decimals(old), _decimals(new))
    if d < 1 or _decimals(old) == _decimals(new):
        return False
    return abs(float(old) - float(new)) <= 0.5 * 10 ** -d + 1e-9


class Tally:
    """Differences by kind:
        changed      a value that differs
        filled       a value the live file left blank and the engine fills in
        blanked      a value the live file has and the engine leaves blank
        rounding     the same number written to a different number of places
        swapped      a pairing (a game, a matchup) listed with its sides the other way round
        only_engine  a record or key only in the engine
        only_live    a record or key only in the live file
        newer        anything in the live season (a record, a key or a value inside one), which changes
                     every week: counted apart, not as a difference
    """

    def __init__(self, live_season: int | None = None, examples: int = EXAMPLES):
        for k in KINDS:
            setattr(self, k, 0)
        self.examples: list[str] = []
        self.live_season = live_season
        self.max_examples = examples

    def note(self, kind: str, where: str, old=None, new=None, rec: dict | None = None, key=None,
             season=None) -> None:
        if kind != "swapped" and self.live_season is not None and (
                season == self.live_season or _year(key) == self.live_season or _season(rec) == self.live_season):
            kind = "newer"
        setattr(self, kind, getattr(self, kind) + 1)
        if len(self.examples) < self.max_examples and kind in ("changed", "filled", "blanked", "only_engine",
                                                                 "only_live"):
            if kind in ("changed", "filled", "blanked"):
                self.examples.append(f"{where}: {_short(old)} -> {_short(new)}")
            else:
                label = "only in the engine" if kind == "only_engine" else "only in the live file"
                self.examples.append(f"{label}: {where}")

    def merge(self, other: "Tally") -> None:
        for k in KINDS:
            setattr(self, k, getattr(self, k) + getattr(other, k))
        room = self.max_examples - len(self.examples)
        self.examples += other.examples[:max(room, 0)]

    @property
    def total(self) -> int:
        """Real differences: everything but rounding, swapped sides and newer records."""
        return self.changed + self.filled + self.blanked + self.only_engine + self.only_live

    def counts(self) -> dict:
        return {k: getattr(self, k) for k in KINDS}


SEASON_KEYS = ("season", "s", "Season_Year", "Year", "year")


def _season(rec) -> int | None:
    if not isinstance(rec, dict):
        return None
    v = next((rec[k] for k in SEASON_KEYS if k in rec), None)
    return int(v) if _num(v) else None


def _year(key) -> int | None:
    """A dict key that is a season (DRAFT["2026"], odds["2026"])."""
    k = str(key) if key is not None else ""
    return int(k) if k.isdigit() and len(k) == 4 and k[:2] in ("19", "20") else None


def _short(v) -> str:
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= 70 else s[:67] + "..."


def _label(rec: dict) -> str:
    keys = [k for k in ("manager", "m", "player", "p", "name", "season", "s", "week", "wk", "id") if k in rec]
    return ", ".join(f"{rec[k]}" for k in keys[:4]) or _short(rec)


def _diff(a, b, where: str, live, season) -> Tally:
    t = Tally(live, EXAMPLES)
    compare(a, b, where, t, season)
    return t


def _match(old: list, new: list, where: str, t: Tally, season=None) -> None:
    """Records matched by identity; within one identity each live record takes the engine record (as is, or
    with its sides exchanged) it differs from least."""
    o, n = defaultdict(list), defaultdict(list)
    for x in old:
        o[identity(x)].append(x)
    for x in new:
        n[identity(x)].append(x)
    for k, recs in o.items():
        pool = list(n.get(k, []))
        for a in recs:
            if not pool:
                t.note("only_live", f"{where}[{_label(a)}]", rec=a, season=season)
                continue
            best = None
            for i, b in enumerate(pool):
                for flip in (False, True):
                    bb = swapped(b) if flip else b
                    if bb is None:
                        continue
                    d = _diff(a, bb, f"{where}[{_label(a)}]", t.live_season, season)
                    score = (d.total + d.rounding + d.newer, flip)
                    if best is None or score < best[0]:
                        best = (score, i, flip, d)
                if best[0][0] == 0 and not best[2]:
                    break
            _, i, flip, d = best
            pool.pop(i)
            t.merge(d)
            t.swapped += flip
    for k, recs in n.items():
        for b in recs[len(o.get(k, [])):]:
            t.note("only_engine", f"{where}[{_label(b)}]", rec=b, season=season)


def compare(old, new, where: str, t: Tally, season: int | None = None) -> None:
    """Compare two values into `t`; `season` is the season of the record being compared (the enclosing
    record's season field, a season key on the way down, or the file's season), so a change inside the
    live season counts as newer data."""
    if isinstance(old, dict) and isinstance(new, dict):
        season = _season(new) or _season(old) or season
        for k in old:
            ks = _year(k) or season
            if k in new:
                compare(old[k], new[k], f"{where}/{k}", t, ks)
            else:
                t.note("only_live", f"{where}/{k}", rec=old[k] if isinstance(old[k], dict) else None, season=ks)
        for k in new:
            if k not in old:
                t.note("only_engine", f"{where}/{k}", rec=new[k] if isinstance(new[k], dict) else None,
                       season=_year(k) or season)
    elif isinstance(old, list) and isinstance(new, list):
        if old and new and all(isinstance(x, dict) for x in old + new):
            _match(old, new, where, t, season)
        elif all(not isinstance(x, (dict, list)) for x in old + new) and sorted(map(repr, old)) == sorted(map(repr, new)):
            return                                      # the same values in another order
        elif len(old) == len(new):
            for i, (a, b) in enumerate(zip(old, new)):
                compare(a, b, f"{where}[{i}]", t, season)
        else:
            t.note("changed", where, f"{len(old)} items", f"{len(new)} items", season=season)
    elif _num(old) and _num(new):
        if abs(float(old) - float(new)) > TOL:
            t.note("rounding" if rounding_only(old, new) else "changed", where, old, new, season=season)
    elif old is None and new is not None:
        t.note("filled", where, old, new, season=season)
    elif new is None and old is not None:
        t.note("blanked", where, old, new, season=season)
    elif old != new:
        t.note("changed", where, old, new, season=season)


# ---------------------------------------------------------------- the report

FILE_SEASON = re.compile(r"(?:^|/)((?:19|20)\d\d)_")


def report(dist: Path, site: Path) -> dict:
    """{build, previous, live_season, pages: [{id, title, why, info, files: [{path, new_file, differences,
    <each Tally kind>, examples}]}], unassigned: [...]} for every legacy view in the build.

    `site` is the site that was live before this build. When it is an engine build too (it has a
    build-manifest.json, from M1 on) the report is the week's release notes: `previous` names that build,
    and the M1 reasons and the build's comparisons with the pre-engine files are left out."""
    with open(dist / "build-manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    previous = None
    if (site / "build-manifest.json").is_file():
        with open(site / "build-manifest.json", encoding="utf-8") as f:
            previous = json.load(f).get("build") or {}
    with open(dist / "config.json", encoding="utf-8") as f:
        live = json.load(f).get("live_season")
    verify = {}
    if (dist / "verify.json").is_file():
        with open(dist / "verify.json", encoding="utf-8") as f:
            verify = json.load(f)
    info = [ln for ln in verify.get("info", [])]
    views = [f["path"] for f in manifest["files"] if f["source"] == "generated" and not f["path"].startswith("data/v1/")
             and f["path"] not in ("config.json", "build-manifest.json")]
    pages, used = [], set()
    for pid, title, files, markers, why in PAGES:
        mine = [v for v in views if any(v == p or (p.endswith("/") and v.startswith(p)) for p in files)]
        used |= set(mine)
        rows = []
        for rel in mine:
            t = Tally(live)
            old, new = load(site / rel, rel), load(dist / rel, rel)
            m = FILE_SEASON.search(rel)
            if old is not None:
                compare(old, new, "", t, int(m.group(1)) if m else None)
            rows.append({"path": rel, "new_file": old is None, **t.counts(), "differences": t.total,
                         "examples": t.examples})
        lines = [ln[6:] if ln.startswith("INFO  ") else ln for ln in info
                 if any(m.lower() in ln.lower() for m in markers)]
        if previous is not None:
            why, lines = [], []
        pages.append({"id": pid, "title": title, "why": why, "info": lines, "files": rows})
    unassigned = [v for v in views if v not in used]
    return {"build": manifest.get("build"), "previous": previous, "live_season": live, "pages": pages,
            "unassigned": unassigned}


CSS = """
:root{--bg:#f7f3ec;--card:#fffdf8;--ink:#2b2622;--mid:#6b625a;--line:#e3dbcf;--chg:#a4462f;--new:#2f6f4f}
@media (prefers-color-scheme:dark){:root{--bg:#1d1a17;--card:#262220;--ink:#eee6dc;--mid:#b3a89c;--line:#3b3530;
--chg:#e08a6f;--new:#7cc39a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}h1{font-size:1.6rem;margin:0 0 4px}
.sub{color:var(--mid);margin:0 0 24px}section{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px 18px;margin:0 0 16px}h2{font-size:1.15rem;margin:0 0 8px}ul{margin:6px 0 10px;padding-left:20px}
.info{color:var(--mid);font-size:.9rem}table{width:100%;border-collapse:collapse;font-size:.9rem;margin-top:8px}
th,td{text-align:left;padding:6px 8px;border-top:1px solid var(--line);vertical-align:top}th{color:var(--mid);
font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums}.chg{color:var(--chg);font-weight:600}
.new{color:var(--new)}details{margin-top:4px}summary{cursor:pointer;color:var(--mid)}code{font-size:.82rem;
word-break:break-word}.none{color:var(--mid)}
.wrap{overflow-x:auto}li{overflow-wrap:anywhere}
"""


COLUMNS = [("changed", "Changed"), ("filled", "Filled in"), ("blanked", "Left blank"),
           ("only_engine", "Only in engine"), ("only_live", "Only in live file"), ("rounding", "Rounding only"),
           ("swapped", "Sides swapped"), ("newer", "Newer")]


def _sum(p: dict, k: str) -> int:
    return sum(r[k] for r in p["files"])


def render(rep: dict) -> str:
    e = html.escape
    out = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width,initial-scale=1'><meta name='robots' content='noindex'>",
           f"<title>Change report</title><style>{CSS}</style></head><body><main>"]
    build = e(str((rep.get("build") or {}).get("id")))
    if rep.get("previous") is not None:
        out += ["<h1>What changed in this build</h1>",
                f"<p class='sub'>Build {build} next to the build that was live before it "
                f"({e(str(rep['previous'].get('id')))}). "]
    else:
        out += ["<h1>What changes at M1</h1>",
                f"<p class='sub'>Every live page next to the same page on engine data (build {build}). "]
    out[-1] += ("A difference is a changed value, a value filled in or left blank, or a record only one side has. "
                f"Not counted as differences: numbers that differ only in rounding, games listed with their sides "
                f"the other way round, and anything from the live season ({e(str(rep.get('live_season')))}), "
                "which changes every week (newer).</p>")
    for p in rep["pages"]:
        total = _sum(p, "differences")
        extra = [f"{_sum(p, k):,} {label.lower()}" for k, label in COLUMNS[5:] if _sum(p, k)]
        out.append(f"<section id='{e(p['id'])}'><h2>{e(p['title'])}</h2>")
        out.append(f"<p><span class='chg'>{total:,} differences</span>"
                   + (f" <span class='new'>(also {', '.join(extra)})</span>" if extra else "") + "</p>")
        if p["why"]:
            out.append("<strong>Why</strong><ul>" + "".join(f"<li>{e(w)}</li>" for w in p["why"]) + "</ul>")
        if p["info"]:
            out.append("<div class='info'><strong>The build's summary</strong><ul>"
                       + "".join(f"<li>{e(i)}</li>" for i in p["info"]) + "</ul></div>")
        out.append("<div class='wrap'><table><tr><th>File</th>"
                   + "".join(f"<th>{label}</th>" for _, label in COLUMNS) + "</tr>")
        for r in p["files"]:
            ex = "".join(f"<li><code>{e(x)}</code></li>" for x in r["examples"])
            cell = e(r["path"]) + (" <span class='none'>(new file)</span>" if r["new_file"] else "")
            if ex:
                cell += f"<details><summary>examples</summary><ul>{ex}</ul></details>"
            out.append(f"<tr><td>{cell}</td>" + "".join(f"<td class='n'>{r[k]:,}</td>" for k, _ in COLUMNS)
                       + "</tr>")
        out.append("</table></div></section>")
    if rep["unassigned"]:
        out.append("<section><h2>Files without a page above</h2><ul>"
                   + "".join(f"<li><code>{e(u)}</code></li>" for u in rep["unassigned"]) + "</ul></section>")
    out.append("</main></body></html>")
    return "\n".join(out)


def fetch(base: str, dist: Path, dest: Path, timeout: int = 30) -> int:
    """Download the live site's copy of every legacy view in the build (and its build-manifest.json) from
    `base` (the Pages URL) into `dest`. A file the site does not have is skipped. Returns the files fetched."""
    import urllib.error
    import urllib.request

    with open(dist / "build-manifest.json", encoding="utf-8") as f:
        files = [x["path"] for x in json.load(f)["files"] if x["source"] == "generated"
                 and not x["path"].startswith("data/v1/") and x["path"] not in ("config.json", "build-manifest.json")]
    n = 0
    files.append("build-manifest.json")
    for rel in files:
        try:
            with urllib.request.urlopen(base.rstrip("/") + "/" + rel, timeout=timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_bytes(body)
        n += 1
    return n


def write(dist: Path, site: Path) -> dict:
    rep = report(dist, site)
    (dist / "changes.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (dist / "changes.html").write_text(render(rep), encoding="utf-8")
    return rep


def summary_lines(rep: dict) -> list[str]:
    out = []
    for p in rep["pages"]:
        c = Counter()
        for r in p["files"]:
            c.update({k: r[k] for k in ("differences", *KINDS)})
        out.append(f"{p['title']}: {c['differences']:,} differences ({c['changed']:,} changed, {c['filled']:,} filled "
                   f"in, {c['blanked']:,} left blank, {c['only_engine']:,} only in the engine, {c['only_live']:,} only "
                   f"in the live files); {c['rounding']:,} rounding only, {c['swapped']:,} sides swapped, "
                   f"{c['newer']:,} newer")
    return out

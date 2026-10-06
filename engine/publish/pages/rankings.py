"""Weekly rankings: weekly-rankings.html (rankings files; the odds chart is pages/odds.py).

Outputs
    data/v1/weekly-rankings/index.json          page model (schema "weekly-rankings-index"): every
                                                ranked week and playoff preview, newest season first
    data/v1/weekly-rankings/<season>-wNN.json   page model (schema "weekly-rankings"), one per week,
                                                keyed by manager key
    data/v1/weekly-rankings/<season>-playoff-<round>.json   page model ("weekly-rankings-preview")
    data/rankings/<season>_weekNN.json          legacy views: editorial + snapshot + derived fields
    data/rankings/<season>_playoff_<round>.json legacy views: the editorial previews as written
    data/rankings/manifest.json                 legacy view: generated from the editorial files

Sources: the league's editorial and snapshot folders (engine/publish/rankings.py,
decision 7.9) and `games` for the derived fields. Stage A check: the files are
rebuilt and compared with the published ones (golden `rankings/rankings_files.json`);
the generator that writes new snapshots is checked on the live season.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np

from engine.config import excluded_manager_keys
from engine.legacy import Comparison, name_to_key
from engine.publish import rankings as R
from engine.publish.build import Output
from engine.publish.diff import compare_json, diff
from engine.publish.editorial import load_editorial
from engine.publish.legacy_view import Names

SCHEMA, INDEX_SCHEMA, PREVIEW_SCHEMA = "weekly-rankings", "weekly-rankings-index", "weekly-rankings-preview"
EDITORIAL_SCHEMA, SNAPSHOT_SCHEMA = "rankings-editorial", "rankings-snapshot"
VERSION = 1
MODEL_DIR = "data/v1/weekly-rankings"
LEGACY_DIR = "data/rankings"


def model_path(name: str) -> str:
    m = R.WEEK_FILE.match(name)
    if m:
        return f"{MODEL_DIR}/{m.group(1)}-w{m.group(2)}.json"
    m = R.PREVIEW_FILE.match(name)
    return f"{MODEL_DIR}/{m.group(1)}-playoff-{m.group(2).replace('_', '-')}.json"


# ---------------------------------------------------------------- page models

def site_path(path):
    """An editorial image path as the legacy page wrote it (relative to pages/, "../images/...") made
    relative to the site root, as every path in the page models is."""
    p = str(path or "")
    while p.startswith("../"):
        p = p[3:]
    return p.lstrip("/")


def week_model(view: dict, lookup: dict[str, str], hidden: set[str], team_names: dict[str, str] | None = None,
               player_id=None) -> dict:
    """A merged week file keyed by manager key (hidden managers dropped, decision 7.3). A name that is
    neither a manager nor an alias is tried as one of the season's team names (`team_names`, lower
    case -> key), else kept as written under `manager`. Each named player gets his `player_id`
    (`player_id(name, pos)`, None when no player matches) so pages find his headshot by id;
    screenshot paths are relative to the site root."""
    team_names = team_names or {}
    pid = player_id or (lambda name, pos: None)

    def with_id(p: dict) -> dict:
        return {**p, "player_id": pid(p.get("player"), p.get("pos"))}

    def key(n):
        n = str(n).strip().lower()
        return lookup.get(n) or team_names.get(n)

    def keyed(row: dict) -> dict:
        k = key(row["manager"])
        out = {"manager_key": k} if k else {"manager": row["manager"]}
        out.update({f: v for f, v in row.items() if f != "manager"})
        return out

    out = {k: v for k, v in view.items() if k not in ("teams", R.MOTW, "undrafted_players")}
    teams = []
    for t in view.get("teams") or []:
        row = keyed(t)
        if row.get("manager_key") in hidden:
            continue
        if row.get("draft_picks"):
            row["draft_picks"] = [with_id(x) for x in row["draft_picks"]]
        if row.get("screenshots"):
            row["screenshots"] = [{**s, "file": site_path(s["file"])} if s.get("file") else dict(s)
                                  for s in row["screenshots"]]
        arch = row.get("draft_archetype")
        if arch and arch.get("comparisons"):
            row["draft_archetype"] = {**arch, "comparisons": [keyed(c) for c in arch["comparisons"]]}
        teams.append(row)
    out["teams"] = teams
    if view.get(R.MOTW):
        m = view[R.MOTW]
        side = lambda s: {**keyed(s), **({"starters": [with_id(x) for x in s["starters"]]} if s.get("starters") else {})}
        out[R.MOTW] = {**{k: v for k, v in m.items() if k not in ("team_a", "team_b")},
                       "team_a": side(m["team_a"]), "team_b": side(m["team_b"])}
    if "undrafted_players" in view:
        out["undrafted_players"] = [with_id(keyed(p) if "manager" in p else dict(p)) for p in view["undrafted_players"]]
    return out


def preview_model(data: dict, lookup: dict[str, str]) -> dict:
    """A playoff preview with each side's manager key beside its name."""
    key = lambda n: lookup.get(str(n).strip().lower(), n)
    out = {k: v for k, v in data.items() if k != "matchups"}
    out["matchups"] = [{**m, **{side: {"manager_key": key(m[side]["manager"]), **m[side]}
                                for side in ("higher_seed", "lower_seed") if isinstance(m.get(side), dict)}}
                       for m in data.get("matchups") or []]
    return out


def index_model(editorial: dict[str, dict]) -> dict:
    seasons = []
    for s in R.manifest(editorial):
        labels = s.get("weekLabels") or {}
        seasons.append({"season": s["season"],
                        "weeks": [{"week": w, "label": labels.get(str(w)), "file": model_path(R.week_stem(s["season"], w) + ".json").split("/")[-1]}
                                  for w in s["weeks"]],
                        "previews": [{"round": r, "file": model_path(f"{s['season']}_playoff_{r}.json").split("/")[-1]}
                                     for r in s.get("playoffRounds") or []]})
    return {"seasons": seasons}


# ---------------------------------------------------------------- Stage A check helpers

def rank_alternatives(files: dict[str, dict]) -> dict[tuple[str, int], set]:
    """(file, team index) -> avg_rank values the older files' rules give (the prior weeks' average
    to 2 places, the running average to 2 places, and both rounded either way at a .x5 tie)."""
    by_season: dict = {}
    for name, d in files.items():
        if R.WEEK_FILE.match(name):
            by_season.setdefault(d["season"], []).append((d["week"], name, d))
    out = {}
    for season, weeks in by_season.items():
        hist: dict = {}
        for _, name, d in sorted(weeks):
            for i, t in enumerate(d["teams"]):
                h = hist.setdefault(t["manager"], [])
                prior = list(h)
                h.append(t["rank"])
                alts = set()
                for seq in (prior, h):
                    if seq:
                        m = sum(seq) / len(seq)
                        alts |= {round(m, 2), round(m, 1), float(np.floor(m * 10) / 10), float(np.ceil(m * 10) / 10)}
                out[(name, i)] = alts
    return out


def known_fn(files: dict[str, dict], regular_weeks: dict[int, int]):
    alts = rank_alternatives(files)

    def known(path: str, eng, leg):
        parts = path.strip("/").split("/")
        name, field = parts[0], parts[-1]
        idx = int(parts[1].split("[")[1].rstrip("]")) if len(parts) > 2 and parts[1].startswith("teams[") else None
        d = files.get(name) or {}
        if field == "avg_rank" and idx is not None and (leg is None or leg in alts.get((name, idx), ())):
            return ("avg_rank by the older rules (the prior weeks' average, blank, or a .x5 tie rounded the other "
                    "way); every week now uses the running average including the week, 1 place (Ethan, 2026-10-05)")
        if field in ("ppg_to_date", "last_score") and isinstance(leg, (int, float)) and isinstance(eng, (int, float)) \
                and leg in (round(eng, 1), float(Decimal(str(eng)).quantize(Decimal("0.1"), ROUND_HALF_UP))):
            return "typed to 1 decimal place (2023 week 15, 2026 week 2)"
        if field in ("last_score", "streak") and leg is None and d.get("week", 0) > regular_weeks.get(d.get("season"), 99):
            return "the end-of-season file left last score and streak blank"
        return None
    return known


NAME_SUFFIXES = (" Jr.", " Sr.", " II", " III", " IV", " V")


def _strip(n):
    n = str(n or "")
    for s in NAME_SUFFIXES:
        if n.endswith(s):
            return n[: -len(s)]
    return n


# ---------------------------------------------------------------- publisher

class RankingsPublisher:
    name = "rankings"
    pages = {"weekly-rankings": None}

    def _inputs(self, ctx):
        base = R.league_dir(ctx)
        editorial = R.load_folder(base, R.EDITORIAL_DIR)
        snaps = R.load_folder(base, R.SNAPSHOT_DIR)
        games = ctx.analysis.get("games")
        if not editorial or games is None:
            return None
        lookup = name_to_key(ctx.cfg)
        weeks = {k: ed for k, (_, ed) in R.week_files(editorial).items()}
        der = R.derived_fields(weeks, R.results_from_games(games, ctx.cfg), lookup)
        views = {name: R.merge(ed, snaps.get(name), der[k], lookup)
                 for k, (name, ed) in R.week_files(editorial).items()}
        return editorial, snaps, lookup, views

    def outputs(self, ctx) -> list[Output]:
        got = self._inputs(ctx)
        if got is None:
            return []
        editorial, _, lookup, views = got
        hidden = excluded_manager_keys(ctx.cfg)
        teams = ctx.tables["teams"]
        from engine.publish.pages.headshots import id_resolver, name_rows
        resolve = id_resolver(name_rows(ctx.tables))
        outs = []
        for name, view in views.items():
            tn = {str(n).strip().lower(): k for n, k in zip(teams.loc[teams["season"] == view["season"], "team_name"],
                                                            teams.loc[teams["season"] == view["season"], "manager_key"])}
            outs.append(Output(f"{LEGACY_DIR}/{name}", view))
            outs.append(Output(model_path(name), week_model(view, lookup, hidden, tn, resolve), SCHEMA, VERSION))
        for name, data in R.preview_files(editorial).items():
            outs.append(Output(f"{LEGACY_DIR}/{name}", data))
            outs.append(Output(model_path(name), preview_model(data, lookup), PREVIEW_SCHEMA, VERSION))
        outs.append(Output(f"{LEGACY_DIR}/manifest.json", R.manifest(editorial)))
        outs.append(Output(f"{MODEL_DIR}/index.json", index_model(editorial), INDEX_SCHEMA, VERSION))
        return outs

    # ------------------------------------------------------------ verify

    def verify(self, ctx) -> list:
        got = self._inputs(ctx)
        if got is None:
            return []
        editorial, snaps, lookup, views = got
        gold = ctx.golden.get("rankings_files") or {}
        checks: list = [self._check_inputs(editorial, snaps)]
        regular = {s["season"]: s["regular_season_weeks"] for s in ctx.config["seasons"]}
        known = known_fn(gold, regular)
        seasons = sorted({d["season"] for n, d in gold.items() if R.WEEK_FILE.match(n)})
        for season in seasons:
            names = [n for n in gold if R.WEEK_FILE.match(n) and gold[n]["season"] == season]
            checks += compare_json(f"legacy view data/rankings/{season}_week*.json ({len(names)} weeks; editorial "
                                   f"+ snapshot + derived)", {n: views.get(n) for n in names},
                                   {n: gold[n] for n in names}, known, by_section=False)
        shared = {n: d for n, d in editorial.items() if n in gold}
        if "manifest.json" in gold:
            checks += compare_json("legacy view data/rankings/manifest.json (from the editorial files)",
                                   R.manifest(shared), gold["manifest.json"], by_section=False)
        for name, data in R.preview_files(editorial).items():
            if name in gold:
                checks += compare_json(f"legacy view data/rankings/{name}", data, gold[name], by_section=False)
        checks += self._check_generator(ctx, gold, snaps, lookup)
        checks += self._info_live(ctx, editorial, snaps)
        return checks

    def _check_inputs(self, editorial: dict, snaps: dict) -> Comparison:
        import jsonschema
        from engine.publish.build import _schema
        ed_v = jsonschema.Draft202012Validator(_schema(EDITORIAL_SCHEMA))
        sn_v = jsonschema.Draft202012Validator(_schema(SNAPSHOT_SCHEMA))
        files = [(n, d, ed_v) for n, d in R.week_files(editorial).values()] + [(n, d, sn_v) for n, d in snaps.items()]
        c = Comparison("rankings editorial and snapshot files vs their JSON schemas", len(files), len(files))
        bad = []
        for n, d, v in files:
            errs = list(v.iter_errors(d))
            if errs:
                bad.append(f"{n}: {errs[0].message[:120]}")
        c.mismatched["files"] = len(bad)
        c.examples = bad[:4]
        return c

    def _season_names(self, ctx, editorial_teams: list[dict]):
        return Names(ctx, [t["manager"] for t in editorial_teams])

    def _check_generator(self, ctx, gold: dict, snaps: dict, lookup: dict) -> list:
        """The snapshot generator on the live season: the draft-day fields from the tables against the
        season's first published week (exact where the inputs still exist), the week-one measures from
        that week's published picks (exact), and INFO lines for what can only drift (projections,
        surplus to date, rosters)."""
        live = ctx.config.get("live_season")
        weeks = sorted(w for (s, w) in R.week_files({n: d for n, d in gold.items()}) if s == live)
        if not weeks or ctx.tables.get("draft_picks") is None:
            return []
        out: list = []
        first = gold[R.week_stem(live, weeks[0]) + ".json"]
        names = self._season_names(ctx, first["teams"])
        key = lambda n: lookup.get(str(n).strip().lower(), n)

        # week-one measures from the published picks (layered check: the file's own inputs)
        c = Comparison(f"rankings generator: adp_value and position_spend from the {live} week {weeks[0]} picks "
                       "vs published", 2 * len(first["teams"]), 2 * len(first["teams"]))
        bad = []
        for t in first["teams"]:
            for f, fn in (("adp_value", R.adp_value), ("position_spend", R.position_spend)):
                if f in t and diff(fn(t["draft_picks"]), t[f], tol=1e-9):
                    bad.append(f"{t['manager']} {f}: legacy={t[f]!r} engine={fn(t['draft_picks'])!r}")
        c.mismatched["values"] = len(bad)
        c.examples = bad[:4]
        out.append(c)

        # draft-day record from the tables
        fresh = R.draft_record(ctx.tables, ctx.analysis, live, names)
        fields = ("player", "pos", "round", "pick_in_round", "overall")
        n = sum(len(t["draft_picks"]) for t in first["teams"]) * len(fields)
        c = Comparison(f"rankings generator: draft record ({', '.join(fields)}) vs the {live} week {weeks[0]} "
                       "file", n, sum(len(v) for v in fresh.values()) * len(fields))
        bad, suffix, adp_diff, team_diff = [], 0, 0, 0
        for t in first["teams"]:
            mine = {p["overall"]: p for p in fresh.get(key(t["manager"]), [])}
            for p in t["draft_picks"]:
                e = mine.get(p["overall"])
                if e is None:
                    bad.append(f"{t['manager']} pick {p['overall']}: missing")
                    continue
                for f in fields:
                    if e[f] == p[f]:
                        continue
                    if f == "player" and _strip(e[f]) == _strip(p[f]):
                        suffix += 1
                    else:
                        bad.append(f"{t['manager']} pick {p['overall']} {f}: legacy={p[f]!r} engine={e[f]!r}")
                adp_diff += e["espn_adp"] != p.get("espn_adp")
                team_diff += e["nfl_team"] != p.get("nfl_team")
        if suffix:
            c.known["ESPN's player name now carries a suffix (Jr., Sr., III)"] = suffix
        c.mismatched["values"] = len(bad)
        c.examples = bad[:4]
        out.append(c)
        out.append(f"INFO  rankings draft record: {adp_diff} of {n // len(fields)} picks' ADP differ from the "
                   f"published draft-day ESPN ADP (the engine's {live} ADP is "
                   f"{'/'.join(sorted(set(ctx.tables['adp'].loc[ctx.tables['adp']['season'] == live, 'source'])))}; "
                   f"published weeks keep their frozen copy), {team_diff} NFL teams differ (players who moved since "
                   "the draft)")

        # the latest week: generated now vs its frozen snapshot
        last = R.week_stem(live, weeks[-1]) + ".json"
        frozen = snaps.get(last)
        if frozen is None:
            return out
        earlier = snaps.get(R.week_stem(live, weeks[0]) + ".json")
        meta = self._archetypes(ctx)
        gen = R.generate_snapshot(ctx, live, weeks[-1], earlier, names, meta)
        out.append(self._drift_info(live, weeks[-1], gen, frozen, gold.get(last) or {}, lookup))
        return out

    def _archetypes(self, ctx) -> dict:
        from engine.publish.pages.fingerprints import archetype_meta
        a = ctx.analysis
        if a.get("draft_archetypes") is None or a.get("draft_profile_seasons") is None:
            return {}
        return archetype_meta(a["draft_archetypes"], a["draft_profile_seasons"], load_editorial(ctx, "archetypes"))

    def _drift_info(self, season, week, gen: dict, frozen: dict, published: dict, lookup) -> str:
        key = lambda n: lookup.get(str(n).strip().lower(), n)
        g = {key(t["manager"]): t for t in gen["teams"]}
        f = {key(t["manager"]): t for t in frozen.get("teams") or []}

        def mad(field):
            vals = [abs(g[k][field] - f[k][field]) for k in f if k in g and g[k].get(field) is not None
                    and f[k].get(field) is not None]
            return f"{np.mean(vals):.2f}" if vals else "n/a"

        same_sos = sum(1 for k in f if k in g and g[k].get("sos_rank") == f[k].get("sos_rank"))
        sv = [abs((pg.get("surplus_value") or 0) - (pf.get("surplus_value") or 0))
              for k in f if k in g for pg, pf in zip(g[k]["draft_picks"], f[k].get("draft_picks") or [])]
        motw = published.get(R.MOTW) or {}
        same_st = tot_st = 0
        gl = {key(m): v for m, v in gen["lineups"].items()}
        for side in ("team_a", "team_b"):
            s = motw.get(side) or {}
            mine = {p["player"] for p in (gl.get(key(s.get("manager"))) or {}).get("starters", [])}
            theirs = {p["player"] for p in s.get("starters") or []}
            same_st += len(mine & theirs)
            tot_st += len(theirs)
        with_opp = sum(1 for v in gen["lineups"].values() for p in v["starters"] if p.get("opp"))
        n_st = sum(len(v["starters"]) for v in gen["lineups"].values())
        und_g = {(p["player"], p.get("manager")) for p in gen["undrafted_players"]}
        und_f = {(p["player"], p.get("manager")) for p in frozen.get("undrafted_players") or []}
        tg, tf = gen["player_season_totals"], frozen.get("player_season_totals") or {}
        same_tot = sum(1 for k in tf if k in tg and tg[k] is not None and abs(tg[k] - tf[k]) < 0.005)
        return (f"INFO  rankings generator on {season} week {week}, today's data vs the published snapshot "
                f"(projections and stats moved since): mean |diff| proj_ppg {mad('proj_ppg')}, proj_ppg_ros "
                f"{mad('proj_ppg_ros')}, sos_avg_opp_ppg {mad('sos_avg_opp_ppg')} (ESPN's current schedule), "
                f"sos_rank same {same_sos} of {len(f)}, draft_grade {mad('draft_grade')}, pick surplus "
                f"{(np.mean(sv) if sv else 0):.2f}; matchup of the week starters {same_st} of {tot_st} the same, "
                f"{with_opp} of {n_st} starters with an NFL opponent; undrafted players {len(und_g)} "
                f"(published {len(und_f)}, {len(und_g & und_f)} in both); season totals {len(tg)} players "
                f"(published {len(tf)}), {same_tot} published totals equal")

    def _info_live(self, ctx, editorial: dict, snaps: dict) -> list[str]:
        """Weekly files on the live site that the editorial folder does not have yet (or has
        differently): run tools/split_rankings.py after a PC update until M1."""
        src = Path(ctx.site_root) / LEGACY_DIR
        if not src.is_dir():
            return []
        missing, differ = [], []
        for p in sorted(src.glob("*.json")):
            if not R.WEEK_FILE.match(p.name):
                continue
            ed, sn = R.split(R.read_json(p))
            if p.name not in editorial:
                missing.append(p.name)
            elif editorial[p.name] != ed or snaps.get(p.name) != sn:
                differ.append(p.name)
        if not missing and not differ:
            return [f"INFO  rankings: every week file in {LEGACY_DIR}/ has its editorial file and snapshot"]
        return [f"INFO  rankings: {len(missing)} week files in {LEGACY_DIR}/ not imported yet "
                f"({', '.join(missing[:4])}), {len(differ)} differ from their editorial file or snapshot "
                f"({', '.join(differ[:4])}); run `python tools/split_rankings.py leagues/<league>/league.yaml`"]


def write_week(ctx, season: int, week: int, force: bool = False) -> list[str]:
    """`engine rankings new`: the live week's snapshot (frozen from now on) and, when the week has no
    editorial file yet, an editorial draft (last week's ranks, empty write-ups) to fill in."""
    base = R.league_dir(ctx)
    stem = R.week_stem(season, week) + ".json"
    snap_path = base / R.SNAPSHOT_DIR / stem
    ed_path = base / R.EDITORIAL_DIR / stem
    if snap_path.exists() and not force:
        raise SystemExit(f"error: {snap_path} exists (snapshots are frozen once published); pass --force to "
                         "regenerate it")
    editorial = R.load_folder(base, R.EDITORIAL_DIR)
    snaps = R.load_folder(base, R.SNAPSHOT_DIR)
    season_weeks = sorted(w for (s, w) in R.week_files(editorial) if s == season and w < week)
    prev = R.week_files(editorial).get((season, season_weeks[-1]))[1] if season_weeks else None
    first_snap = next((snaps[R.week_stem(season, w) + ".json"] for w in season_weeks
                       if R.week_stem(season, w) + ".json" in snaps), None)
    names = Names(ctx, [t["manager"] for t in (prev or {}).get("teams") or []])
    pub = RankingsPublisher()
    snap = R.generate_snapshot(ctx, season, week, first_snap, names, pub._archetypes(ctx))
    R.write_json(snap_path, snap)
    written = [str(snap_path)]
    if not ed_path.exists():
        teams = sorted(snap["teams"], key=lambda t: next((p["rank"] for p in (prev or {}).get("teams") or []
                                                          if name_to_key(ctx.cfg).get(p["manager"].lower()) ==
                                                          name_to_key(ctx.cfg).get(t["manager"].lower())), 99))
        draft = {"season": season, "week": week,
                 **({"hide_archetype_link": prev["hide_archetype_link"]} if prev and "hide_archetype_link" in prev
                    else {}),
                 "teams": [{"manager": t["manager"], "rank": i + 1, "synopsis": "", "blurb": "", "screenshots": []}
                           for i, t in enumerate(teams)]}
        R.write_json(ed_path, draft)
        written.append(str(ed_path))
    return written

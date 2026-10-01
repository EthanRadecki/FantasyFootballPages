"""Draft analysis: draft-analysis.html.

Outputs
    data/v1/draft-analysis.json   page model (schema "draft-analysis"): results by draft slot,
                                  who drafted from each slot, hit rate by round, tier and
                                  position, late-round steals, the career surplus preview
    pages/draft-analysis.html     the page with its inline data and typed HTML replaced

Blocks and their rules:
    slot table (typed HTML)  draft_slot_results in the page's units: playoff %, champ % and
                             PF/G to 1 place, dominance and expected to 2, over/under to 2
                             with an arrow; cell colors below
    PLAYOFF_RATES, OVERPERFS the slot chart series (over/under to 3 places)
    SLOT_DATA                {slot: [[manager, season]]}, every season including the live one
    tier cards (typed HTML)  hit rate per tier (rounds 1-3, 4-7, 8+): rate, hits, picks
    HR_BY_ROUND              hit rate per round, plus the drafted positions per round
    HR_BY_POS                {position: [early, middle, late]} hit rate
    ALL_TIME_STEALS          draft.steals over every finished season; SEASON_STEALS per season
    CAREER_PREVIEW           draft_career_grades: avg, rank, seasons
    ABOVE_AVG_CEIL           the highest points above average among the all-time steals

Slots need at least 2 finished seasons to appear in the results (decision 7.4:
slot 15, used once in 2020, stays in SLOT_DATA only). Cell colors (the page's
builder was lost; this rule reproduces every cell of the current page): rates
and PF/G by z-score among the slots shown, good above +0.2, bad below -1.0;
champ % good when above 0; dominance, expected and over/under by sign.

Hidden managers count in every aggregate and keep their slots in SLOT_DATA
and their picks in the steals lists (decision 7.3: real picks); they are left
out of the surplus preview (a ranking).
The position counts per round cover the hit-rate seasons in engine mode; the
legacy page counted 2020-2024 only (legacy mode reproduces that).

Coverage: finished seasons, as the page shows today (decision 7.8, Stage A).
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd

from engine.analytics import draft as draft_mod
from engine.config import excluded_manager_keys
from engine.legacy import Comparison, name_to_key
from engine.legacy_manager_seasons import legacy_slots, slot_frame, slot_managers_check, slot_table_check
from engine.publish.build import Output
from engine.publish.diff import compare_json
from engine.publish.legacy_view import Names, read_html, read_literal, replace_html, replace_literal
from engine.publish.pages.draft_common import legacy_draft

SCHEMA, VERSION = "draft-analysis", 1
PAGE = "pages/draft-analysis.html"
VARS = ["PLAYOFF_RATES", "OVERPERFS", "SLOT_DATA", "HR_BY_ROUND", "HR_BY_POS", "ALL_TIME_STEALS", "SEASON_STEALS",
        "CAREER_PREVIEW", "ABOVE_AVG_CEIL"]
SLOT_TABLE = ('<table class="da-table">', "<tbody>")         # (anchor, opening tag) of the typed slot table
TIER_CARDS = (None, '<div class="hr-stat-row">')
MIN_SLOT_SEASONS = 2
GOOD_Z, BAD_Z = 0.2, -1.0
POS_COLS = [("rb", "RB"), ("wr", "WR"), ("qb", "QB"), ("te", "TE"), ("k", "K"), ("dst", "D/ST")]
TIER_LABELS = {"Early": "Early Rounds ({lo}-{hi})", "Middle": "Middle Rounds ({lo}-{hi})", "Late": "Late Rounds ({lo}+)"}
STEALS_PER_LIST = 10


# ---------------------------------------------------------------- slot table

def shown_slots(results: pd.DataFrame) -> pd.DataFrame:
    """Slot results the page shows: slots with at least MIN_SLOT_SEASONS seasons (decision 7.4)."""
    return results[results["seasons"] >= MIN_SLOT_SEASONS].sort_values("draft_slot").reset_index(drop=True)


def _band(values: pd.Series) -> list[str]:
    v = values.astype(float)
    sd = v.std(ddof=0)
    z = (v - v.mean()) / sd if sd else v * 0
    return ["good" if x > GOOD_Z else "bad" if x < BAD_Z else "mid" for x in z]


def _signed(v: float, digits: int) -> str:
    """Signed, rounded half away from zero from the value as the page rounds it
    one place further (-0.655 -> -0.66, as the page shows over/under)."""
    d = Decimal(repr(round(float(v), digits + 1))).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return f"{'+' if d >= 0 else ''}{d}"


def cell_classes(f: pd.DataFrame) -> dict[tuple[int, str], str]:
    """(slot, column) -> the cell's class, from the table in the page's units."""
    pl, pf = _band(f["playoff_pct"]), _band(f["pf_per_game"])
    out = {}
    for i, r in enumerate(f.itertuples()):
        s = int(r.slot)
        out |= {(s, "slot"): "val-bold", (s, "seasons"): "",
                (s, "playoff_pct"): f"cell-{pl[i]} val-bold",
                (s, "champ_pct"): f"cell-{'good' if r.champ_pct > 0 else 'bad'} val-bold",
                (s, "pf_per_game"): f"cell-{pf[i]}",
                (s, "dominance"): "cell-good val-green" if r.dominance > 0 else "cell-bad val-red",
                (s, "expected_dominance"): "val-green" if r.expected_dominance > 0 else "val-red",
                (s, "over_under"): "cell-good val-green" if r.over_under > 0 else "cell-bad val-red"}
    return out


def slot_table_html(results: pd.DataFrame) -> str:
    """The typed rows of the Detailed Breakdown table."""
    f = slot_frame(shown_slots(results))
    f["over_under"] = [float(_signed(v, 2)) for v in f["over_under"]]      # the table shows 2 places
    cls = cell_classes(f)
    rows = []
    for r in f.itertuples():
        s = int(r.slot)
        c = lambda col: f' class="{cls[(s, col)]}"' if cls[(s, col)] else ""
        arrow = "&#9650;" if r.over_under > 0 else "&#9660;"
        rows.append(
            f"        <tr><td{c('slot')}>{s}</td><td{c('seasons')}>{int(r.seasons)}</td>"
            f"<td{c('playoff_pct')}>{r.playoff_pct:.1f}%</td><td{c('champ_pct')}>{r.champ_pct:.1f}%</td>"
            f"<td{c('pf_per_game')}>{r.pf_per_game:.1f}</td><td{c('dominance')}>{_signed(r.dominance, 2)}</td>"
            f"<td{c('expected_dominance')}>{_signed(r.expected_dominance, 2)}</td>"
            f"<td{c('over_under')}>{_signed(r.over_under, 2)} {arrow}</td></tr>")
    return "\n" + "\n".join(rows) + "\n      "


_CELL = re.compile(r'<td(?: class="([^"]*)")?>(.*?)</td>')


def parse_slot_table(html: str) -> tuple[pd.DataFrame, list[tuple]]:
    """(numbers in the golden's table shape, every cell's (slot, column, class, text))."""
    cols = ["slot", "seasons", "playoff_pct", "champ_pct", "pf_per_game", "dominance", "expected_dominance",
            "over_under"]
    rows, cells = [], []
    for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        tds = _CELL.findall(tr)
        vals = [float(re.sub(r"[^0-9.+-]", "", t.replace("&#9650;", "").replace("&#9660;", ""))) for _, t in tds]
        row = dict(zip(cols, vals))
        row["slot"], row["seasons"] = int(row["slot"]), int(row["seasons"])
        rows.append(row)
        cells += [(row["slot"], c, cls, t) for c, (cls, t) in zip(cols, tds)]
    return pd.DataFrame(rows), cells


# ---------------------------------------------------------------- hit rate

def round_positions(tables: dict, seasons: list[int]) -> pd.DataFrame:
    """Drafted positions per round (every position, every manager) over the given seasons."""
    dp = tables["draft_picks"].merge(tables["player_seasons"][["season", "player_id", "position"]],
                                     on=["season", "player_id"], how="left")
    dp = dp[dp["season"].isin(seasons)]
    return dp.groupby(["round", "position"]).size().rename("n").reset_index()


def _rate(g: pd.DataFrame) -> float:
    return round(g["hit"].sum() / len(g) * 100, 1) if len(g) else 0.0


def tier_cards_html(h: pd.DataFrame) -> str:
    out = []
    for name, lo, hi in draft_mod.TIERS:
        g = h[h["tier"] == name]
        label = TIER_LABELS.get(name, f"{name} Rounds ({lo}-{hi})").format(lo=lo, hi=hi)
        out.append(f'    <div class="hr-stat-card glass">\n'
                   f'      <div class="hr-stat-tier">{label}</div>\n'
                   f'      <div class="hr-stat-pct hr-{name.lower()}">{_rate(g)}%</div>\n'
                   f'      <div class="hr-stat-sub">{int(g["hit"].sum())} hits from {len(g)} picks</div>\n'
                   f'    </div>')
    return "\n" + "\n".join(out) + "\n  "


def parse_tier_cards(html: str) -> list[dict]:
    pat = re.compile(r'hr-stat-tier">([^<]*)<.*?hr-stat-pct hr-(\w+)">([0-9.]+)%<.*?hr-stat-sub">(\d+) hits from (\d+) '
                     r"picks<", re.S)
    return [{"label": a, "tier": b, "rate": float(c), "hits": int(d), "picks": int(e)} for a, b, c, d, e in pat.findall(html)]


def _steal(r, rank: int, names) -> dict:
    return {"rank": rank, "player": r.player_name, "pos": r.position, "round": int(r.round), "slot": int(r.draft_slot),
            "season": int(r.season), "ppg": round(float(r.ppg), 2), "above": round(float(r.pts_above_avg), 2),
            "games": int(r.games), "manager": names(r.manager_key)}


def steal_lists(h: pd.DataFrame, names) -> tuple[list, dict]:
    """Every manager's picks (decision 7.3: real picks keep excluded managers, as the page shows them)."""
    all_ = [_steal(r, i + 1, names) for i, r in enumerate(draft_mod.steals(h, STEALS_PER_LIST).itertuples())]
    by = {str(int(s)): [_steal(r, i + 1, names) for i, r in enumerate(draft_mod.steals(g, STEALS_PER_LIST).itertuples())]
          for s, g in h.groupby("season")}
    return all_, by


# ---------------------------------------------------------------- views

def analysis_view(results: pd.DataFrame, who: pd.DataFrame, h: pd.DataFrame, positions: pd.DataFrame,
                  career: pd.DataFrame, names) -> dict:
    shown = slot_frame(shown_slots(results))
    slot_data: dict = {}
    for r in who.sort_values(["draft_slot", "season"]).itertuples():
        slot_data.setdefault(str(int(r.draft_slot)), []).append([names(r.manager_key), int(r.season)])
    by_round = []
    pos = positions.set_index(["round", "position"])["n"]
    for rnd, g in h.groupby("round"):
        row = {"round": int(rnd), "tier": draft_mod.tier(int(rnd)), "hit_rate": _rate(g), "total_picks": int(len(g)),
               "hits": int(g["hit"].sum())}
        row |= {col: int(pos.get((rnd, p), 0)) for col, p in POS_COLS}
        by_round.append(row)
    hr_pos = {p: [_rate(h[(h["tier"] == t) & (h["position"] == p)]) for t, _, _ in draft_mod.TIERS]
              for p in ["RB", "WR", "QB", "TE"] if (h["position"] == p).any()}
    steals_all, steals_by = steal_lists(h, names)
    c = career[career["rank"].notna()].sort_values("rank")
    return {
        "slot_table": slot_table_html(results),
        "PLAYOFF_RATES": [float(x) for x in shown["playoff_pct"]],
        "OVERPERFS": [float(x) for x in shown["over_under"]],
        "SLOT_DATA": slot_data, "tier_cards": tier_cards_html(h), "HR_BY_ROUND": by_round, "HR_BY_POS": hr_pos,
        "ALL_TIME_STEALS": steals_all, "SEASON_STEALS": steals_by,
        "CAREER_PREVIEW": [{"manager": names(r.manager_key), "avg": float(r.avg_surplus), "rank": int(r.rank),
                            "seasons": int(r.seasons)} for r in c.itertuples()],
        "ABOVE_AVG_CEIL": max([s["above"] for s in steals_all], default=0.0),
    }


def write_page(text: str, view: dict) -> str:
    for var in VARS:
        text = replace_literal(text, var, view[var])
    text = replace_html(text, SLOT_TABLE[1], view["slot_table"], SLOT_TABLE[0])
    return replace_html(text, TIER_CARDS[1], view["tier_cards"], TIER_CARDS[0])


def read_page(text: str) -> dict:
    out = {v: read_literal(text, v) for v in VARS}
    out["slot_table"] = read_html(text, SLOT_TABLE[1], SLOT_TABLE[0])
    out["tier_cards"] = read_html(text, TIER_CARDS[1], TIER_CARDS[0])
    return out


def analysis_model(results, who, h, positions, career, hidden: set[str]) -> dict:
    ident = lambda k: k
    v = analysis_view(results, who, h, positions, career, ident)
    shown = shown_slots(results)
    tiers = []
    for name, lo, hi in draft_mod.TIERS:
        g = h[h["tier"] == name]
        tiers.append({"tier": name, "first_round": lo, "last_round": None if hi >= 99 else hi,
                      "hit_rate": _rate(g), "hits": int(g["hit"].sum()), "picks": int(len(g))})
    steal = lambda x: {"rank": x["rank"], "player_name": x["player"], "position": x["pos"], "round": x["round"],
                       "draft_slot": x["slot"], "season": x["season"], "ppg": x["ppg"], "above_average": x["above"],
                       "games": x["games"], "manager_key": x["manager"], "hidden": x["manager"] in hidden}
    return {
        "slot_results": [{"draft_slot": int(r.draft_slot), "seasons": int(r.seasons),
                          "playoff_rate": float(r.playoff_rate), "champion_rate": float(r.champion_rate),
                          "pf_per_game": float(r.pf_per_game), "dominance": float(r.dominance),
                          "expected_dominance": float(r.expected_dominance), "over_under": float(r.over_under)}
                         for r in shown.itertuples()],
        "min_slot_seasons": MIN_SLOT_SEASONS,
        "slot_managers": [{"season": int(r.season), "draft_slot": int(r.draft_slot), "manager_key": r.manager_key,
                           "live": bool(r.is_live), "hidden": r.manager_key in hidden}
                          for r in who.sort_values(["draft_slot", "season"]).itertuples()],
        "hit_rate_tiers": tiers, "hit_rate_by_round": v["HR_BY_ROUND"], "hit_rate_by_position": v["HR_BY_POS"],
        "steals": [steal(x) for x in v["ALL_TIME_STEALS"]],
        "season_steals": {k: [steal(x) for x in xs] for k, xs in v["SEASON_STEALS"].items()},
        "career_preview": [{"manager_key": x["manager"], "avg_surplus": x["avg"], "rank": x["rank"],
                            "seasons": x["seasons"]} for x in v["CAREER_PREVIEW"]],
        "above_average_max": v["ABOVE_AVG_CEIL"],
    }


# ---------------------------------------------------------------- Stage A check

SLOT15_REASON = "slot 15 (one season) added to who drafted from each slot (decision 7.4)"


STEALS_REASON = ("page SEASON_STEALS contradicts its source hit_rate_data.json (slot, PPG, games and points "
                 "above average typed from another file); the view has the source value")


TIE_REASON = "steals list tied on points above average; unstable legacy sort"


def steals_source(source: dict | None, view: dict, gold: dict):
    """Excuse a SEASON_STEALS value where the page differs from hit_rate_data.json
    (the script that wrote the lists) and the view has the script's value, and
    a list place two picks tied on points above average (as analyze --verify)."""
    field = {"above": "pts_above_avg"}

    def known(path, eng, leg):
        m = re.match(r"/(SEASON_STEALS/(\d+)|ALL_TIME_STEALS)\[(\d+)\]/(\w+)$", path)
        if not m:
            return None
        lst = (lambda d: d["SEASON_STEALS"][m.group(2)]) if m.group(2) else (lambda d: d["ALL_TIME_STEALS"])
        i = int(m.group(3))
        v, g = lst(view)[i], lst(gold)[i]
        if v["player"] != g["player"] and abs(v["above"] - g["above"]) < 1e-9:
            return TIE_REASON
        if not m.group(2) or source is None:
            return None
        m = re.match(r"/SEASON_STEALS/(\d+)\[(\d+)\]/(\w+)$", path)
        rows = source.get("season_steals", {}).get(m.group(1), [])
        i = int(m.group(2))
        if i >= len(rows):
            return None
        src = rows[i].get(field.get(m.group(3), m.group(3)))
        same = (abs(float(eng) - float(src)) < 1e-9) if isinstance(eng, (int, float)) and isinstance(src, (int, float)) \
            else eng == src
        return STEALS_REASON if same and src != leg else None
    return known


def compare_view(view: dict, gold: dict, stats: pd.DataFrame, cfg: dict, live: set[int],
                 source: dict | None = None) -> list:
    exp_t, exp_cells = parse_slot_table(gold["slot_table"])
    act_t, act_cells = parse_slot_table(view["slot_table"])
    checks: list = [slot_table_check(f"legacy view {PAGE} slot table vs draft_analysis_page.json", exp_t, act_t,
                                     stats, cfg, live, units={"over_under": 0.01})]
    styles = Comparison(f"legacy view {PAGE} slot table cell colors vs draft_analysis_page.json",
                        len(exp_cells), len(act_cells))
    gold_cls = {(s_, c): cls for s_, c, cls, _ in exp_cells}
    rule = cell_classes(exp_t)                 # the color rule reproduces the page from the page's own numbers
    styles.mismatched["rule"] = sum(rule.get(k, "") != v for k, v in gold_cls.items())
    num_e, num_a = exp_t.set_index("slot"), act_t.set_index("slot")
    banded = {c for c in ("playoff_pct", "pf_per_game")
              if (num_e[c] - num_a[c].reindex(num_e.index)).abs().max() > 1e-9}
    bad, excused = [], 0
    for s_, c, cls, _ in act_cells:
        if (s_, c) not in gold_cls or gold_cls[(s_, c)] == cls:
            continue
        if c in banded or (c in num_e and abs(float(num_e.loc[s_, c]) - float(num_a.loc[s_, c])) > 1e-9):
            excused += 1            # the color follows values the slot table check excuses
        else:
            bad.append(f"slot {s_} {c}: {gold_cls[(s_, c)]!r} -> {cls!r}")
    styles.mismatched["cells"] = len(bad)
    if excused:
        styles.known["color set by values that differ from the page (see the slot table check)"] = excused
    styles.examples = bad[:4]
    checks.append(styles)
    who = pd.DataFrame([{"draft_slot": int(s), "season": int(y), "manager_key": n}
                        for s, v in view["SLOT_DATA"].items() for n, y in v])
    lk = name_to_key(cfg)
    who["manager_key"] = [lk[n.strip().lower()] for n in who["manager_key"]]
    checks.append(slot_managers_check(f"legacy view {PAGE} SLOT_DATA vs draft_analysis_page.json", gold["SLOT_DATA"],
                                      who, cfg))
    extra = sorted(set(view["SLOT_DATA"]) - set(gold["SLOT_DATA"]))
    if extra:
        checks.append(f"INFO  {PAGE} SLOT_DATA adds slot(s) {', '.join(extra)}: {SLOT15_REASON}")
    one_unit = lambda path, e, l: ("dominance from the file's rounded PF/G (one unit of the last digit)"
                                   if isinstance(e, float) and abs(e - l) <= 0.001 + 1e-9 else None)
    checks += compare_json(f"legacy view {PAGE} PLAYOFF_RATES", view["PLAYOFF_RATES"], gold["PLAYOFF_RATES"])
    checks += compare_json(f"legacy view {PAGE} OVERPERFS", view["OVERPERFS"], gold["OVERPERFS"], known=one_unit)
    checks += compare_json(f"legacy view {PAGE} tier cards", parse_tier_cards(view["tier_cards"]),
                           parse_tier_cards(gold["tier_cards"]))
    rest = ["HR_BY_ROUND", "HR_BY_POS", "ALL_TIME_STEALS", "SEASON_STEALS", "CAREER_PREVIEW", "ABOVE_AVG_CEIL"]
    checks += compare_json(f"legacy view {PAGE}", {k: view[k] for k in rest}, {k: gold[k] for k in rest},
                           known=steals_source(source, view, gold))
    return checks


class DraftAnalysisPublisher:
    name = "draft-analysis"
    NEEDS = ("draft_slot_results", "draft_slot_managers", "draft_hits", "draft_career_grades")

    def _engine(self, ctx):
        a = ctx.analysis
        h = a["draft_hits"]
        seasons = sorted(int(s) for s in h["season"].unique())
        return (a["draft_slot_results"], a["draft_slot_managers"], h, round_positions(ctx.tables, seasons),
                a["draft_career_grades"])

    def _names(self, ctx, text: str | None) -> Names:
        spelled = []
        if text is not None:
            try:
                spelled = [r["manager"] for r in read_literal(text, "CAREER_PREVIEW")]
                spelled += [n for v in read_literal(text, "SLOT_DATA").values() for n, _ in v]
            except (KeyError, ValueError):
                pass
        return Names(ctx, spelled)

    def outputs(self, ctx) -> list[Output]:
        a = ctx.analysis
        if not all(n in a and len(a[n]) for n in self.NEEDS):
            return []
        parts = self._engine(ctx)
        out = [Output(f"data/v1/{SCHEMA}.json", analysis_model(*parts, excluded_manager_keys(ctx.cfg)), SCHEMA, VERSION)]
        path = ctx.site_root / PAGE
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            out.append(Output(PAGE, write_page(text, analysis_view(*parts, self._names(ctx, text)))))
        return out

    def verify(self, ctx) -> list:
        a = ctx.analysis
        if not all(n in a and len(a[n]) for n in self.NEEDS):
            return []
        from engine.analytics.weeks import live_seasons
        gold = ctx.golden["draft_analysis_page"]
        results, who = legacy_slots(ctx.tables, ctx.cfg)
        legacy = legacy_draft(ctx)
        h = legacy["draft_hits"]
        hit_seasons = sorted(int(s) for s in h["season"].unique())
        positions = round_positions(ctx.tables, hit_seasons[:-1])   # the legacy page left out the last season
        names = Names(ctx, [r["manager"] for r in gold["CAREER_PREVIEW"]]
                      + [n for v in gold["SLOT_DATA"].values() for n, _ in v])
        view = analysis_view(results, who, h, positions, legacy["draft_career_grades"], names)
        path = ctx.site_root / PAGE
        if path.is_file():
            view = read_page(write_page(path.read_text(encoding="utf-8"), view))
        checks = compare_view(view, gold, ctx.golden["preach_manager_stats"], ctx.cfg, set(live_seasons(ctx.tables)),
                              ctx.golden["hit_rate_data"])
        return checks + self.info(ctx)

    def info(self, ctx) -> list[str]:
        path = ctx.site_root / PAGE
        if not path.is_file():
            return []
        text = path.read_text(encoding="utf-8")
        live = read_page(text)
        eng = analysis_view(*self._engine(ctx), self._names(ctx, text))
        lt, et = parse_tier_cards(live["tier_cards"]), parse_tier_cards(eng["tier_cards"])
        ou = [f"slot {i + 1} {a_:+.3f} -> {b:+.3f}" for i, (a_, b) in enumerate(zip(live["OVERPERFS"], eng["OVERPERFS"]))
              if abs(a_ - b) > 0.0005]
        return [f"INFO  draft-analysis, engine data vs the live page: tier hit rates "
                + ", ".join(f"{x['tier']} {x['rate']}% -> {y['rate']}%" for x, y in zip(lt, et))
                + f"; over/under changes for {len(ou)} slot(s)" + (f", e.g. {', '.join(ou[:3])}" if ou else "")
                + f"; steals ceiling {live['ABOVE_AVG_CEIL']} -> {eng['ABOVE_AVG_CEIL']}; position counts per round "
                "now cover every hit-rate season (the page counted 2020-2024)"]


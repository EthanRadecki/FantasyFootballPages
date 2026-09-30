"""Compare manager season stats with the legacy preach_manager_stats.csv.

Golden file:
    manager_seasons/preach_manager_stats.csv.gz   data/preach_manager_stats.csv,
                                                  maintained by hand (no script
                                                  wrote it); 2020-2025 plus a
                                                  2026 snapshot after week 2

Its formulas, recovered from the file itself: regular-season games only;
W% = W / GP; PF/G and PA/G per game; DIFF = (PF - PA) / regular-season
weeks played (a bye week included); ranks within the season over every
manager; Luck_Rating = PF/G rank - PA/G rank; Dominance_Score and
LR_zscore are PF/G and PA/G as z-scores within the season (sample standard
deviation); Placement, Playoffs, Champ_App,
Champ_W and Draft_Slot as ESPN records them; Conference is the league's
stable label for ESPN's division id (league.yaml league.conference_labels),
used for every season although ESPN's division names changed.

Legacy mode must reproduce it, with these patterns excused (never by name):
- hand-rounded values: 2021-2024 W%, PF/G, PA/G and DIFF were typed rounded
  (W% to 2 places, the rest to 1); excused when the engine value is within
  half of the file's last digit
- a hand-entered total that disagrees with the file's own source: a PA (and
  the PA/G and DIFF built from it) that does not match the sum of that
  manager's regular-season rows in matchup_data.csv, where the engine does
- z-scores computed from the file's own PF/G or PA/G column (so they carry
  the rounding and entry errors above): excused when the legacy formula on
  the file's column gives the file's z-score and the engine's is within 0.05
- ranks: a tie in the file's values (ties were ordered by row), or a rank
  that contradicts the file's own PF/G or PA/G column (hand-entered); the
  luck rating follows an excused rank
The 2026 rows are a snapshot after week 2: they are checked against the
engine run on those weeks only, record columns only (the file showed the
current standings as placement). Team names are display names edited by hand
and are not compared (editorial, phase 5).
"""

from __future__ import annotations

import pandas as pd

from engine.analytics import manager_seasons as ms_mod
from engine.config import conference_labels, excluded_games, excluded_manager_keys
from engine.legacy import Comparison, compare, name_to_key, resolve_names

RECORD_COLS = ["wins", "losses", "games", "points_for", "points_against", "win_pct", "pf_per_game",
               "pa_per_game", "point_diff_per_game", "pf_rank", "pa_rank", "luck_rating", "dominance", "pa_z"]
ESPN_COLS = ["final_rank", "made_playoffs", "champion_appearance", "champion", "draft_slot"]
LEGACY_NAMES = {"W": "wins", "L": "losses", "GP": "games", "PF": "points_for", "PA": "points_against",
                "W%": "win_pct", "PF/G": "pf_per_game", "PA/G": "pa_per_game", "DIFF": "point_diff_per_game",
                "PF/G_Rank_within_Year": "pf_rank", "PA/G_Rank_within_Year": "pa_rank",
                "Luck_Rating": "luck_rating", "Dominance_Score": "dominance", "LR_zscore": "pa_z",
                "Placement_within_Year": "final_rank", "Playoffs": "made_playoffs", "Champ_App": "champion_appearance",
                "Champ_W": "champion", "Draft_Slot": "draft_slot", "Conference": "conference"}
ROUNDED_COLS = ["win_pct", "pf_per_game", "pa_per_game", "point_diff_per_game"]
KEYS = ["season", "manager_key"]
Z_CLOSE = 0.05   # a z-score excused for its inputs must still be this close to the engine's


def legacy_frame(legacy: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    out = legacy.rename(columns=LEGACY_NAMES)
    out["season"] = legacy["Year"].astype(int)
    out["manager_key"] = resolve_names(legacy["Manager"], name_to_key(cfg))
    for c in ("made_playoffs", "champion_appearance", "champion"):
        out[c] = out[c].astype(int).astype(bool)
    return out


def _decimals(v: float) -> int:
    s = repr(float(v))
    return len(s.split(".")[1].rstrip("0")) if "." in s else 0


def _known_rounding(both: pd.DataFrame) -> list[pd.DataFrame]:
    reason = ("hand-rounded in the file (W% to 2 places, PF/G, PA/G, DIFF to 1); "
              "the engine value is within half its last digit")
    out = []
    for c in ROUNDED_COLS:
        leg, eng = both[f"{c}_l"], both[f"{c}_e"]
        d = leg.map(_decimals)
        ok = (d <= 2) & (eng.astype(float) - leg).abs().le(0.5 * 10.0 ** -d + 1e-9)
        out.append(both.loc[ok, KEYS].assign(column=c, reason=reason))
    return out


def source_totals(matchup_data: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """PF and PA summed from the legacy matchup_data.csv, regular season only."""
    md = matchup_data[matchup_data["Week"].str.startswith("Week")]
    out = pd.DataFrame({"season": md["Season_Year"].astype(int),
                        "manager_key": resolve_names(md["Team_Name"], name_to_key(cfg)),
                        "src_pa": md["Opponent_Score"].astype(float)})
    return out.groupby(KEYS)["src_pa"].sum().reset_index()


def _known_entry(both: pd.DataFrame, src: pd.DataFrame) -> list[pd.DataFrame]:
    reason = "hand-entered PA disagrees with the file's own source (matchup_data.csv); the engine matches the source"
    b = both.merge(src, on=KEYS, how="left")
    bad = (b["points_against_l"] - b["src_pa"]).abs().gt(0.005) & (b["points_against_e"] - b["src_pa"]).abs().le(0.005)
    rows = b.loc[bad, KEYS]
    return [rows.assign(column=c, reason=reason) for c in ("points_against", "pa_per_game", "point_diff_per_game")]


def _known_z(both: pd.DataFrame, leg: pd.DataFrame) -> list[pd.DataFrame]:
    out = []
    for z, src, label in (("dominance", "pf_per_game", "PF/G"), ("pa_z", "pa_per_game", "PA/G")):
        recomputed = leg.groupby("season")[src].transform(ms_mod.zscore)
        logic_ok = leg.loc[(recomputed - leg[z]).abs().lt(1e-6), KEYS]
        close = both.loc[(both[f"{z}_l"] - both[f"{z}_e"]).abs().lt(Z_CLOSE), KEYS]
        reason = f"z-score computed from the file's own {label} column; the legacy formula on it gives the file's value"
        out.append(close.merge(logic_ok, on=KEYS).assign(column=z, reason=reason))
    return out


def _known_ranks(both: pd.DataFrame, leg: pd.DataFrame) -> list[pd.DataFrame]:
    out, excused = [], []
    for rank, src, asc in (("pf_rank", "pf_per_game", False), ("pa_rank", "pa_per_game", True)):
        g = leg.groupby("season")[src]
        lo, hi = g.rank(ascending=asc, method="min"), g.rank(ascending=asc, method="max")
        tie = (lo < hi) & leg[rank].between(lo, hi)
        contra = ~leg[rank].between(lo, hi)
        for mask, reason in ((tie, "tied in the file's values (legacy ordered ties by row)"),
                             (contra, "hand-entered rank contradicts the file's own column")):
            rows = both[KEYS].merge(leg.loc[mask, KEYS], on=KEYS)
            out.append(rows.assign(column=rank, reason=reason))
            excused.append(rows)
    luck_ok = leg.loc[(leg["pf_rank"] - leg["pa_rank"]) == leg["luck_rating"], KEYS]
    rows = pd.concat(excused, ignore_index=True).drop_duplicates().merge(luck_ok, on=KEYS)
    out.append(rows.assign(column="luck_rating", reason="follows an excused rank (PF/G rank - PA/G rank)"))
    return out


def _known(exp: pd.DataFrame, act: pd.DataFrame, matchup_data: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    both = exp.merge(act, on=KEYS, suffixes=("_l", "_e"))
    parts = (_known_rounding(both) + _known_entry(both, source_totals(matchup_data, cfg))
             + _known_z(both, exp) + _known_ranks(both, exp))
    return pd.concat(parts, ignore_index=True)


def _snapshot_tables(tables: dict, season: int, weeks: int) -> dict:
    out = dict(tables)
    m = tables["matchups"]
    out["matchups"] = m[(m["season"] != season) | (m["week"] <= weeks)]
    return out


def check_finished(tables: dict, legacy: pd.DataFrame, matchup_data: pd.DataFrame, cfg: dict,
                   live: set[int]) -> Comparison:
    exp = legacy_frame(legacy, cfg)
    exp = exp[~exp["season"].isin(live)]
    act = ms_mod.manager_seasons(tables, excluded_manager_keys(cfg), legacy_mode=True,
                                 conference_labels=conference_labels(cfg))
    act = act[act["season"].isin(set(exp["season"]))]
    values = RECORD_COLS + ESPN_COLS + ["conference"]
    return compare("season stats (finished seasons) vs preach_manager_stats.csv", exp, act, keys=KEYS,
                   values=values, tolerance=1e-6, known=_known(exp, act, matchup_data, cfg))


def check_live(tables: dict, legacy: pd.DataFrame, matchup_data: pd.DataFrame, cfg: dict,
               live: set[int]) -> list[Comparison]:
    out = []
    exp_all = legacy_frame(legacy, cfg)
    for season in sorted(live & set(exp_all["season"])):
        exp = exp_all[exp_all["season"] == season]
        weeks = int(exp["games"].max())
        act = ms_mod.manager_seasons(_snapshot_tables(tables, season, weeks), excluded_manager_keys(cfg),
                                     legacy_mode=True, conference_labels=conference_labels(cfg))
        act = act[act["season"] == season]
        out.append(compare(f"season stats ({season} after week {weeks}) vs preach_manager_stats.csv", exp, act,
                           keys=KEYS, values=RECORD_COLS + ["draft_slot"], tolerance=1e-6,
                           known=_known(exp, act, matchup_data, cfg)))
    return out


def _effect(leg: pd.DataFrame, eng: pd.DataFrame, names: dict) -> list[str]:
    b = leg.merge(eng[~eng["hidden"]], on=KEYS, suffixes=("_l", "_e"))
    out = []
    for c, fmt in (("point_diff_per_game", "{:+.1f}"), ("pf_per_game", "{:.1f}"), ("pa_per_game", "{:.1f}"), ("dominance", "{:+.2f}"),
                   ("pf_rank", "{}"), ("pa_rank", "{}"), ("luck_rating", "{:+}")):
        d = b[(b[f"{c}_l"].astype(float) - b[f"{c}_e"].astype(float)).abs() > 1e-9]
        if len(d):
            ex = ", ".join(f"{r.season} {names.get(r.manager_key, r.manager_key)} "
                           f"{fmt.format(getattr(r, c + '_l'))} -> {fmt.format(getattr(r, c + '_e'))}"
                           for r in d.head(4).itertuples())
            out.append(f"{c}: {len(d)} row(s), e.g. {ex}")
    return out or ["no effect on current data"]


def engine_changes(tables: dict, cfg: dict) -> list[str]:
    names = {m["id"]: m["name"] for m in cfg.get("managers") or []}
    ex, ppg = excluded_manager_keys(cfg), excluded_games(cfg, "ppg")
    leg = ms_mod.manager_seasons(tables, ex, ppg, legacy_mode=True,
                                 conference_labels=conference_labels(cfg))
    lines = []
    for fix, text in ms_mod.ENGINE_CHANGES.items():
        eng = ms_mod.manager_seasons(tables, ex, ppg, fixes={fix})
        lines.append(f"INFO  engine fix [{fix}] {text}")
        lines += [f"INFO      {e}" for e in _effect(leg, eng, names)]
    return lines


def verify_manager_seasons(tables: dict, golden: dict, cfg: dict) -> tuple[list[Comparison], list[str]]:
    legacy, md = golden["preach_manager_stats"], golden["matchup_data"]
    live = ms_mod.live_seasons(tables)
    checks = [check_finished(tables, legacy, md, cfg, live), *check_live(tables, legacy, md, cfg, live)]
    exp = legacy_frame(legacy, cfg)
    act = ms_mod.manager_seasons(tables, excluded_manager_keys(cfg), legacy_mode=True,
                                 conference_labels=conference_labels(cfg))
    names = exp.merge(act[KEYS + ["team_name"]], on=KEYS, suffixes=("_l", "_e"))
    edited = int((names["Team"].str.split().str.join(" ") != names["team_name"]).sum())
    info = [f"INFO  seasons {exp['season'].min()}-{exp['season'].max()}; legacy mode",
            f"INFO  team names: {edited} of {len(names)} were edited by hand in the file (not compared; "
            "display names are editorial, phase 5)"]
    if act["division_name"].isna().all():
        info.append("INFO  ESPN division names not in the canonical tables yet (run `engine normalize`)")
    else:
        by = act.dropna(subset=["division_id"]).groupby(["season", "division_id"])
        names = by.agg(name=("division_name", "first"), conf=("conference", "first")).reset_index()
        info.append("INFO  ESPN division names by season (conference): " + "; ".join(
            f"{y} " + ", ".join(f"{r.name} ({r.conf})" for r in g.itertuples()) for y, g in names.groupby("season")))
    return checks, info + engine_changes(tables, cfg)

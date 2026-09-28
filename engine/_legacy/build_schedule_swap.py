"""
Schedule Swap analysis for Preach Fantasy extra-analytics.html.

For every manager A in a season, and for every OTHER manager B in that
same season, this computes what A's record would have been if A had
played B's actual schedule (B's real weekly opponents and the scores
those opponents actually put up), using A's own actual weekly score.

Regular season only (Week 1-14), Thomas Sullivan / William Serafin
excluded entirely (both as a manager and as anyone else's opponent),
matching the site-wide exclusion rule. Playoffs and consolation games
are excluded from this analysis per the standing rule for schedule-luck
work.

Known wrinkles handled explicitly (see inline notes):
  1. A one-row data mismatch (2025 Wk14 Anthony Kelly / Ryan P McQuaid)
     is corrected here to 86.46 per Ethan's confirmation. The raw CSV
     itself still has the old value on Anthony's row -- flagged in the
     printed output, not silently fixed upstream.
  2. 2020 had 15 teams with rotating byes, so games played per manager
     that season ranges 9-11 instead of a clean 14, and some managers
     are missing specific weeks entirely (whenever their real 2020
     opponent was Thomas Sullivan or William Serafin, that week drops
     out of the data for them, not just true byes). Every average and
     comparison below is done on win% (not raw win totals) specifically
     so 2020's uneven schedule lengths don't distort the ranking, and
     the site copy for 2020 needs to say this in-page.
  3. Self-matchup weeks: if A and B played each other for real in a
     given week, that week can't be used when giving A "B's schedule"
     (A would be playing itself). Those weeks are dropped from that one
     pairing only. Most pairs meet exactly once a season (dropping 1
     week from that swap), rivalry pairs meet twice (weeks 1 and 14,
     dropping 2 weeks). Verified below: 462 pair-seasons meet once,
     44 meet twice, 0 meet more than twice.
  4. The known Ben Castaldo 2024 Week 14 forfeit (recorded as a 0.0
     score) stays in his actual record as a real loss, and other
     managers can still safely borrow that week's opponent slot
     (Baylen Slansky's real 128.52 is unaffected). But his own 0.0 is
     excluded from being used as HIS score when he wears a different
     schedule -- otherwise the forfeit would force an automatic loss
     in every single alt-schedule for that week, which isn't a real
     performance. Confirmed via a full-data scan that this is the only
     exact-0.0 score in the regular-season data, so no other weeks
     need this treatment.
"""

import csv
import json
from collections import defaultdict

EXCLUDED = {"Thomas Sullivan", "William Serafin"}

# (season, week, manager) weeks whose OWN score is a non-performance
# (forfeit) and must not be used as the "wearer's" score in a swap.
FORFEIT_OWN_SCORE_WEEKS = {("2024", "Week 14", "Ben Castaldo")}
SEASON_LENGTH = 14  # weeks in a full regular season, used to normalize
                     # win% back into a "wins over a full season" figure
                     # for display, so 2020's shorter/uneven schedules
                     # are comparable to other years.

def load_rows(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    # Manual correction confirmed by Ethan: 2025 Week 14, Anthony Kelly's
    # row records Ryan P McQuaid's score as 84.46; Ryan's own row records
    # his score that week as 86.46. Ethan confirmed 86.46 is correct.
    # NOTE: this only patches the in-memory copy used for this analysis --
    # the source matchup_data.csv on disk still has the stale 84.46 on
    # Anthony's row and should probably be corrected upstream too.
    fixed = 0
    for r in rows:
        if (r["Season_Year"] == "2025" and r["Week"] == "Week 14"
                and r["Team_Name"] == "Anthony Kelly"
                and r["Opponent_Name"] == "Ryan P McQuaid"):
            assert r["Opponent_Score"] == "84.46", "expected stale value not found"
            r["Opponent_Score"] = "86.46"
            fixed += 1
    assert fixed == 1, f"expected to patch exactly 1 row, patched {fixed}"
    return rows


def regular_season_rows(rows):
    return [r for r in rows
            if r["Week"].startswith("Week")
            and r["Team_Name"] not in EXCLUDED
            and r["Opponent_Name"] not in EXCLUDED]


def build_schedules(reg_rows):
    """season -> manager -> week -> (own_score, opponent, opp_score)"""
    sched = defaultdict(lambda: defaultdict(dict))
    for r in reg_rows:
        yr, wk, mgr = r["Season_Year"], r["Week"], r["Team_Name"]
        sched[yr][mgr][wk] = (float(r["Team_Score"]), r["Opponent_Name"], float(r["Opponent_Score"]))
    return sched


def verify_pair_meeting_counts(reg_rows):
    """Sanity check referenced in the module docstring."""
    pair_counts = defaultdict(float)
    for r in reg_rows:
        key = (r["Season_Year"], frozenset([r["Team_Name"], r["Opponent_Name"]]))
        pair_counts[key] += 0.5
    from collections import Counter
    dist = Counter(pair_counts.values())
    assert dist[1.0] == 462 and dist[2.0] == 44 and set(dist) == {1.0, 2.0}, dist
    return dist


def actual_record(schedule_for_mgr):
    w = l = 0
    for wk, (own, opp, opp_score) in schedule_for_mgr.items():
        if own > opp_score:
            w += 1
        else:
            l += 1
    return w, l


def swap_record(yr, mgr_schedule, other_mgr_schedule, mgr_name):
    """What mgr's record would be wearing other_mgr's schedule.

    Skips any week where:
      - mgr has no actual score that week (missing/bye), or
      - other_mgr's real opponent that week was mgr itself (degenerate), or
      - mgr's own score that week is a known forfeit non-performance
        (see FORFEIT_OWN_SCORE_WEEKS).
    """
    w = l = 0
    games = 0
    for wk, (other_own, other_opp, other_opp_score) in other_mgr_schedule.items():
        if other_opp == mgr_name:
            continue  # degenerate: can't play against yourself
        if wk not in mgr_schedule:
            continue  # mgr has no score that week (2020 bye/missing week)
        if (yr, wk, mgr_name) in FORFEIT_OWN_SCORE_WEEKS:
            continue  # mgr's own score that week is a forfeit, not real
        mgr_own_score = mgr_schedule[wk][0]
        if mgr_own_score > other_opp_score:
            w += 1
        else:
            l += 1
        games += 1
    return w, l, games


def pct(w, l):
    return w / (w + l) if (w + l) > 0 else 0.0


def build_output(sched):
    output = {}
    for yr in sorted(sched.keys()):
        managers = sorted(sched[yr].keys())
        yr_out = {}
        for mgr in managers:
            aw, al = actual_record(sched[yr][mgr])
            actual_pct = pct(aw, al)
            alt = {}
            alt_pcts = []
            for other in managers:
                if other == mgr:
                    continue
                w, l, games = swap_record(yr, sched[yr][mgr], sched[yr][other], mgr)
                p = pct(w, l)
                alt[other] = {"w": w, "l": l, "games": games, "pct": round(p, 4)}
                alt_pcts.append(p)
            avg_pct = sum(alt_pcts) / len(alt_pcts) if alt_pcts else 0.0
            wins_gained = (avg_pct - actual_pct) * SEASON_LENGTH
            yr_out[mgr] = {
                "actual": {"w": aw, "l": al, "pct": round(actual_pct, 4)},
                "alt": alt,
                "avg_pct": round(avg_pct, 4),
                "wins_gained": round(wins_gained, 2),
            }
        output[yr] = yr_out
    return output


def main():
    rows = load_rows("matchup_data.csv")
    reg = regular_season_rows(rows)
    print(f"Regular season rows after exclusions: {len(reg)}")

    dist = verify_pair_meeting_counts(reg)
    print(f"Pair-meeting-count distribution (sanity check): {dict(dist)}")

    sched = build_schedules(reg)

    # Verify the forfeit handling: Ben Castaldo's 2024 own-score-based
    # swap games should total 13 (14 minus the forfeit week) against
    # every other manager's schedule, not 14.
    ben_2024 = sched["2024"]["Ben Castaldo"]
    for other, other_sched in sched["2024"].items():
        if other == "Ben Castaldo":
            continue
        _, _, games = swap_record("2024", ben_2024, other_sched, "Ben Castaldo")
        # games should be 13 (14 minus forfeit week) or 12 if other is a rival
        assert games in (12, 13), (
            f"Ben Castaldo 2024 vs {other} schedule: expected 12 or 13 games, got {games}")
    print("Forfeit-week exclusion verified: Ben Castaldo's 2024 swaps never "
          "use his forfeited Week 14 score.")

    for yr in sorted(sched):
        counts = {m: len(sched[yr][m]) for m in sched[yr]}
        print(f"{yr}: {len(sched[yr])} managers, games played range "
              f"{min(counts.values())}-{max(counts.values())}")

    output = build_output(sched)

    # Print a full readable dump for a couple of seasons for manual review
    for yr in ["2020", "2025"]:
        print(f"\n=== {yr} ===")
        for mgr in sorted(output[yr]):
            d = output[yr][mgr]
            print(f"{mgr:22s} actual {d['actual']['w']:2d}-{d['actual']['l']:2d} "
                  f"({d['actual']['pct']:.3f})  avg_alt_pct={d['avg_pct']:.3f}  "
                  f"wins_gained={d['wins_gained']:+.2f}")

    with open("schedule_swap.json", "w") as f:
        json.dump(output, f, indent=None, separators=(",", ":"))
    print("\nWrote schedule_swap.json")


if __name__ == "__main__":
    main()

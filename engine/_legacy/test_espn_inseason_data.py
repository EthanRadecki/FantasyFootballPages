import json as _json; _AUTH = {k.lower(): v for k, v in _json.load(open("espn_auth.json")).items()}  # credentials stay out of code
"""
=============================================================================
Preach Fantasy — In-Season Data Diagnostic
Tests two things we don't have yet: weekly lineups and transaction history.
Run this FIRST, on one season, before we build the full pipeline.
Paste the printed output back so we can see what ESPN actually gives us.
=============================================================================
"""

from espn_api.football import League
import json

LEAGUE_ID = 9954376
ESPN_S2   = _AUTH["espn_s2"]
SWID      = _AUTH["swid"]

# ── Start with the most recent complete season. If this works cleanly,
#    we'll walk backward to 2020 and see where (if anywhere) it degrades.
TEST_SEASON = 2025

print(f"Loading {TEST_SEASON} season...")
league = League(league_id=LEAGUE_ID, year=TEST_SEASON, espn_s2=ESPN_S2, swid=SWID)
print(f"Loaded. {len(league.teams)} teams found.\n")

# =============================================================================
# TEST 1: Weekly lineups (starter vs. bench)
# =============================================================================
print("=" * 70)
print("TEST 1: WEEKLY LINEUPS")
print("=" * 70)

TEST_WEEK = 1
try:
    box_scores = league.box_scores(TEST_WEEK)
    print(f"box_scores(week={TEST_WEEK}) returned {len(box_scores)} matchups\n")

    if box_scores:
        bs = box_scores[0]
        print(f"Sample matchup: {bs.home_team.team_name} vs {bs.away_team.team_name}")
        print(f"\nHome lineup (first 5 players):")
        for p in bs.home_lineup[:5]:
            print(f"  {p.name:25s} slot={p.slot_position:6s} points={p.points}")
        print(f"\nTotal home_lineup size: {len(bs.home_lineup)}")
        print(f"Unique slot_position values seen: {set(p.slot_position for p in bs.home_lineup)}")
except Exception as e:
    print(f"box_scores FAILED: {e}")

# =============================================================================
# TEST 2: Transaction history (trades, waivers, drops)
# =============================================================================
print("\n" + "=" * 70)
print("TEST 2: TRANSACTION HISTORY")
print("=" * 70)

try:
    # Pull as many as the API will give us in one call
    activity = league.recent_activity(size=500)
    print(f"recent_activity(size=500) returned {len(activity)} entries\n")

    if activity:
        # Show date range covered — tells us if we're getting the whole season
        dates = [a.date for a in activity]
        print(f"Earliest activity timestamp: {min(dates)}")
        print(f"Latest activity timestamp:   {max(dates)}")

        # Show a few raw entries so we can see the actual shape
        print(f"\nFirst 5 raw activity entries:")
        for a in activity[:5]:
            print(f"  date={a.date}")
            for action in a.actions:
                team, act_type, player, bid = action
                print(f"    team={team.team_name!r} action={act_type!r} player={player} bid={bid}")

        # Tally action types so we know what we're working with
        action_types = {}
        for a in activity:
            for action in a.actions:
                act_type = action[1]
                action_types[act_type] = action_types.get(act_type, 0) + 1
        print(f"\nAction type counts:")
        for t, c in action_types.items():
            print(f"  {t}: {c}")
except Exception as e:
    print(f"recent_activity FAILED: {e}")

print("\n" + "=" * 70)
print("Done. Paste this whole output back so we can plan the real pipeline.")
print("=" * 70)

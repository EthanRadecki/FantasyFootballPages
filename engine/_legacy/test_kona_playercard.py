import json as _json; _AUTH = {k.lower(): v for k, v in _json.load(open("espn_auth.json")).items()}  # credentials stay out of code
"""
=============================================================================
Preach Fantasy — kona_playercard Transaction Diagnostic
recent_activity() is broken (confirmed known espn_api library issue).
This tests the workaround: querying a handful of players directly via the
raw kona_playercard view, which includes transaction history per player.

This is diagnostic only — it just prints the raw shape of the data back
so we can see what's actually in there before writing a real parser.
=============================================================================
"""

import requests
import json

LEAGUE_ID = 9954376
ESPN_S2   = _AUTH["espn_s2"]
SWID      = _AUTH["swid"]

TEST_SEASON = 2025

# Pull a handful of real player IDs from your existing season stats file
# so we're testing with players who actually have transaction history.
import pandas as pd
season_df = pd.read_csv("espn_player_stats_season.csv")
test_ids = season_df[season_df["season"] == TEST_SEASON]["player_id"].head(15).tolist()
print(f"Testing with {len(test_ids)} player IDs from {TEST_SEASON}: {test_ids}\n")

url = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{TEST_SEASON}/segments/0/leagues/{LEAGUE_ID}"

filters = {
    "players": {
        "filterIds": {"value": test_ids},
        "limit": len(test_ids),
        "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "STANDARD"}
    }
}
headers = {"x-fantasy-filter": json.dumps(filters)}
params = {"view": "kona_playercard"}
cookies = {"espn_s2": ESPN_S2, "swid": SWID}

print(f"Requesting: {url}")
resp = requests.get(url, headers=headers, params=params, cookies=cookies)
print(f"Status code: {resp.status_code}\n")

if resp.status_code != 200:
    print("Request failed. Response text:")
    print(resp.text[:2000])
else:
    data = resp.json()
    players = data.get("players", [])
    print(f"Got {len(players)} player entries back\n")

    if players:
        # Print the full structure of the first player so we can see the shape
        first = players[0]
        print("Top-level keys on first player entry:")
        print(list(first.keys()))

        p = first.get("player", {})
        print(f"\nPlayer name: {p.get('fullName')}")

        # The transactions field lives at the TOP level of each player entry,
        # as a sibling to 'player' — not nested inside it.
        txns = first.get("transactions")
        print(f"\n--- 'transactions' field (top-level) ---")
        print(json.dumps(txns, indent=2)[:4000] if txns is not None else "None / not present for this player")

        # Also check 'status' in case acquisition info lives there instead
        status = first.get("status")
        print(f"\n--- 'status' field (top-level) ---")
        print(json.dumps(status, indent=2)[:2000] if status is not None else "None / not present")

        # Loop all 15 test players and show which ones actually have transaction data,
        # since Ja'Marr Chase (a heavily-owned, likely never-dropped player) may not
        # be the best example.
        print(f"\n\n--- Scanning all {len(players)} test players for non-empty transactions ---")
        for entry in players:
            t = entry.get("transactions")
            name = entry.get("player", {}).get("fullName", "?")
            if t:
                print(f"\n{name}: transactions = {json.dumps(t)[:1500]}")
            else:
                print(f"{name}: no transactions field / empty")

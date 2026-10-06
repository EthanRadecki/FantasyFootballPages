"""Player headshots (PR A8c, decision 7.5): ESPN images by player id, legacy keys by spelling."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd

from engine.providers.espn import headshot_url
from engine.publish.pages import headshots as hs

GOLDEN = Path(__file__).parent / "golden"


def test_espn_urls():
    assert headshot_url(3126486, "WR") == "https://a.espncdn.com/i/headshots/nfl/players/full/3126486.png"
    assert headshot_url(-16002, "D/ST", "BUF") == "https://a.espncdn.com/i/teamlogos/nfl/500/buf.png"
    assert headshot_url(-16002, "D/ST") is None


def test_name_matching_ignores_case_accents_punctuation_and_suffixes():
    assert hs.norm("Audric Estimé") == hs.norm("audric estime")
    assert hs.norm("Travis Etienne Jr.") == hs.norm("Travis Etienne") == "travisetienne"
    assert hs.norm("A.J. Brown") == hs.norm("AJ Brown")


def _tables():
    stats = pd.DataFrame({"season": [2024, 2026, 2026, 2026], "player_id": [7, 7, 8, -16002],
                          "player_name": ["Travis Etienne", "Travis Etienne Jr.", "Malcolm Perry", "Bills D/ST"],
                          "position": ["RB", "RB", "WR", "D/ST"], "pro_team_id": [30, 30, 15, 2]})
    teams = pd.DataFrame({"season": 2026, "pro_team_id": [2, 15, 30], "abbrev": ["BUF", "MIA", "JAX"],
                          "bye_week": [7, 6, 8]})
    return {"player_stats": stats, "pro_teams": teams}


def test_legacy_view_keys_every_spelling_and_leaves_out_dst():
    t = _tables()
    index = hs.player_index(t)
    urls = hs.image_urls({"league": {"provider": "espn"}}, t, index)
    assert urls[-16002].endswith("/buf.png") and urls[7].endswith("/7.png")
    view, unmatched = hs.legacy_view(index, urls, ["Travis Etienne|RB", "Malcolm Perry|RB", "Nobody|QB"],
                                     hs.name_rows(t))
    assert view == {"Malcolm Perry|RB": urls[8], "Malcolm Perry|WR": urls[8], "Travis Etienne Jr.|RB": urls[7],
                    "Travis Etienne|RB": urls[7]}
    assert unmatched == ["Nobody|QB"]
    assert hs.image_urls({"league": {"provider": "sleeper"}}, t, index) == {}


def test_published_file_is_the_golden():
    with gzip.open(GOLDEN / "headshots" / "player_headshots.json.gz", "rt", encoding="utf-8") as f:
        gold = json.load(f)
    assert len(gold) == 1319 and all("|" in k for k in gold)

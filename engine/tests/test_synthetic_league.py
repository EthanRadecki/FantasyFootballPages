"""The synthetic league (F1): the whole engine on a league that is not Preach.

The league (engine/testing/synthetic.py) changes size mid-history, turns divisions
on and off, never starts a D/ST, drops its kicker, adds a superflex, plays two- and
three-round playoffs, and has a live season. These tests run normalize, analyze and
build on it in-process (tables kept in memory) and check that every page model is
produced, valid, and adapted to the league. CI also runs the same steps through the
command line (.github/workflows/validate.yml, job synthetic-league).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from engine.testing import synthetic

ROOT = Path(__file__).resolve().parents[2]
YAML = ROOT / "leagues" / "synthetic" / "league.yaml"


def _digest(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*.json")):
        h.update(p.relative_to(folder).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def test_committed_config_matches_the_generator():
    assert YAML.read_text(encoding="utf-8") == synthetic.league_yaml()


def test_generator_is_deterministic(tmp_path):
    a = synthetic.write_league(tmp_path / "a")
    b = synthetic.write_league(tmp_path / "b")
    assert _digest(a) == _digest(b)


_BUILT: dict = {}


def built():
    """normalize, analyze and build --verify on the synthetic league, once per test run (tables kept in
    memory, so no Parquet engine is needed); returns (dist, canonical tables, analysis tables, rc)."""
    if _BUILT:
        return _BUILT["v"]
    import tempfile

    import engine.store as store
    from engine import cli

    mem: dict = {}
    saved = store.write_tables, store.read_tables, Path.exists
    real_exists = Path.exists
    store.write_tables = lambda t, d: mem.__setitem__(str(d), {k: v.copy() for k, v in t.items()})
    store.read_tables = lambda d: {k: v.copy() for k, v in mem.get(str(d), {}).items()}
    Path.exists = lambda self: str(self) in mem or real_exists(self)
    try:
        tmp = Path(tempfile.mkdtemp(prefix="synthetic-"))
        cache, out = tmp / "cache", tmp / "dist"
        synthetic.write_league(cache)
        assert cli.main(["normalize", str(YAML), "--cache", str(cache)]) == 0
        assert cli.main(["analyze", str(YAML), "--cache", str(cache)]) == 0
        rc = cli.main(["build", str(YAML), "--cache", str(cache), "--out", str(out), "--verify"])
    finally:
        store.write_tables, store.read_tables, Path.exists = saved
    canon = next(v for k, v in mem.items() if "canonical" in k)
    ana = next(v for k, v in mem.items() if "analysis" in k)
    _BUILT["v"] = (out, canon, ana, rc)
    return _BUILT["v"]


def _model(dist: Path, rel: str) -> dict:
    return json.loads((dist / "data" / "v1" / rel).read_text(encoding="utf-8"))


def test_the_engine_runs_end_to_end():
    dist, canon, ana, rc = built()
    assert rc == 0                                         # every page model matches its schema
    # the league as generated
    assert dict(zip(canon["seasons"]["season"], canon["seasons"]["team_count"])) == {2021: 10, 2022: 10,
                                                                                     2023: 12, 2024: 12}
    assert "D/ST" not in set(canon["lineups"]["position"])
    assert len(canon["pro_games"]) and len(canon["projections"])
    # only page models (no legacy site for this league), and only the pages the league has
    files = {p.relative_to(dist).as_posix() for p in dist.rglob("*") if p.is_file()}
    assert all(f.startswith("data/v1/") or f in ("config.json", "build-manifest.json") for f in files)
    pages = {p["id"] for p in json.loads((dist / "config.json").read_text())["pages"]}
    assert "dst-impact" not in pages            # never starts a D/ST
    assert "weekly-rankings" not in pages       # no editorial rankings
    assert {"home", "managers", "champions", "matchups", "extra-analytics", "position-impact",
            "draft-fingerprints", "trade-value", "waiver-value", "lineup-efficiency", "schedule-release"} <= pages


def test_page_models_adapt_to_the_league():
    dist, canon, ana, rc = built()
    hidden = synthetic.manager_key(9)
    managers = {p.stem for p in (dist / "data" / "v1" / "managers").glob("*.json")}
    assert len(managers) == 12 and hidden not in managers           # the excluded manager is hidden
    assert _model(dist, "position-impact.json")["positions"] == ["QB", "RB", "WR", "TE", "K"]
    ex = _model(dist, "extra-analytics.json")
    assert ex["conference"]["summary"] == [] and ex["conference"]["rivalries"]   # no conferences configured
    assert len(ex["gauntlet"]["champions"]) == 3                    # two- and three-game title runs
    assert len(_model(dist, "champions.json")["seasons"]) == 3
    assert len(_model(dist, "draft-fingerprints.json")["archetypes"]) == 4
    assert len(ana["draft_archetype_matches"]) == 12 * 3            # every live draft, three comparisons
    odds = _model(dist, "playoff-odds.json")
    assert {s["season"] for s in odds["seasons"]} == {2021, 2022, 2023, 2024}

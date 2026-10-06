"""Publish skeleton: writer, JSON diff, config.json, and the dist/ build."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine.config import excluded_manager_keys, load_config, validate_config
from engine.publish import config_json
from engine.publish.build import BuildContext, Output, run_build, verify_build
from engine.publish.diff import compare_json
from engine.publish.site import pages_for, site_files
from engine.publish.writer import build_info, clean, dump, rnd, with_meta

ROOT = Path(__file__).resolve().parents[2]
PREACH = ROOT / "leagues" / "preach" / "league.yaml"
BUILD = {"id": "test-build", "generated_at": "2026-09-30T00:00:00Z"}


# ---------------------------------------------------------------- writer

def test_clean_makes_values_json_safe():
    raw = {1: np.int64(3), "f": np.float64(1.5), "nan": float("nan"), "inf": np.inf, "na": pd.NA,
           "b": np.bool_(True), "t": (1, 2), "arr": np.array([1.0, np.nan])}
    out = clean(raw)
    assert out == {"1": 3, "f": 1.5, "nan": None, "inf": None, "na": None, "b": True, "t": [1, 2],
                   "arr": [1.0, None]}
    assert isinstance(out["1"], int) and isinstance(out["b"], bool)
    json.loads(dump(raw))


def test_rnd_and_meta():
    assert rnd(1.23456, 2) == 1.23 and rnd(float("nan"), 2) is None and rnd(None, 1) is None
    doc = with_meta("config", 1, BUILD, {"a": 1})
    assert list(doc) == ["meta", "a"]
    assert doc["meta"] == {"schema": "config", "schema_version": 1, "build_id": "test-build",
                           "generated_at": "2026-09-30T00:00:00Z"}
    with pytest.raises(ValueError, match="reserved"):
        with_meta("config", 1, BUILD, {"meta": 1})


def test_build_info_id_given_and_generated():
    assert build_info("abc")["id"] == "abc"
    info = build_info()
    assert info["id"][:8].isdigit() and info["generated_at"].endswith("Z")


# ---------------------------------------------------------------- diff

def test_compare_json_sections_known_and_tolerance():
    legacy = {"a": {"x": 1.0, "y": [1, 2]}, "b": [{"k": "v"}]}
    engine = {"a": {"x": 1.0 + 1e-12, "y": [1, 3]}, "b": [{"k": "v"}]}
    a, b = compare_json("page", engine, legacy)
    assert a.name == "page a vs published" and not a.ok and a.mismatched["values"] == 1
    assert "/a/y[1]" in a.examples[0] and b.ok
    known = compare_json("page", engine, legacy, known=lambda p, e, l: "legacy typo" if p == "/a/y[1]" else None)
    assert all(c.ok for c in known) and known[0].known == {"legacy typo": 1}
    whole, = compare_json("file", [1, 2], [1, 2, 3])
    assert whole.name == "file vs published" and not whole.ok


def test_compare_json_missing_keys_both_ways():
    c, = compare_json("p", {"s": {"a": 1, "extra": 2}}, {"s": {"a": 1, "gone": 3}})
    assert c.mismatched["values"] == 2


# ---------------------------------------------------------------- config.json pieces

def test_short_name_and_fallback_color():
    assert config_json.short_name("Carmine Pittelli Jr.") == "Pittelli"
    assert config_json.short_name("Ryan P McQuaid") == "McQuaid"
    assert config_json.fallback_color("m_000000000001") == config_json.fallback_color("m_000000000001")
    assert config_json.fallback_color("m_000000000001") in config_json.FALLBACK_COLORS


def test_round_names_week_map_default_list_and_generic():
    cfg = {"rules": {"playoff_rounds": {2020: {14: "The Round of 15", 15: "Quarterfinals"},
                                        "default": ["Quarterfinals", "Semifinals", "Championship"]}}}
    assert config_json.round_names(cfg, 2020, 13, 17) == {"14": "The Round of 15", "15": "Quarterfinals"}
    assert config_json.round_names(cfg, 2023, 14, 17) == {"15": "Quarterfinals", "16": "Semifinals",
                                                          "17": "Championship"}
    # an imported league with no round names and a five-week bracket
    assert config_json.round_names({}, 2019, 12, 17) == {
        "13": "Round 1", "14": "Round 2", "15": "Quarterfinals", "16": "Semifinals", "17": "Championship"}
    # a default list too short for the season falls back to generic names
    assert config_json.round_names(cfg, 2019, 13, 17)["14"] == "Round 1"


def test_pages_for_drops_switched_off_features():
    ids = [p["id"] for p in pages_for({"weekly_rankings": False})]
    assert "weekly-rankings" not in ids and "champions" in ids and "managers" in ids
    assert len(pages_for(None)) == len(pages_for({}))


def test_config_validation_short_and_features():
    cfg = load_config(PREACH)
    cfg["managers"][0]["short"] = " "
    cfg["features"] = {"weekly_rankings": "yes"}
    errors = validate_config(cfg).errors
    assert any("short must be" in e for e in errors) and any("features must map" in e for e in errors)


# ---------------------------------------------------------------- synthetic league

def _tables(cfg: dict) -> dict:
    """Two seasons (one finished, one live after week 2), four configured
    managers, one hidden, plus one manager league.yaml does not list."""
    keys = [m["id"] for m in cfg["managers"][:3]] + [sorted(excluded_manager_keys(cfg))[0], "m_0000000000ff"]
    seasons = pd.DataFrame({"season": [2025, 2026], "team_count": [4, 4], "regular_season_periods": [3, 3],
                            "playoff_team_count": [2, 2], "final_scoring_period": [4, 4]})
    rows = []
    for season, last in ((2025, 4), (2026, 3)):
        for week in range(1, 5):
            po = week > 3
            for i, key in enumerate(keys[:4] if season == 2025 else keys[1:]):
                decided = week <= 2 or season == 2025
                tier = ("WINNERS_BRACKET" if i < 2 else "LOSERS_CONSOLATION_LADDER") if po else "NONE"
                rows.append({"season": season, "week": week, "team_id": i + 1, "manager_key": key, "is_bye": False,
                             "is_playoff_week": po, "tier": tier, "points": 100.0,
                             "result": ("W" if i % 2 else "L") if decided else None})
    teams = pd.DataFrame([{"season": s, "team_id": i + 1, "manager_key": k, "logo_url": f"https://logo/{k}.png"}
                          for s, ks in ((2025, keys[:4]), (2026, keys[1:])) for i, k in enumerate(ks)])
    managers = pd.DataFrame({"manager_key": keys, "espn_name": ["A", "B", "C", "D", "Newcomer Person"]})
    return {"seasons": seasons, "matchups": pd.DataFrame(rows), "teams": teams, "managers": managers}


def test_build_config_from_data():
    cfg = load_config(PREACH)
    conf = config_json.build_config(cfg, _tables(cfg), BUILD)
    assert conf["finished_seasons"] == [2025] and conf["live_season"] == 2026
    assert conf["current"] == {"season": 2026, "last_completed_week": 2}
    assert [s["team_count"] for s in conf["seasons"]] == [4, 4]
    assert conf["seasons"][0]["last_completed_week"] == 4 and conf["seasons"][0]["live"] is False
    by_key = {m["key"]: m for m in conf["managers"]}
    new = by_key["m_0000000000ff"]
    assert new["name"] == "Newcomer Person" and new["short"] == "Person" and new["hidden"] is False
    assert new["logo"] == "https://logo/m_0000000000ff.png" and new["colors"]["dark"] in config_json.FALLBACK_COLORS
    assert sum(m["hidden"] for m in conf["managers"]) == 2        # both excluded managers, from league.yaml
    assert by_key[cfg["managers"][0]["id"]]["seasons"] == [2025]
    assert conf["league"]["logo"].endswith("preach_logo_2026.png")
    assert conf["exclude_games"][0]["season"] == 2024
    assert "images/logos/Radecki.png" in config_json.asset_paths(conf)
    assert not any(p.startswith("https://") for p in config_json.asset_paths(conf))


# ---------------------------------------------------------------- build

class _FakePublisher:
    """A legacy view that overwrites a site data file, and one Stage A check."""
    name = "fake"

    def outputs(self, ctx):
        return [Output("data/rankings/manifest.json", [{"season": 2026, "weeks": [1]}])]

    def verify(self, ctx):
        return compare_json("fake manifest", [{"season": 2026, "weeks": [1]}], [{"season": 2026, "weeks": [1]}])


def test_build_and_verify_real_site(tmp_path):
    cfg = load_config(PREACH)
    ctx = BuildContext(cfg=cfg, tables=_tables(cfg), analysis={}, build=BUILD, site_root=ROOT)
    out = tmp_path / "dist"
    res = run_build(ctx, out, publishers=[_FakePublisher()])
    assert (out / "index.html").read_bytes() == (ROOT / "index.html").read_bytes()
    assert len(res.copied) == len(site_files(ROOT)) > 100
    conf = json.loads((out / "config.json").read_text())
    assert conf["meta"]["schema"] == "config" and conf["build"]["id"] == "test-build"
    assert json.loads((out / "data/rankings/manifest.json").read_text()) == [{"season": 2026, "weeks": [1]}]
    manifest = json.loads((out / "build-manifest.json").read_text())
    sources = {f["path"]: f["source"] for f in manifest["files"]}
    assert sources["config.json"] == "generated" and sources["data/rankings/manifest.json"] == "generated"
    assert sources["index.html"] == "site"
    checks = [c for c in verify_build(ctx, res, publishers=[_FakePublisher()]) if not isinstance(c, str)]
    assert [c.name for c in checks][:5] == [
        "site files in dist vs the repo (byte for byte)", "page model files vs their JSON schemas",
        "generated files within the 5 MB page data budget",
        "config.json asset paths vs dist", "referenced data and image paths in dist"]
    assert all(c.ok for c in checks), "\n".join(c.render() for c in checks if not c.ok)
    prov = manifest["provenance"]
    assert prov["engine_version"] and len(prov["canonical_tables_sha256"]) == 64
    assert prov["league_config_sha256"] is None             # no league_dir given to this context
    # a rebuild replaces the previous build
    run_build(ctx, out, publishers=[])
    assert json.loads((out / "data/rankings/manifest.json").read_text()) != [{"season": 2026, "weeks": [1]}]


def test_verify_catches_schema_and_copy_problems(tmp_path):
    cfg = load_config(PREACH)
    ctx = BuildContext(cfg=cfg, tables=_tables(cfg), analysis={}, build=BUILD, site_root=ROOT)
    res = run_build(ctx, tmp_path / "dist", publishers=[])
    conf_path = tmp_path / "dist" / "config.json"
    conf = json.loads(conf_path.read_text())
    conf["managers"][0]["colors"]["dark"] = "red"
    conf_path.write_text(json.dumps(conf))
    (tmp_path / "dist" / "style.css").write_text("changed")
    checks = {c.name: c for c in verify_build(ctx, res, publishers=[]) if not isinstance(c, str)}
    assert not checks["page model files vs their JSON schemas"].ok
    assert "colors" in checks["page model files vs their JSON schemas"].examples[0]
    assert checks["site files in dist vs the repo (byte for byte)"].examples == ["style.css"]


def test_build_refuses_to_clear_a_folder_it_did_not_make(tmp_path):
    cfg = load_config(PREACH)
    ctx = BuildContext(cfg=cfg, tables=_tables(cfg), analysis={}, build=BUILD, site_root=ROOT)
    target = tmp_path / "precious"
    target.mkdir()
    (target / "notes.txt").write_text("keep me")
    with pytest.raises(SystemExit, match="not a build output"):
        run_build(ctx, target, publishers=[])
    assert (target / "notes.txt").exists()


def test_duplicate_output_paths_rejected(tmp_path):
    cfg = load_config(PREACH)
    ctx = BuildContext(cfg=cfg, tables=_tables(cfg), analysis={}, build=BUILD, site_root=ROOT)

    class Dup:
        name = "dup"

        def outputs(self, ctx):
            return [Output("config.json", {})]

        def verify(self, ctx):
            return []

    with pytest.raises(ValueError, match="two outputs"):
        run_build(ctx, tmp_path / "dist", publishers=[Dup()])


def test_size_budget_and_provenance(tmp_path):
    from engine.publish import build as build_mod

    class Big:
        name = "big"

        def outputs(self, ctx):
            return [Output("data/big.json", "x" * 2000), Output("data/small.json", "y")]

        def verify(self, ctx):
            return []

    cfg = load_config(PREACH)
    ctx = BuildContext(cfg=cfg, tables=_tables(cfg), analysis={}, build=BUILD, site_root=ROOT,
                       league_dir=PREACH.parent)
    old = build_mod.SIZE_LIMIT, build_mod.SIZE_NOTICE
    build_mod.SIZE_LIMIT, build_mod.SIZE_NOTICE = 1000, 500
    try:
        res = run_build(ctx, tmp_path / "dist", publishers=[Big()])
        check, info = build_mod.check_sizes(res)
    finally:
        build_mod.SIZE_LIMIT, build_mod.SIZE_NOTICE = old
    assert not check.ok and "data/big.json: 0.0 MB" in check.examples
    assert not any(e.startswith("data/small.json") for e in check.examples)
    assert info.startswith("INFO  page data sizes")
    prov = json.loads((tmp_path / "dist" / "build-manifest.json").read_text())["provenance"]
    assert len(prov["league_config_sha256"]) == 64 and prov["league_files"] > 50
    # the same inputs give the same digests; a changed value changes the table digest
    t = _tables(cfg)
    assert build_mod.tables_digest(t) == build_mod.tables_digest(_tables(cfg))
    first = next(iter(t))
    if len(t[first]):
        t[first] = t[first].copy()
        t[first].iloc[0, 0] = "changed" if isinstance(t[first].iloc[0, 0], str) else 12345
        assert build_mod.tables_digest(t) != build_mod.tables_digest(_tables(cfg))

"""The deploy (milestones M0 and M1 (engine/publish/deploy.py): the published root and the sanity checks."""

from __future__ import annotations

import json
from pathlib import Path

from engine.publish import deploy

ROOT = Path(__file__).resolve().parents[2]


def _build(tmp_path: Path) -> Path:
    """A stand-in engine build: every committed site file, one generated data file replacing its copy."""
    import shutil

    d = tmp_path / "build"
    for f in deploy.committed_site_files(ROOT):
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, d / f)
    (d / "data" / "matchups.json").write_text("[]")
    (d / "config.json").write_text("{}")
    return d


def test_root_is_the_engine_build(tmp_path):
    dist, out = _build(tmp_path), tmp_path / "_site"
    counts = deploy.assemble(ROOT, out, dist)
    assert counts["next"] == 0 and counts["root"] == sum(1 for p in dist.rglob("*") if p.is_file())
    assert (out / "data" / "matchups.json").read_text() == "[]"          # engine data, not the committed file
    assert deploy.check_root(ROOT, out, dist) == []
    for internal in ("engine", "docs", "tools", "leagues", "README.md", ".github", "pyproject.toml"):
        assert not (out / internal).exists(), internal
    (out / "index.html").write_text("changed")
    (out / "stray.txt").write_text("x")
    (out / "style.css").unlink()
    (dist / "style.css").unlink()
    assert deploy.check_root(ROOT, out, dist) == ["missing or changed: index.html", "not in the build: stray.txt",
                                                  "committed site file not published: style.css"]


def test_a_preview_build_goes_to_next(tmp_path):
    dist, out = _build(tmp_path), tmp_path / "_site"
    counts = deploy.assemble(ROOT, out, dist, next_dist=dist)
    assert counts["next"] == counts["root"] and (out / "next" / "index.html").is_file()
    assert deploy.check_root(ROOT, out, dist) == []


def _dist(tmp_path: Path, games: dict, week: int, files: bool = True) -> Path:
    d = tmp_path / "dist"
    (d / "data" / "v1" / "managers").mkdir(parents=True)
    keys = ["m_000000000001", "m_000000000002"]
    (d / "config.json").write_text(json.dumps({"current": {"season": 2026, "last_completed_week": week},
                                               "live_season": 2026,
                                               "managers": [{"key": k} for k in keys] + [{"key": "m_x", "hidden": True}]}))
    (d / "data" / "v1" / "matchups.json").write_text(json.dumps({"games": [{"season": s} for s, n in games.items()
                                                                           for _ in range(n)]}))
    (d / "data" / "v1" / "index.json").write_text(json.dumps({"leaderboard": [{"manager_key": k} for k in keys]}))
    for k in keys[: 2 if files else 1]:
        (d / "data" / "v1" / "managers" / f"{k}.json").write_text("{}")
    return d


def test_sanity_checks(tmp_path):
    d = _dist(tmp_path, {2025: 3, 2026: 2}, 4)
    assert deploy.sanity(d, None) == []
    prev = deploy.stats(d)
    assert prev["games"] == {"2025": 3, "2026": 2} and prev["visible_managers"] == ["m_000000000001", "m_000000000002"]
    assert deploy.sanity(d, prev) == []
    worse = {**prev, "games": {"2025": 4, "2026": 2}, "current": {"season": 2026, "last_completed_week": 5}}
    assert deploy.sanity(d, worse) == ["season 2025: 3 games, the last deploy had 4",
                                       "live week went backwards: 4 after 5"]
    # a new season starting over at week 0 is not a step backwards
    assert deploy.sanity(d, {**prev, "current": {"season": 2025, "last_completed_week": 17}}) == []


def test_sanity_needs_every_visible_manager(tmp_path):
    d = _dist(tmp_path, {2026: 1}, 1, files=False)
    assert deploy.sanity(d, None) == ["manager m_000000000002: no data/v1/managers file"]


# ---------------------------------------------------------------- M2: the new site at the root

def _web_build(tmp_path: Path) -> Path:
    """A stand-in build with the new site in next/ and the build files at its root."""
    d = tmp_path / "build"
    (d / "next" / "pages").mkdir(parents=True)
    (d / "next" / "index.html").write_text("<html>home</html>")
    (d / "next" / "pages" / "managers.html").write_text("<html>managers</html>")
    (d / "next" / "assets").mkdir()
    (d / "next" / "assets" / "a.js").write_text("export {};")
    (d / "next" / "config.json").write_text(json.dumps({"pages": [{"id": "home", "path": "index.html"},
                                                                  {"id": "managers", "path": "pages/managers.html"}]}))
    (d / "index.html").write_text("<html>stage A</html>")              # the Stage A site: not published at M2
    for name in ("build-manifest.json", "verify.json", "changes.html", deploy.STATS):
        (d / name).write_text("{}")
    return d


def test_m2_serves_the_new_site_at_the_root(tmp_path):
    dist, out = _web_build(tmp_path), tmp_path / "_site"
    counts = deploy.assemble_web(out, dist)
    assert counts == {"root": 8, "next": 2}
    assert (out / "index.html").read_text() == "<html>home</html>"       # the new site, not Stage A
    assert (out / "changes.html").is_file() and (out / deploy.STATS).is_file()
    assert deploy.check_web_root(out, dist) == []
    page = (out / "next" / "pages" / "managers.html").read_text()        # preview links still land
    assert 'url=../../pages/managers.html' in page and 'location.replace("../../pages/managers.html"' in page
    assert 'location.replace("../index.html"' in (out / "next" / "index.html").read_text()
    (out / "pages" / "managers.html").unlink()
    (out / "stray.txt").write_text("x")
    (out / "verify.json").unlink()
    assert deploy.check_web_root(out, dist) == [
        "missing or changed: pages/managers.html", "build file not published: verify.json",
        "page in config.json not published: pages/managers.html", "not in the build: stray.txt"]


def test_the_root_switch_and_its_rollback(tmp_path):
    import os
    saved = os.environ.pop("SITE_ROOT", None)
    try:
        assert deploy.root_mode() == "web"                               # M2 default
        os.environ["SITE_ROOT"] = "Legacy "
        assert deploy.root_mode() == "legacy"                            # the repository variable rolls back
        assert deploy.root_mode("web") == "web"
        try:
            deploy.root_mode("next")
            raise AssertionError("accepted an unknown root")
        except ValueError:
            pass
    finally:
        os.environ.pop("SITE_ROOT", None)
        if saved is not None:
            os.environ["SITE_ROOT"] = saved
    try:
        deploy.assemble_web(tmp_path / "_site", tmp_path)                # no new site in the build
        raise AssertionError("assembled without a new site")
    except FileNotFoundError:
        pass

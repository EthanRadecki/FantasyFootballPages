"""The Stage B site template (web/) and its preview build (engine/publish/preview.py)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from engine.publish import preview

ROOT = Path(__file__).resolve().parents[2]


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_template_holds_no_league_data():
    assert _tool("check_web").scan(ROOT / "web", ROOT / "leagues") == []


def test_the_check_finds_names_keys_and_colors(tmp_path):
    web, leagues = tmp_path / "web", tmp_path / "leagues"
    (leagues / "x").mkdir(parents=True)
    (leagues / "x" / "league.yaml").write_text(
        "league: {name: Example League}\nmanagers:\n  - {name: Jane Doe, id: m_0123456789ab, "
        "colors: {dark: '#AA1122', light: '#bb2233'}}\n")
    web.mkdir()
    (web / "a.js").write_text("var x = 'Jane Doe'; var k = 'm_0123456789ab';\nvar c = '#aa1122'; var ok = 'Doer';\n")
    (web / "b.css").write_text("/* Example League */ .x { color: #123456; }\n")
    hits = _tool("check_web").scan(web, leagues)
    assert [h.split(": ")[-1] for h in hits] == ["Jane Doe", "m_0123456789ab", "#aa1122", "Example League"]


def test_the_preview_links_pages_not_moved_yet_to_the_live_site(tmp_path):
    web = tmp_path / "web"
    (web / "pages").mkdir(parents=True)
    (web / "index.html").write_text("<html></html>")
    cfg = {"pages": [{"id": "home", "path": "index.html"}, {"id": "managers", "path": "pages/managers.html"}]}
    assert preview.preview_config(cfg, web, legacy_site=True)["pages"] == [
        {"id": "home", "path": "index.html"},
        {"id": "managers", "path": "pages/managers.html", "href": "../pages/managers.html"}]
    assert [p["id"] for p in preview.preview_config(cfg, web, legacy_site=False)["pages"]] == ["home"]


def test_write_preview(tmp_path):
    root, out = tmp_path / "repo", tmp_path / "dist"
    (root / "web" / "assets").mkdir(parents=True)
    (root / "web" / "index.html").write_text("<html></html>")
    (root / "web" / "assets" / "a.js").write_text("export {};")
    (root / "web" / ".hidden").write_text("x")
    (root / "images" / "logos").mkdir(parents=True)
    (root / "images" / "logos" / "l.png").write_bytes(b"png")
    (out / "data" / "v1").mkdir(parents=True)
    (out / "data" / "v1" / "index.json").write_text("{}")
    (out / "config.json").write_text(json.dumps({"pages": [{"id": "home", "path": "index.html"}]}))
    files = preview.write_preview(root, out, legacy_site=True)
    assert sorted(files) == ["next/assets/a.js", "next/config.json", "next/data/v1/index.json",
                             "next/images/logos/l.png", "next/index.html"]
    assert preview.write_preview(tmp_path / "no-web", out, legacy_site=True) == []


def test_the_preview_leaves_out_pages_the_league_does_not_have(tmp_path):
    """A league without weekly rankings gets no weekly rankings page (it could not load its data)."""
    root, out = tmp_path / "repo", tmp_path / "dist"
    (root / "web" / "pages").mkdir(parents=True)
    (root / "web" / "index.html").write_text("<html></html>")
    (root / "web" / "pages" / "weekly-rankings.html").write_text("<html></html>")
    (root / "web" / "pages" / "managers.html").write_text("<html></html>")
    (out / "data" / "v1").mkdir(parents=True)
    (out / "config.json").write_text(json.dumps({"pages": [{"id": "home", "path": "index.html"},
                                                           {"id": "managers", "path": "pages/managers.html"}]}))
    files = preview.write_preview(root, out, legacy_site=False)
    assert sorted(files) == ["next/config.json", "next/index.html", "next/pages/managers.html"]


def test_every_template_page_is_in_the_site_page_list():
    """A page in web/ is one of engine/publish/site.py's pages (the nav and the preview links use that list)."""
    from engine.publish.site import PAGES

    paths = {p["path"] for p in PAGES}
    web = ROOT / "web"
    pages = sorted(p.relative_to(web).as_posix() for p in web.rglob("*.html"))
    assert pages and all(p in paths for p in pages), pages

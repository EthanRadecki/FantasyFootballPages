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


def test_share_tags_give_chat_apps_a_preview_card(tmp_path):
    """A link pasted into a group chat shows a card only from tags in the HTML (crawlers run no scripts)."""
    import os
    root, out = tmp_path / "repo", tmp_path / "dist"
    (root / "web" / "pages").mkdir(parents=True)
    (root / "web" / "index.html").write_text("<html><head><title>Home</title></head></html>")
    (root / "web" / "pages" / "schedule_release.html").write_text("<html><head><title>x</title></head></html>")
    (out / "data" / "v1").mkdir(parents=True)
    cfg = {"league": {"name": "Test & Co", "first_season": 2020, "logo": "images/l.png",
                      "logos_by_season": {"2026": "images/l26.png"}, "site_url": "https://x.github.io/site/"},
           "live_season": 2026, "pages": [{"id": "home", "title": "Home", "path": "index.html"},
                                          {"id": "schedule-release", "title": "Schedule Release",
                                           "path": "pages/schedule_release.html"}]}
    (out / "config.json").write_text(json.dumps(cfg))
    saved = os.environ.pop("SITE_URL", None)
    saved_root = os.environ.get("SITE_ROOT")
    os.environ["SITE_ROOT"] = "legacy"                  # the preview at /next/ (the root from M2: below)
    try:
        preview.write_preview(root, out, legacy_site=False)
        page = (out / "next" / "pages" / "schedule_release.html").read_text()
        assert "<title>Test &amp; Co: 2026 Schedule Release</title>" in page
        assert '<meta property="og:title" content="Test &amp; Co: 2026 Schedule Release">' in page
        assert '<meta property="og:url" content="https://x.github.io/site/next/pages/schedule_release.html">' in page
        assert '<meta property="og:image" content="https://x.github.io/site/next/images/l26.png">' in page
        assert "you&#x27;re up against" in page and page.index("og:title") < page.index("</head>")
        home = (out / "next" / "index.html").read_text()
        assert '<meta property="og:title" content="Test &amp; Co">' in home
        # no public URL known: no tags (relative URLs would not work in a chat preview)
        del cfg["league"]["site_url"]
        (out / "config.json").write_text(json.dumps(cfg))
        preview.write_preview(root, out, legacy_site=False)
        assert "og:" not in (out / "next" / "index.html").read_text()
        os.environ["SITE_URL"] = "https://y.github.io/z"
        preview.write_preview(root, out, legacy_site=False)
        assert 'content="https://y.github.io/z/next/index.html"' in (out / "next" / "index.html").read_text()
        os.environ["SITE_ROOT"] = "web"                 # M2: the new site serves the root
        preview.write_preview(root, out, legacy_site=False)
        assert 'content="https://y.github.io/z/index.html"' in (out / "next" / "index.html").read_text()
    finally:
        os.environ.pop("SITE_URL", None)
        os.environ.pop("SITE_ROOT", None)
        if saved_root is not None:
            os.environ["SITE_ROOT"] = saved_root
        if saved is not None:
            os.environ["SITE_URL"] = saved


def test_a_league_without_a_logo_gets_its_own_share_card_and_icon(tmp_path):
    """Ethan, 2026-10-08: a family league link showed Preach's logo. A league with no logo gets a drawn
    card (og:image) and icon (favicon, apple-touch-icon); a league with a logo gets neither."""
    import os
    root, out = tmp_path / "repo", tmp_path / "dist"
    (root / "web" / "pages").mkdir(parents=True)
    head = '<html><head><title>x</title><link rel="icon" type="image/png" href=""></head></html>'
    (root / "web" / "index.html").write_text(head)
    (root / "web" / "pages" / "matchups.html").write_text(head)
    (out / "data" / "v1").mkdir(parents=True)
    cfg = {"league": {"name": "Radecki Family League", "first_season": 2022, "logo": None,
                      "logos_by_season": {"2026": None}, "site_url": "https://x.github.io/site/family"},
           "live_season": 2026, "theme": {"season_colors": {"2022": "#d8b28e", "2026": "#c292b8"}},
           "pages": [{"id": "home", "title": "Home", "path": "index.html"},
                     {"id": "matchups", "title": "Matchups", "path": "pages/matchups.html"}]}
    (out / "config.json").write_text(json.dumps(cfg))
    saved_root = os.environ.get("SITE_ROOT")
    os.environ["SITE_ROOT"] = "web"
    try:
        written = preview.write_preview(root, out, legacy_site=False)
        assert "next/assets/share/card.png" in written and "next/assets/share/icon.png" in written
        from PIL import Image
        assert Image.open(out / "next" / "assets" / "share" / "card.png").size == (1200, 630)
        page = (out / "next" / "pages" / "matchups.html").read_text()
        assert '<meta property="og:image" content="https://x.github.io/site/family/assets/share/card.png">' in page
        assert 'rel="apple-touch-icon" href="https://x.github.io/site/family/assets/share/icon.png"' in page
        assert '<link rel="icon" type="image/png" href="../assets/share/icon.png">' in page
        assert 'href="assets/share/icon.png"' in (out / "next" / "index.html").read_text()
        from engine.publish.share_card import initials
        assert initials("Radecki Family League") == "RFL" and initials("Preach") == "P"
        # a league with a logo keeps it: no drawn card
        out2 = tmp_path / "dist2"
        (out2 / "data" / "v1").mkdir(parents=True)
        cfg["league"]["logo"] = "images/l.png"
        (out2 / "config.json").write_text(json.dumps(cfg))
        assert not any("share/" in w for w in preview.write_preview(root, out2, legacy_site=False))
        assert "images/l.png" in (out2 / "next" / "index.html").read_text()
    finally:
        os.environ.pop("SITE_ROOT", None)
        if saved_root is not None:
            os.environ["SITE_ROOT"] = saved_root

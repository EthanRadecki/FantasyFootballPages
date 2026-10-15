"""Light images (engine/publish/images.py, decision 7.18): small WebP copies for the pages."""

from __future__ import annotations

import random

from PIL import Image

from engine.publish.images import LEAGUE_LOGO_PX, LOGO_PX, PHOTO_PX, Optimizer, light_config, light_data


def _noise(path, size, mode="RGBA"):
    rnd = random.Random(1)
    im = Image.new(mode, size)
    im.putdata([tuple(rnd.randrange(256) for _ in mode) for _ in range(size[0] * size[1])])
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def test_logos_and_photos_get_small_copies(tmp_path):
    src, dest = tmp_path / "repo", tmp_path / "site"
    _noise(src / "images/logos/big.png", (600, 500))
    _noise(src / "images/logos/league/l.png", (900, 900))
    _noise(src / "images/champions/photo.jpeg", (2400, 1600), "RGB")
    Image.new("RGBA", (20, 20), (255, 0, 0, 255)).save(src / "images/logos/tiny.png")
    opt = Optimizer(src, dest)
    cfg = light_config({"league": {"logo": "images/logos/league/l.png", "logos_by_season": {"2026": "images/logos/league/l.png"}},
                        "managers": [{"key": "a", "logo": "images/logos/big.png", "championship_logos": {"2020": "images/logos/tiny.png"}},
                                     {"key": "b", "logo": "https://espn.example/logo.png", "championship_logos": {}},
                                     {"key": "c", "logo": None}]}, opt)
    assert cfg["league"]["logo"] == f"images/_opt/logos/league/l-{LEAGUE_LOGO_PX}.webp"
    a, b, c = cfg["managers"]
    assert a["logo"] == f"images/_opt/logos/big-{LOGO_PX}.webp"
    assert a["championship_logos"] == {"2020": "images/logos/tiny.png"}      # already small: the original
    assert b["logo"] == "https://espn.example/logo.png" and c["logo"] is None
    with Image.open(dest / a["logo"]) as im:
        assert max(im.size) == LOGO_PX and im.mode == "RGBA" and im.format == "WEBP"
    model = light_data({"photos": [{"image": "images/champions/photo.jpeg", "label": "images/not-an-image"}],
                        "team_logo": "images/logos/big.png", "n": 3}, opt)
    assert model["photos"][0]["image"] == f"images/_opt/champions/photo-{PHOTO_PX}.webp"
    assert model["photos"][0]["label"] == "images/not-an-image" and model["n"] == 3
    assert model["team_logo"] == a["logo"]
    with Image.open(dest / model["photos"][0]["image"]) as im:
        assert im.size == (PHOTO_PX, round(1600 * PHOTO_PX / 2400))
    assert len(opt.written) == 3 and opt.bytes_after < opt.bytes_before
    assert light_data({"x": "images/missing.png"}, opt) == {"x": "images/missing.png"}

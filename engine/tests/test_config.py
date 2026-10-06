from pathlib import Path

from engine.config import load_config, slugify, validate_config

REPO = Path(__file__).resolve().parents[2]
PREACH = REPO / "leagues" / "preach" / "league.yaml"


def minimal(**overrides):
    cfg = {
        "league": {"name": "Test", "provider": "espn", "league_id": 1, "first_season": 2020},
        "managers": [{"name": "A Person", "id": "x1", "colors": {"dark": "#112233", "light": "#445566"}}],
    }
    cfg.update(overrides)
    return cfg


def test_preach_config_is_valid():
    report = validate_config(load_config(PREACH))
    assert report.ok, report.errors


def test_slugify():
    assert slugify("Carmine Pittelli Jr.") == "carmine-pittelli-jr"
    assert slugify("Ben Castaldo") == "ben-castaldo"


def test_minimal_config_passes_clean():
    report = validate_config(minimal())
    assert report.ok and not report.warnings


def test_unsupported_provider_fails():
    cfg = minimal()
    cfg["league"]["provider"] = "yahoo"
    assert not validate_config(cfg).ok


def test_bad_color_fails():
    cfg = minimal(managers=[{"name": "A", "id": "1", "colors": {"dark": "orange"}}])
    assert not validate_config(cfg).ok


def test_theme_colors_are_checked():
    """season_colors and champion_tints must be #RRGGBB."""
    assert validate_config(minimal(theme={"champion_tints": {2020: "#ea7988"}})).ok
    report = validate_config(minimal(theme={"champion_tints": {2020: "pink"}}))
    assert not report.ok and "theme.champion_tints.2020" in report.errors[0]


def test_duplicate_manager_fails():
    cfg = minimal(managers=[{"name": "A", "id": "1"}, {"name": "A", "id": "2"}])
    assert not validate_config(cfg).ok


def test_unknown_excluded_manager_fails():
    cfg = minimal(analysis={"exclude_managers": ["nobody"]})
    assert not validate_config(cfg).ok


def test_unknown_color_role_fails():
    cfg = minimal(managers=[{"name": "A", "id": "1", "colors": {"neon": "#112233"}}])
    assert not validate_config(cfg).ok


def test_unknown_record_game_type_fails():
    assert not validate_config(minimal(analysis={"record_games": ["regular_season", "exhibition"]})).ok

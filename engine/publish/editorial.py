"""League editorial files: hand-written content a league may add.

They live in `leagues/<league>/editorial/<name>.yaml` beside league.yaml
(phase 5 moves the rest of the site's editorial content there). Every page
works without them: a missing file means the generated fallback.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def editorial_path(ctx, name: str) -> Path | None:
    base = getattr(ctx, "league_dir", None)
    return None if base is None else Path(base) / "editorial" / f"{name}.yaml"


def load_editorial(ctx, name: str):
    """The parsed file, or None when the league has none."""
    path = editorial_path(ctx, name)
    if path is None or not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

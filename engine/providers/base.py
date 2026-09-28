"""Provider interface.

A provider pulls raw league data from one fantasy platform and caches it
verbatim. Normalizing that data into canonical tables is a separate step
(engine.normalize), so the raw cache can always be re-read and re-checked
without calling the platform again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Provider(Protocol):
    name: str

    def pull_season(self, season: int, out_dir: Path) -> dict:
        """Download one season into out_dir. Returns a summary dict of counts."""
        ...

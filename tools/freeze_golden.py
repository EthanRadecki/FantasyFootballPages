"""Freeze site data as a golden file (engine/tests/golden/), gzipped JSON.

Goldens are frozen copies of what the site shows today; Stage A checks
compare publish's legacy views against them (docs/PUBLISH_PLAN.md).

    python tools/freeze_golden.py data/network_data.js trades/network_data.json.gz
    python tools/freeze_golden.py pages/trade-value.html trades/trade_value_inline.json.gz --vars LEADERBOARD_TOTALS

A .js data file freezes every `var NAME = ...` global it defines (one global
is stored as its value, several as {NAME: value}). A page freezes the named
inline literals as {NAME: value}. Never edit a golden by hand; refreeze from
the site file and record why in engine/tests/golden/README.md.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.publish.legacy_view import read_js_globals, read_literal  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("source", help="site file: data/*.js, data/*.json or pages/*.html")
    p.add_argument("golden", help="path under engine/tests/golden/, ending .json.gz")
    p.add_argument("--vars", nargs="*", help="inline literals to freeze (pages)")
    a = p.parse_args()
    text = Path(a.source).read_text(encoding="utf-8")
    if a.vars:
        value = {v: read_literal(text, v) for v in a.vars}
    elif a.source.endswith(".js"):
        g = read_js_globals(text)
        value = next(iter(g.values())) if len(g) == 1 else g
    else:
        value = json.loads(text)
    out = Path("engine/tests/golden") / a.golden
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, separators=(",", ":"))
    print(f"froze {a.source} -> {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

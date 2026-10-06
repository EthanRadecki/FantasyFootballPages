"""Write the synthetic test league (engine/testing/synthetic.py).

    python tools/synthetic_league.py --cache .cache-synthetic        # the raw ESPN cache
    python tools/synthetic_league.py --yaml leagues/synthetic/league.yaml

Deterministic: the same files on every run. CI writes the cache, then runs
normalize, analyze and build --verify on leagues/synthetic/league.yaml.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.testing import synthetic  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--cache", help="cache root to write the raw league into")
    p.add_argument("--yaml", help="path to write the league's league.yaml")
    args = p.parse_args(argv)
    if not args.cache and not args.yaml:
        p.error("give --cache, --yaml or both")
    if args.cache:
        out = synthetic.write_league(Path(args.cache))
        print(f"wrote {sum(1 for _ in out.rglob('*.json'))} files under {out}")
    if args.yaml:
        Path(args.yaml).parent.mkdir(parents=True, exist_ok=True)
        Path(args.yaml).write_text(synthetic.league_yaml(), encoding="utf-8", newline="\n")
        print(f"wrote {args.yaml}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

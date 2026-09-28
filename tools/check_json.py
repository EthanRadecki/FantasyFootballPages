"""Fail if any JSON file in the repo does not parse.

Usage: python tools/check_json.py [root]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKIP_DIRS = {".git", ".conda", ".venv", "venv", "node_modules", "dist", ".cache", "_legacy", ".vscode"}


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    checked = failed = 0
    for path in sorted(root.rglob("*.json")):
        if SKIP_DIRS.intersection(path.relative_to(root).parts):
            continue
        checked += 1
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            failed += 1
            print(f"{path.relative_to(root)}: {exc}")
    if failed:
        print(f"\nFAIL: {failed} of {checked} JSON file(s) are invalid.")
        return 1
    print(f"OK: {checked} JSON file(s) parse.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

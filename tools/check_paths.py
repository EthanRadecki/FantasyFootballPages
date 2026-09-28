"""Fail if HTML or JS references a data or image file that does not exist.

Checks string literals like "../data/matchups.json" or "images/logos/Root.png".
Dynamic paths built at runtime (a folder prefix plus a variable) are skipped;
only literals ending in a file extension are checked.

A reference passes if it resolves relative to the referencing file, the repo
root, or pages/ (root-level JS such as shared.js runs inside pages/*.html).

Usage: python tools/check_paths.py [root]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", ".conda", ".venv", "venv", "node_modules", "dist", ".cache", "_legacy", "engine", "tools"}
REF = re.compile(r"""["'`(]((?:\.\./|\./)*(?:data|images|assets)/[^"'`)\s?#{}+]+\.[A-Za-z0-9]{2,5})["'`)]""")


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    bases_extra = [root, root / "pages"]
    checked = 0
    missing: list[str] = []
    for path in sorted(list(root.rglob("*.html")) + list(root.rglob("*.js"))):
        rel = path.relative_to(root)
        if SKIP_DIRS.intersection(rel.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for ref in REF.findall(line):
                checked += 1
                bases = [path.parent, *bases_extra]
                if not any((base / ref).resolve().is_file() for base in bases):
                    missing.append(f"{rel}:{lineno}: missing {ref}")
    for item in missing:
        print(item)
    if missing:
        print(f"\nFAIL: {len(missing)} of {checked} referenced path(s) do not exist.")
        return 1
    print(f"OK: {checked} referenced path(s) exist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

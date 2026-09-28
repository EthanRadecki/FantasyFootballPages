"""Fail if any source file contains an em dash.

Site-wide style rule: no em dashes anywhere in the codebase. Catches the
literal character, the HTML entity, and JS/Python/JSON unicode escapes.

Usage: python tools/check_style.py [root]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

EXTENSIONS = {".html", ".js", ".css", ".py", ".json", ".md", ".yaml", ".yml", ".csv"}
SKIP_DIRS = {".git", ".conda", ".venv", "venv", "node_modules", "dist", ".cache", "_legacy"}
# Assembled from parts so this file does not flag itself.
_EM = chr(0x2014)
_FORMS = [_EM, "&" + "mdash;", "&#" + "8212;", "&#x" + "2014;", "\\" + "u2014"]
PATTERN = re.compile("|".join(re.escape(f) for f in _FORMS), re.IGNORECASE)


def iter_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in EXTENSIONS:
            if not SKIP_DIRS.intersection(path.relative_to(root).parts):
                yield path


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    violations = 0
    for path in iter_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if PATTERN.search(line):
                violations += 1
                snippet = line.strip()[:120]
                print(f"{path.relative_to(root)}:{lineno}: em dash: {snippet}")
    if violations:
        print(f"\nFAIL: {violations} line(s) contain an em dash.")
        return 1
    print("OK: no em dashes found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

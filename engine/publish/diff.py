"""Compare a generated JSON value with its golden, section by section.

Used by every Stage A check: a legacy view built from legacy-mode analysis
must reproduce the current site file. Differences a known legacy bug
explains are counted by reason (never by editing the golden).
"""

from __future__ import annotations

from typing import Any, Callable

from engine.legacy import Comparison

Known = Callable[[str, Any, Any], "str | None"]


def diff(a: Any, b: Any, path: str = "", out: list | None = None, tol: float = 1e-9) -> list[tuple]:
    """(path, engine value, legacy value) for every leaf that differs.
    `a` is the engine value, `b` the legacy value; numbers within `tol` match."""
    out = [] if out is None else out
    if isinstance(b, dict):
        if not isinstance(a, dict):
            out.append((path, a, b))
            return out
        for k in list(b) + [k for k in a if k not in b]:
            if k not in a or k not in b:
                out.append((f"{path}/{k}", a.get(k, "<missing>"), b.get(k, "<missing>")))
            else:
                diff(a[k], b[k], f"{path}/{k}", out, tol)
    elif isinstance(b, list):
        if not isinstance(a, list) or len(a) != len(b):
            out.append((path, f"list of {len(a) if isinstance(a, list) else a}", f"list of {len(b)}"))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                diff(x, y, f"{path}[{i}]", out, tol)
    elif isinstance(b, (int, float)) and isinstance(a, (int, float)) and not isinstance(b, bool) \
            and not isinstance(a, bool):
        if abs(float(a) - float(b)) > tol:
            out.append((path, a, b))
    elif a != b:
        out.append((path, a, b))
    return out


def leaves(x: Any) -> int:
    if isinstance(x, dict):
        return sum(leaves(v) for v in x.values())
    if isinstance(x, list):
        return sum(leaves(v) for v in x) or 1
    return 1


def compare_json(name: str, engine: Any, legacy: Any, known: Known | None = None, tol: float = 1e-9,
                 by_section: bool = True) -> list[Comparison]:
    """One Comparison per top-level section of a dict golden (or one for the
    whole value when `by_section` is False or the golden is not a dict).
    known(path, engine value, legacy value) -> reason or None."""
    if by_section and isinstance(legacy, dict):
        parts = [(f"{name} {s} vs published", engine.get(s) if isinstance(engine, dict) else None, legacy[s], f"/{s}")
                 for s in legacy]
    else:
        parts = [(f"{name} vs published", engine, legacy, "")]
    out = []
    for label, eng, leg, root in parts:
        c = Comparison(label, leaves(leg), leaves(eng if eng is not None else {}))
        bad = []
        for d in diff(eng, leg, root, tol=tol):
            reason = known(*d) if known else None
            if reason:
                c.known[reason] = c.known.get(reason, 0) + 1
            else:
                bad.append(d)
        c.mismatched["values"] = len(bad)
        c.examples = [f"{p}: legacy={lv!r} engine={ev!r}" for p, ev, lv in bad[:4]]
        out.append(c)
    return out

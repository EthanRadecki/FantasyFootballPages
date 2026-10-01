"""Helpers for Stage A legacy views: today's site files, rebuilt by publish.

A legacy view lets the current pages run on engine data unchanged until each
page moves into `web/` (Stage B), when its legacy view is deleted. Legacy
files name managers the way that file always did ("Carmine Pittelli Jr." on
one page, "Carmine Pittelli" on another), so each view takes its spellings
from the current site file it replaces, falling back to the config name for
a manager the file has never seen.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from engine.legacy import name_to_key
from engine.publish.writer import clean


def site_json(ctx, rel: str):
    path = Path(ctx.site_root) / rel
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def site_csv(ctx, rel: str) -> pd.DataFrame | None:
    path = Path(ctx.site_root) / rel
    return pd.read_csv(path) if path.is_file() else None


def spellings(names: Iterable[str], cfg: dict) -> dict[str, str]:
    """member key -> the spelling these legacy names use (first seen wins)."""
    lookup = name_to_key(cfg)
    out: dict[str, str] = {}
    for n in names:
        if not isinstance(n, str):
            continue
        key = lookup.get(n.strip().lower())
        if key and key not in out:
            out[key] = n
    return out


class Names:
    """Display names for one legacy file: its own spelling, else config."""

    def __init__(self, ctx, legacy_names: Iterable[str] = ()):
        self.config = {m["key"]: m for m in ctx.config["managers"]}
        self.spelled = spellings(legacy_names, ctx.cfg)

    def __call__(self, key: str) -> str:
        return self.spelled.get(key) or self.config[key]["name"]

    def short(self, key: str) -> str:
        return self.config[key]["short"]


def csv_text(df: pd.DataFrame, index_label: str | None = None) -> str:
    buf = io.StringIO()
    if index_label is None:
        df.to_csv(buf, index=False, lineterminator="\n")
    else:
        df.to_csv(buf, index=True, index_label=index_label, lineterminator="\n")
    return buf.getvalue()


def info_diff(name: str, live: pd.DataFrame, engine: pd.DataFrame, keys: list[str], values: list[str],
              tol: float = 0.005) -> str:
    """One INFO line: how the engine's data differs from the live site file
    (what the live page will show after milestone M1). Not a check."""
    both = live.merge(engine, on=keys, how="outer", suffixes=("_l", "_e"), indicator=True)
    only_e = int((both["_merge"] == "right_only").sum())
    only_l = int((both["_merge"] == "left_only").sum())
    b = both[both["_merge"] == "both"]
    changed = pd.Series(False, index=b.index)
    for v in values:
        lv, ev = b[f"{v}_l"], b[f"{v}_e"]
        if pd.api.types.is_numeric_dtype(lv) and pd.api.types.is_numeric_dtype(ev):
            changed |= (lv.astype(float) - ev.astype(float)).abs().gt(tol)
        else:
            changed |= lv.astype(str) != ev.astype(str)
    return (f"INFO  {name}, engine data vs the live file: {len(b)} rows in both, {int(changed.sum())} with a "
            f"different {'/'.join(values)}; {only_e} only in the engine, {only_l} only in the live file "
            f"(later weeks, or rows the live file keys differently)")


# ---------------------------------------------------------------- JavaScript data (globals and inline blocks)

_IDENT = re.compile(r"[A-Za-z_$][\w$]*")


def js_to_json(text: str) -> str:
    """A JavaScript data literal as JSON text: quotes bare and numeric object
    keys, turns single-quoted strings into JSON strings, drops comments and
    trailing commas. For the plain data the site's pages and .js files hold
    (objects, arrays, strings, numbers, true, false, null), not general code."""
    out, i, n = [], 0, len(text)
    expect_key = False            # just after '{' or ',' inside an object
    stack: list[str] = []
    while i < n:
        c = text[i]
        if c in "\"'":
            j, buf = i + 1, []
            while j < n and text[j] != c:
                if text[j] == "\\":
                    nxt = text[j + 1]
                    buf.append("'" if nxt == "'" else "\\" + nxt)
                    j += 2
                    continue
                buf.append('\\"' if text[j] == '"' else text[j])
                j += 1
            out.append('"' + "".join(buf) + '"')
            i, expect_key = j + 1, False
            continue
        if text.startswith("//", i):
            i = text.find("\n", i) if text.find("\n", i) != -1 else n
            continue
        if text.startswith("/*", i):
            i = text.find("*/", i) + 2
            continue
        if c in "{[":
            stack.append(c)
            expect_key = c == "{"
            out.append(c)
        elif c in "}]":
            while out and out[-1].strip() == "":
                out.pop()
            if out and out[-1] == ",":
                out.pop()                                  # trailing comma
            stack.pop()
            out.append(c)
            expect_key = False
        elif c == ",":
            out.append(c)
            expect_key = bool(stack) and stack[-1] == "{"
        elif expect_key and (c.isalpha() or c in "_$" or c.isdigit() or c == "-"):
            m = _IDENT.match(text, i) or re.compile(r"-?\d+(?:\.\d+)?").match(text, i)
            key = m.group(0)
            k = m.end()
            while k < n and text[k].isspace():
                k += 1
            if k < n and text[k] == ":":
                out.append(json.dumps(key))
                i = m.end()
                expect_key = False
                continue
            out.append(key)
            i = m.end()
            expect_key = False
            continue
        else:
            if not c.isspace():
                expect_key = False
            out.append(c)
        i += 1
    return "".join(out)


def parse_js(text: str):
    return json.loads(js_to_json(text))


def literal_span(text: str, name: str) -> tuple[int, int]:
    """(start, end) of the literal assigned by the first `var|let|const <name> =`."""
    m = re.search(rf"\b(?:var|let|const)\s+{re.escape(name)}\s*=\s*", text)
    if not m:
        raise KeyError(f"no `{name} = ...` in the page")
    start = m.end()
    if text[start] not in "[{":
        raise ValueError(f"{name} is not an object or array literal")
    depth, i, quote = 0, start, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c in "[{(":
            depth += 1
        elif c in "]})":
            depth -= 1
            if depth == 0:
                return start, i + 1
        i += 1
    raise ValueError(f"{name}: unterminated literal")


def read_literal(text: str, name: str):
    s, e = literal_span(text, name)
    return parse_js(text[s:e])


def replace_literal(text: str, name: str, value) -> str:
    """The page with `name`'s literal replaced by `value` as JSON (valid JS)."""
    s, e = literal_span(text, name)
    return text[:s] + json.dumps(clean(value), ensure_ascii=False, separators=(",", ":")) + text[e:]


def js_globals(values: dict) -> str:
    """A legacy `data/*.js` file: one `var NAME = <json>;` line per global."""
    return "".join(f"var {k} = {json.dumps(clean(v), ensure_ascii=False, separators=(',', ':'))};\n"
                   for k, v in values.items())


def read_js_globals(text: str) -> dict:
    out = {}
    for m in re.finditer(r"\bvar\s+(\w+)\s*=\s*", text):
        s, e = literal_span(text[m.start():], m.group(1))
        out[m.group(1)] = parse_js(text[m.start():][s:e])
    return out

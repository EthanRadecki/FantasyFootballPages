"""Weekly rankings blurb formatter (engine/publish/blurbs.py) and its JavaScript twin
(web/assets/js/core/blurbs.js, run with node when it is installed): the shared cases in
golden/blurbs/cases.json, and 2026 week 5 (formatted by these rules in session 11) comes
back identical from its plain text."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from engine.publish import blurbs as B
from engine.publish.pages.editor import manager_names

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "golden" / "blurbs"
VOCAB = json.loads((GOLDEN / "vocab_2026.json").read_text(encoding="utf-8"))
CASES = json.loads((GOLDEN / "cases.json").read_text(encoding="utf-8"))["cases"]
WEEK5 = json.loads((ROOT / "leagues" / "preach" / "editorial" / "rankings" / "2026_week05.json").read_text(
    encoding="utf-8"))


def _week5_items():
    items = [(t["blurb"], t["synopsis"], True) for t in WEEK5["teams"]]
    items.append((WEEK5["matchup_of_the_week"]["blurb"], None, False))
    return items


def test_shared_cases():
    for c in CASES:
        html, synopsis = B.format_blurb(c["text"], VOCAB, c["auto_key"])
        assert (html, synopsis) == (c["html"], c["synopsis"]), c["name"]


def test_week5_round_trips():
    for blurb, synopsis, auto in _week5_items():
        src = B.to_source(blurb, auto)
        assert "<" not in src
        html, syn = B.format_blurb(src, VOCAB, auto)
        assert html == blurb
        if synopsis is not None:
            assert syn == synopsis


def test_javascript_twin_matches():
    node = shutil.which("node")
    if node is None:                      # CI runners and the Codespace have node
        return
    items = [{"text": c["text"], "auto_key": c["auto_key"]} for c in CASES]
    sources = [{"html": b, "auto_key": a} for b, _, a in _week5_items()]
    items += [{"text": B.to_source(s["html"], s["auto_key"]), "auto_key": s["auto_key"]} for s in sources]
    job = json.dumps({"vocab": VOCAB, "items": items, "sources": sources}, ensure_ascii=False)
    res = subprocess.run([node, str(Path(__file__).parent / "js" / "blurbs_run.mjs")], input=job.encode("utf-8"),
                         capture_output=True, check=True)
    out = json.loads(res.stdout.decode("utf-8"))
    for item, got in zip(items, out["formatted"]):
        html, synopsis = B.format_blurb(item["text"], VOCAB, item["auto_key"])
        assert (got["html"], got["synopsis"]) == (html, synopsis), item["text"][:60]
    for s, got in zip(sources, out["sources"]):
        assert got == B.to_source(s["html"], s["auto_key"])


def test_to_source_marks_a_key_that_is_not_the_first_sentence():
    html, _ = B.format_blurb("Not flashy. **Cole wins.** Done.", VOCAB, True)
    assert B.to_source(html) == "Not flashy. **Cole wins.** Done."
    html, _ = B.format_blurb("Cole wins. Done.", VOCAB, True)
    assert B.to_source(html) == "Cole wins. Done."


def test_problems():
    assert B.problems("a " + chr(0x2014) + " b") == ["em dash: use a comma, colon or parentheses"]
    assert B.problems("**open") == ["unclosed ** key sentence marker"]
    assert B.problems("  ") == ["empty"] and B.problems("fine") == []


def test_manager_names_keep_shared_first_names_out():
    ms = [{"key": "a", "name": "Ann Radecki", "colors": {"dark": "#111111"}},
          {"key": "b", "name": "Ann Smith", "aliases": ["Annie S"], "colors": {"dark": "#222222"}},
          {"key": "c", "name": "Joe Radecki", "colors": {}}]
    got = {m["key"]: m["names"] for m in manager_names(ms, {"Big Joe": "joe radecki"})}
    assert got == {"a": ["Ann Radecki"], "b": ["Ann Smith", "Annie S", "Smith"], "c": ["Joe Radecki", "Big Joe", "Joe"]}
    try:
        manager_names(ms, {"X": "Nobody"})
        raise AssertionError("expected an error")
    except ValueError:
        pass


def test_player_names_add_unsuffixed_names_once():
    v = {"players": ["Kenneth Walker III", "Travis Etienne Jr.", "Marvin Harrison", "Marvin Harrison Jr.", "Solo"]}
    names = set(B.player_names(v))
    assert {"Kenneth Walker", "Travis Etienne", "Marvin Harrison", "Marvin Harrison Jr."} <= names
    assert "Solo" not in names

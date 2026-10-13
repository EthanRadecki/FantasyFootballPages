"""Weekly rankings blurb formatter: plain text in, the page's highlight markup out.

The rankings editor (web/admin/) runs the JavaScript twin, web/assets/js/core/blurbs.js;
both follow the same rules and are tested on the same cases
(engine/tests/golden/blurbs/cases.json), so a blurb formats the same in the editor's
preview, in a draft file and in the build.

Rules, in order (each pass skips text an earlier pass already marked):
    1. quotes      ' and " become curly (’ ‘ ” “); HTML special characters are escaped
    2. [[img:id]]  screenshot markers are left exactly as written
    3. teams       every team name of the league (`<em class="hl-team">`), longest first,
                   any case
    4. players     multi-word player names (`<mark class="hl-player">`), longest first, any
                   case; suffixes like "Jr." are part of the name, and the name without its
                   suffix counts too when no other player has it
    5. managers    full names, aliases, nicknames (editorial blurbs.yaml), and first and last
                   names that only one manager has (`<mark class="hl-manager"
                   style="color:<dark color>;">`); exact case, so "max" stays a word
    6. positions   QB, RB, WR, TE as words, also in plurals and ranks: WRs, QB11, RB2
                   (`<mark class="hl-pos-QB">`)
    7. numbers     integers, decimals, 1,234, 45%, 2nd (`<strong class="hl-stat">`); not after
                   a letter, digit, #, $ or "."
    8. key         **like this** marks the key sentence (`<strong class="hl-key">`); without
                   it, a manager's blurb uses its first sentence (abbreviations such as Jr.,
                   St., N.Y. inside names do not end a sentence) and other blurbs have none
The synopsis is the key sentence as plain text.

A name counts only between word boundaries: "Ben" in "Bengals" is not a manager.
"""

from __future__ import annotations

import re

POSITIONS = ("QB", "RB", "WR", "TE")
ABBREVIATIONS = ("Jr", "Sr", "St", "Mr", "Mrs", "Ms", "Dr", "vs", "No", "Jan", "Feb", "Aug", "Sept", "Oct", "Nov",
                 "Dec")
NUMBER = re.compile(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?(?:%|st|nd|rd|th)?")
IMG = re.compile(r"\[\[img:[^\]\s]+\]\]")
KEY = re.compile(r"\*\*(.+?)\*\*", re.S)
PH0 = 0xE100            # placeholders: one private-use character per marked span (never a word character)
KEY_OPEN, KEY_CLOSE = "\ue001", "\ue002"   # the key sentence's start and end while formatting


def is_word(c: str) -> bool:
    return c.isalnum() or c == "_"


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def unescape(text: str) -> str:
    """The entities blurbs use (the JavaScript twin decodes the same ones)."""
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"&#[xX]([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)
    for k, v in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&nbsp;", "\u00a0"), ("&amp;", "&")):
        text = text.replace(k, v)
    return text


def curly(text: str) -> str:
    """Straight quotes to curly: an opening one after a space, an opening bracket or a dash, or at the start."""
    out = []
    for i, c in enumerate(text):
        prev = text[i - 1] if i else " "
        opening = prev.isspace() or prev in "([{-\u2013" or prev in (KEY_OPEN,)
        if c == "'":
            out.append("‘" if opening and i + 1 < len(text) and not text[i + 1].isspace() else "’")
        elif c == '"':
            out.append("“" if opening else "”")
        else:
            out.append(c)
    return "".join(out)


class _Spans:
    """Marked spans behind placeholder characters."""

    def __init__(self):
        self.html: list[str] = []
        self.plain: list[str] = []

    def add(self, markup: str, plain: str) -> str:
        self.html.append(markup)
        self.plain.append(plain)
        return chr(PH0 + len(self.html) - 1)

    def restore(self, text: str, plain: bool = False) -> str:
        src = self.plain if plain else self.html
        return re.sub("[\ue100-\uf8ff]", lambda m: src[ord(m.group()) - PH0], text)


def _replace_terms(text: str, terms: list[tuple[str, str]], spans: _Spans, ignore_case: bool) -> str:
    """Mark every whole-word occurrence of each term (longest first). terms: (term, opening tag)."""
    for term, tag in sorted(terms, key=lambda t: (-len(t[0]), t[0])):
        if not term:
            continue
        flags = re.I if ignore_case else 0
        pat = re.compile(re.escape(term), flags)
        out, pos = [], 0
        for m in pat.finditer(text):
            s, e = m.span()
            if s < pos:
                continue
            if is_word(term[0]) and s > 0 and is_word(text[s - 1]):
                continue
            if is_word(term[-1]) and e < len(text) and is_word(text[e]):
                continue
            close = "</" + tag[1:tag.index(" ")] + ">"
            out.append(text[pos:s])
            out.append(spans.add(tag + m.group() + close, m.group()))
            pos = e
        out.append(text[pos:])
        text = "".join(out)
    return text


def _positions(text: str, spans: _Spans) -> str:
    """QB, RB, WR, TE as words, and inside plurals and ranks: "WRs", "QB11", "RB2"."""
    def sub(m):
        s, e = m.span()
        prev = text[s - 1] if s else " "
        nxt = text[e:e + 2]
        if is_word(prev):
            return m.group()
        if nxt[:1] and is_word(nxt[0]) and not nxt[0].isdigit() and not (
                nxt[0] == "s" and (len(nxt) < 2 or not is_word(nxt[1]))):
            return m.group()
        return spans.add(f'<mark class="hl-pos-{m.group()}">{m.group()}</mark>', m.group())
    return re.sub("|".join(POSITIONS), sub, text)


def _numbers(text: str, spans: _Spans) -> str:
    def sub(m):
        s = m.start()
        prev = text[s - 1] if s else " "
        e = m.end()
        nxt = text[e] if e < len(text) else " "
        if is_word(prev) or prev in "#$." or is_word(nxt):
            return m.group()
        return spans.add(f'<strong class="hl-stat">{m.group()}</strong>', m.group())
    return NUMBER.sub(sub, text)


def first_sentence_end(text: str) -> int | None:
    """Index just past the first sentence's closing punctuation (and closing quotes or brackets),
    or None when the text is one sentence. Placeholders count as words."""
    for m in re.finditer(r"[.!?]+[’”\")\]]*", text):
        e = m.end()
        if e < len(text) and not text[e].isspace():
            continue
        if e >= len(text.rstrip()):
            return None
        if m.group().startswith("."):
            word = re.search(r"([A-Za-z.]+)$", text[:m.start()])
            w = word.group(1) if word else ""
            if w in ABBREVIATIONS or re.fullmatch(r"(?:[A-Z]\.)*[A-Z]", w):   # Jr. / N.Y. / A.J.
                continue
        return e
    return None


SUFFIX = re.compile(r"\s+(?:Jr\.?|Sr\.?|II|III|IV|V)$")


def player_names(vocab: dict) -> list[str]:
    """The vocab's multi-word player names plus each name without its suffix (Jr., III) when that
    shorter name is not another player's."""
    names = [p.strip() for p in vocab.get("players") or [] if " " in str(p).strip()]
    full = set(names)
    short: dict[str, int] = {}
    for p in names:
        s = SUFFIX.sub("", p)
        if s != p and " " in s:
            short[s] = short.get(s, 0) + 1
    return sorted(full | {s for s, n in short.items() if n == 1 and s not in full})


def vocabulary_terms(vocab: dict) -> tuple[list, list, list]:
    """(team terms, player terms, manager terms) as (text, opening tag) pairs from a vocab model."""
    teams = [(curly(escape(t)), '<em class="hl-team">') for t in vocab.get("teams") or []]
    players = [(curly(escape(p)), '<mark class="hl-player">') for p in player_names(vocab)]
    managers = []
    for m in vocab.get("managers") or []:
        tag = f'<mark class="hl-manager" style="color:{m["color"]};">' if m.get("color") else '<mark class="hl-manager">'
        managers += [(curly(escape(n)), tag) for n in m.get("names") or []]
    return teams, players, managers


def format_blurb(text: str, vocab: dict, auto_key: bool = True) -> tuple[str, str]:
    """Plain text (as typed in the editor) -> (blurb HTML, synopsis). See the module docstring."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return "", ""
    spans = _Spans()
    text = IMG.sub(lambda m: spans.add(m.group(), ""), text)       # kept in the blurb, left out of the synopsis
    explicit = bool(KEY.search(text))
    text = KEY.sub(lambda m: KEY_OPEN + m.group(1).strip() + KEY_CLOSE, text)
    text = curly(escape(text))
    teams, players, managers = vocabulary_terms(vocab)
    text = _replace_terms(text, teams, spans, ignore_case=True)
    text = _replace_terms(text, players, spans, ignore_case=True)
    text = _replace_terms(text, managers, spans, ignore_case=False)
    text = _positions(text, spans)
    text = _numbers(text, spans)
    if not explicit and auto_key:
        end = first_sentence_end(text)
        text = KEY_OPEN + (text if end is None else text[:end] + KEY_CLOSE + text[end:])
        if end is None:
            text += KEY_CLOSE
    key = re.search(KEY_OPEN + "(.*?)" + KEY_CLOSE, text, re.S)
    synopsis = re.sub(r"\s+", " ", unescape(spans.restore(key.group(1), plain=True))).strip() if key else ""
    out = spans.restore(text).replace(KEY_OPEN, '<strong class="hl-key">').replace(KEY_CLOSE, "</strong>")
    return out, synopsis


def _unwrap_key(s: str) -> str:
    """The hl-key <strong> (which holds other <strong> tags) replaced by ** markers."""
    open_tag = '<strong class="hl-key">'
    i = s.find(open_tag)
    if i < 0:
        return s
    depth, j = 1, i + len(open_tag)
    for m in re.compile(r"<(/?)strong\b[^>]*>").finditer(s, j):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return s[:i] + "**" + s[j:m.start()] + "**" + s[m.end():]
    return s


def to_source(blurb_html: str, auto_key: bool = True) -> str:
    """A published blurb back to the editor's plain text: tags dropped, entities decoded, the key
    sentence marked **like this** unless it is the first sentence the formatter picks anyway."""
    s = unescape(re.sub(r"<[^>]+>", "", _unwrap_key(str(blurb_html or ""))))
    s = re.sub(r"\s+", " ", s).strip()
    if auto_key and s.startswith("**") and s.count("**") == 2:
        close = s.index("**", 2) - 2                 # where the key ends in the text without markers
        plain = s[2:close + 2] + s[close + 4:]
        end = first_sentence_end(plain)
        if end == close or (end is None and close == len(plain)):
            return plain
    return s


def problems(text: str) -> list[str]:
    """Warnings the editor shows beside a blurb."""
    out = []
    if chr(0x2014) in text:
        out.append("em dash: use a comma, colon or parentheses")
    if text.count("**") % 2:
        out.append("unclosed ** key sentence marker")
    if not str(text).strip():
        out.append("empty")
    return out

"""Player headshots: the images on managers.html, champions.html and weekly-rankings.html.

Outputs
    data/v1/headshots.json        page model (schema "headshots"): player id -> image URL
    data/player_headshots.json    legacy view: "Player Name|POS" -> image URL, as the pages read it

Decision 7.5: images come from the league's provider by player id (ESPN: the
headshot by ESPN player id, a D/ST its team's logo), for any league; the
hand-kept NFL.com file is retired. Pages keep their missing-image fallback, so
a player ESPN has no headshot for shows the placeholder as before.

Players covered: every player the league's data names (lineups, drafts, player
cards, and every season's player pool). The legacy view keys each one by its
ESPN name and position, plus every other spelling the published data uses for
the same player (the live file's keys and the names in the rankings snapshots,
matched on name and position ignoring case, accents, punctuation and suffixes
such as Jr. or III, or on the name alone when only one player has it), so
frozen files keep their pictures. D/ST logos are in the
page model only: today's pages show no D/ST images, and Stage B decides where
they appear.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

from engine.legacy import Comparison
from engine.publish import rankings as R
from engine.publish.build import Output
from engine.publish.legacy_view import site_json

SCHEMA, VERSION = "headshots", 1
LIVE = "data/player_headshots.json"
SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\.?$")


def norm(name) -> str:
    """Name for matching spellings: no accents, case, punctuation or generational suffix."""
    n = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower().strip()
    n = SUFFIX.sub("", n).strip()
    return re.sub(r"[^a-z0-9]", "", n)


def name_rows(tables: dict) -> pd.DataFrame:
    """player_id, player_name, position, season (+ pro_team_id): every name and position the
    league's tables list for a player, one row per table row (the players table as season -1)."""
    parts = []
    for name in ("player_stats", "player_seasons", "lineups"):
        t = tables.get(name)
        if t is not None and len(t):
            cols = ["player_id", "player_name", "position", "season"] + (["pro_team_id"] if "pro_team_id" in t else [])
            parts.append(t[cols])
    pl = tables.get("players")
    if pl is not None and len(pl):
        parts.append(pl[["player_id", "player_name", "position"]].assign(season=-1))
    if not parts:
        return pd.DataFrame(columns=["player_id", "player_name", "position", "season", "pro_team_id"])
    df = pd.concat(parts, ignore_index=True).dropna(subset=["player_id", "player_name"])
    df["player_id"] = df["player_id"].astype(int)
    return df


def player_index(tables: dict) -> pd.DataFrame:
    """player_id, player_name, position, season, pro_team_id: one row per player, his latest
    season's name, position and NFL team (seasons from the pool, player cards and lineups)."""
    df = name_rows(tables)
    if not len(df):
        return pd.DataFrame(columns=["player_id", "player_name", "position", "season", "pro_team_id"])
    team = df.dropna(subset=["pro_team_id"]).sort_values("season", kind="stable").groupby("player_id")["pro_team_id"].last() \
        if "pro_team_id" in df else pd.Series(dtype=float)
    latest = df.sort_values("season", kind="stable").groupby("player_id").last()[["player_name", "position", "season"]]
    latest["pro_team_id"] = team.reindex(latest.index)
    return latest.reset_index()


def image_urls(cfg: dict, tables: dict, index: pd.DataFrame) -> dict[int, str]:
    """player id -> image URL from the league's provider."""
    provider = (cfg.get("league") or {}).get("provider")
    if provider != "espn":
        return {}
    from engine.providers.espn import headshot_url

    pt = tables.get("pro_teams")
    abbrev = {} if pt is None else {int(i): a for i, a in zip(pt["pro_team_id"], pt["abbrev"])}
    out = {}
    for r in index.itertuples():
        team = None if pd.isna(r.pro_team_id) else abbrev.get(int(r.pro_team_id))
        url = headshot_url(int(r.player_id), r.position, team)
        if url:
            out[int(r.player_id)] = url
    return out


def spellings(ctx) -> list[str]:
    """"Name|POS" keys the published data uses: the live file's keys and the names in the
    league's rankings snapshots (frozen, so they keep the spelling of their day)."""
    keys = list((site_json(ctx, LIVE) or {}).keys())
    for snap in R.load_folder(R.league_dir(ctx), R.SNAPSHOT_DIR).values():
        for t in snap.get("teams") or []:
            keys += [f"{p['player']}|{p['pos']}" for p in t.get("draft_picks") or [] if p.get("player")]
        keys += [f"{p['player']}|{p['pos']}" for p in snap.get("undrafted_players") or []]
        keys += [f"{p['player']}|{p['pos']}" for v in (snap.get("lineups") or {}).values()
                 for p in v.get("starters") or [] if p.get("player")]
        keys += list(snap.get("player_season_totals") or {})
    return keys


def legacy_view(index: pd.DataFrame, urls: dict[int, str], extra_keys: list[str],
                names: pd.DataFrame | None = None) -> tuple[dict, list[str]]:
    """("Name|POS" -> URL, keys of `extra_keys` no player matches). Other spellings match any name and
    position a table ever listed for the player (`names`, default `index`). D/ST left out (module doc)."""
    rows = index[(index["position"] != "D/ST") & index["player_id"].isin(urls)].sort_values(["season", "player_id"])
    variants = (names if names is not None else index)
    variants = variants[variants["player_id"].isin(rows["player_id"])].sort_values(["season", "player_id"],
                                                                                    kind="stable")
    by_norm: dict = {}
    by_name: dict = {}
    out = {}
    for r in variants.itertuples():    # oldest first: the latest season wins a shared name
        by_norm[(norm(r.player_name), r.position)] = int(r.player_id)
        by_name.setdefault(norm(r.player_name), set()).add(int(r.player_id))
    for r in rows.itertuples():
        out[f"{r.player_name}|{r.position}"] = urls[int(r.player_id)]
    unmatched = []
    for key in dict.fromkeys(extra_keys):
        if key in out or "|" not in key:
            continue
        name, pos = key.rsplit("|", 1)
        if pos == "D/ST":
            continue
        pid = by_norm.get((norm(name), pos))
        if pid is None and len(by_name.get(norm(name), ())) == 1:   # listed at another position, one player
            pid = next(iter(by_name[norm(name)]))
        if pid is None:
            unmatched.append(key)
        else:
            out[key] = urls[pid]
    return dict(sorted(out.items())), unmatched


class HeadshotsPublisher:
    name = "headshots"
    pages = {"managers": None, "champions": None, "weekly-rankings": None}

    def _build(self, ctx):
        index = player_index(ctx.tables)
        urls = image_urls(ctx.cfg, ctx.tables, index)
        return index, urls

    def outputs(self, ctx) -> list[Output]:
        index, urls = self._build(ctx)
        if not urls:
            return []
        view, _ = legacy_view(index, urls, spellings(ctx), name_rows(ctx.tables))
        model = {"provider": ctx.cfg["league"]["provider"],
                 "players": {str(k): v for k, v in sorted(urls.items())}}
        return [Output("data/v1/headshots.json", model, SCHEMA, VERSION), Output(LIVE, view)]

    def verify(self, ctx) -> list:
        """Stage A: the URLs change by design (ESPN instead of NFL.com), so the check is coverage:
        every player the published file has a picture for still has one under the same key."""
        index, urls = self._build(ctx)
        gold = ctx.golden.get("player_headshots")
        if not urls or gold is None:
            return []
        names = name_rows(ctx.tables)
        view, _ = legacy_view(index, urls, list(gold), names)
        known_names = {norm(n) for n in names["player_name"]}
        c = Comparison("legacy view data/player_headshots.json keys vs published (every pictured player keeps a "
                       "picture)", len(gold), len(view))
        missing = [k for k in gold if k not in view]
        absent = [k for k in missing if norm(k.rsplit("|", 1)[0]) not in known_names]
        if absent:
            c.known["player not in the league's data under that name (a nickname or a player ESPN no longer lists)"] = \
                len(absent)
        bad = [k for k in missing if k not in absent]
        c.missing = len(bad)
        c.examples = bad[:4]
        live = site_json(ctx, LIVE) or {}
        espn = sum(1 for k in gold if k in view)
        return [c, f"INFO  headshots: {len(urls)} players with an ESPN image (data/v1/headshots.json); the legacy "
                   f"view has {len(view)} keys (published {len(gold)}), {espn} of the published keys now point at ESPN "
                   f"(were NFL.com), {len(absent)} published keys match no player"
                   + (f"; live file {len(live)} keys" if live and len(live) != len(gold) else "")]

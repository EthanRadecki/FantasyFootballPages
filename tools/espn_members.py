"""Print every ESPN member (manager) id in the league, by season.

Run locally, not in CI; it needs your ESPN cookies. Paste the printed ids into
leagues/preach/league.yaml. Printed ids are hashed (see member_key).

    pip install espn-api
    python tools/espn_members.py --league 9954376 --first 2020 --last 2026 --auth path/to/espn_auth.json

Credentials are read from --auth (JSON with espn_s2 and swid keys, any case)
or from the ESPN_S2 and SWID environment variables. Nothing is written to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict


def member_key(member_id: str) -> str:
    """Stable public key for a provider member id. Must match engine.identity.member_key."""
    return "m_" + hashlib.sha256(member_id.strip("{}").lower().encode()).hexdigest()[:12]


def load_auth(path: str | None) -> tuple[str, str]:
    if path:
        with open(path, encoding="utf-8") as f:
            raw = {k.lower(): v for k, v in json.load(f).items()}
        return raw["espn_s2"], raw["swid"]
    s2, swid = os.environ.get("ESPN_S2"), os.environ.get("SWID")
    if not (s2 and swid):
        sys.exit("No credentials: pass --auth or set ESPN_S2 and SWID.")
    return s2, swid


def owners_of(team) -> list[tuple[str, str]]:
    """Return (member_id, name) pairs. Handles old and new espn_api versions."""
    owners = getattr(team, "owners", None)
    if owners:
        pairs = []
        for o in owners:
            if isinstance(o, dict):
                name = f"{o.get('firstName', '')} {o.get('lastName', '')}".strip() or o.get("displayName", "?")
                pairs.append((o.get("id", "?"), name))
            else:
                pairs.append(("?", str(o)))
        return pairs
    return [("?", str(getattr(team, "owner", "?")))]


def main() -> int:
    from espn_api.football import League

    p = argparse.ArgumentParser()
    p.add_argument("--league", type=int, required=True)
    p.add_argument("--first", type=int, required=True)
    p.add_argument("--last", type=int, required=True)
    p.add_argument("--auth")
    args = p.parse_args()
    s2, swid = load_auth(args.auth)

    members: dict[str, dict] = defaultdict(lambda: {"names": set(), "seasons": []})
    for season in range(args.first, args.last + 1):
        try:
            league = League(league_id=args.league, year=season, espn_s2=s2, swid=swid)
        except Exception as exc:  # noqa: BLE001  report and keep going
            print(f"{season}: could not load ({exc})")
            continue
        for team in league.teams:
            for mid, name in owners_of(team):
                members[mid]["names"].add(name)
                members[mid]["seasons"].append(season)

    print(f"\n{len(members)} member(s) found. Paste the id values into league.yaml.")
    print("Ids are hashed: a member id doubles as that person's SWID cookie, so raw ids never go in the repo.\n")
    for mid, info in sorted(members.items(), key=lambda kv: sorted(kv[1]["names"])[0]):
        names = " / ".join(sorted(info["names"]))
        seasons = sorted(set(info["seasons"]))
        span = f"{seasons[0]}-{seasons[-1]}" if len(seasons) > 1 else str(seasons[0])
        print(f"  {names:<28} id: {member_key(mid)}   seasons: {span} ({len(seasons)})")
    if "?" in members:
        print("\nSome ids came back as '?': upgrade espn-api (pip install -U espn-api) and rerun.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

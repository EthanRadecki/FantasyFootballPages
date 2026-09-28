"""Stable, non-sensitive identifiers for league members.

ESPN member ids double as each person's SWID cookie, so raw ids are never
stored in config or published data. Every provider id is hashed to a short
public key on ingest, and config refers to managers by that key.
"""

from __future__ import annotations

import hashlib


def member_key(member_id: str) -> str:
    """Return the public key for a provider member id, e.g. 'm_3fa91c07be21'.

    Normalizes braces and case so '{ABC-...}' and 'abc-...' map to the same key.
    tools/espn_members.py keeps a copy of this function; the two must match.
    """
    return "m_" + hashlib.sha256(member_id.strip("{}").lower().encode()).hexdigest()[:12]

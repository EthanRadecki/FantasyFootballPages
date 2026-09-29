"""League-specific corrections to what ESPN recorded.

Some leagues have facts ESPN got wrong and can no longer fix, such as an
offline draft entered in the wrong order, or a pick trade made during the draft
that ESPN never recorded. Corrections live in league.yaml under `corrections`,
are applied right after normalize, and keep ESPN's original value in an
`espn_*` column so every change stays traceable.
"""

from __future__ import annotations

import pandas as pd

from engine.config import slugify


def snake_slot(round_no: int, round_pick: int, teams: int) -> int:
    """Draft slot (1..teams) that makes a given pick in a snake draft."""
    return round_pick if round_no % 2 == 1 else teams + 1 - round_pick


def snake_round_pick(round_no: int, slot: int, teams: int) -> int:
    """Pick number within the round for a draft slot in a snake draft."""
    return slot if round_no % 2 == 1 else teams + 1 - slot


def _keep_espn(picks: pd.DataFrame, col: str) -> None:
    if f"espn_{col}" not in picks:
        picks[f"espn_{col}"] = picks[col]


def apply_draft_order(picks: pd.DataFrame, season: int, order_keys: list[str]) -> pd.DataFrame:
    """ESPN has the right players on the right managers, but the pick numbers
    come from the wrong draft order. Renumber each manager's picks from their
    true slot (order_keys[0] is slot 1)."""
    picks = picks.copy()
    for col in ("overall_pick", "round_pick"):
        _keep_espn(picks, col)
    mask = picks["season"] == season
    teams = len(order_keys)
    slot_of = {k: i + 1 for i, k in enumerate(order_keys)}
    rounds = picks.loc[mask, "round"].astype(int)
    slots = picks.loc[mask, "manager_key"].map(slot_of)
    if slots.isna().any():
        raise ValueError(f"draft_order {season}: managers with picks missing from the order")
    round_pick = [snake_round_pick(r, int(s), teams) for r, s in zip(rounds, slots)]
    picks.loc[mask, "round_pick"] = round_pick
    picks.loc[mask, "overall_pick"] = [(r - 1) * teams + p for r, p in zip(rounds, round_pick)]
    return picks


def apply_pick_owners(picks: pd.DataFrame, season: int, owners: dict[int, str]) -> pd.DataFrame:
    """Picks traded during the draft that ESPN still credits to the original
    owner: set who actually made each listed pick (by overall pick number)."""
    picks = picks.copy()
    _keep_espn(picks, "manager_key")
    for overall, key in owners.items():
        mask = (picks["season"] == season) & (picks["espn_overall_pick"].fillna(picks["overall_pick"]) == int(overall)) \
            if "espn_overall_pick" in picks else (picks["season"] == season) & (picks["overall_pick"] == int(overall))
        if mask.sum() != 1:
            raise ValueError(f"draft_pick_owners {season}: pick {overall} not found")
        picks.loc[mask, "manager_key"] = key
    return picks


def add_draft_slots(picks: pd.DataFrame) -> pd.DataFrame:
    """draft_slot: the slot a manager drafted from (their round 1 pick)."""
    slots = (picks[picks["round"] == 1][["season", "manager_key", "round_pick"]]
             .rename(columns={"round_pick": "draft_slot"}))
    return picks.drop(columns="draft_slot", errors="ignore").merge(slots, on=["season", "manager_key"], how="left")


def apply_corrections(tables: dict[str, pd.DataFrame], cfg: dict) -> dict[str, pd.DataFrame]:
    corrections = cfg.get("corrections") or {}
    slug_to_key = {slugify(m["name"]): m["id"] for m in cfg.get("managers") or []}
    picks = tables["draft_picks"]
    for season, order in (corrections.get("draft_order") or {}).items():
        picks = apply_draft_order(picks, int(season), [slug_to_key[s] for s in order])
    for season, owners in (corrections.get("draft_pick_owners") or {}).items():
        picks = apply_pick_owners(picks, int(season), {int(k): slug_to_key[v] for k, v in owners.items()})
    tables["draft_picks"] = add_draft_slots(picks)
    return tables

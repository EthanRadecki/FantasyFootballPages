"""Player stints: what a player produced for the manager who acquired him.

A stint starts in the week a manager acquires a player and covers every later
week of that season in which that manager rostered him (bench and IR included).
Weeks excluded from decision analysis (consolation games, forfeited lineups)
are removed from the lineups before they reach this module.

- The weeks need not be consecutive: a player dropped and later re-added by
  the same manager keeps counting (league decision, same as legacy).
- Realized value counts only weeks the player was started, so bench and IR
  weeks are excluded. The legacy pipeline counted IR weeks as started;
  ir_counts_as_started=True reproduces that for verification.
"""

from __future__ import annotations

import pandas as pd

BENCH = "BE"
IR = "IR"


def stints(acquisitions: pd.DataFrame, z_lineups: pd.DataFrame, all_lineups: pd.DataFrame | None = None,
           ir_counts_as_started: bool = False) -> pd.DataFrame:
    """One row per acquisition.

    acquisitions: season, manager_key, player_id, start_week (plus any other
        columns, carried through)
    z_lineups: lineups with weighted_z (see weeks.with_z), decision weeks only
    all_lineups: lineups used only to label the player's position in the stint
        (legacy took it before removing forfeits); defaults to z_lineups

    Adds position, weeks_rostered, total_z, realized_z.
    """
    keys = ["season", "manager_key", "player_id"]
    acq = acquisitions.reset_index(drop=True).copy()
    acq["_row"] = acq.index

    rows = acq[keys + ["start_week", "_row"]].merge(
        z_lineups[keys + ["week", "slot", "weighted_z"]], on=keys)
    rows = rows[rows["week"] >= rows["start_week"]]
    not_started = {BENCH} if ir_counts_as_started else {BENCH, IR}
    started = ~rows["slot"].isin(not_started)
    agg = pd.DataFrame({
        "weeks_rostered": rows.groupby("_row").size(),
        "total_z": rows.groupby("_row")["weighted_z"].sum(),
        "realized_z": rows["weighted_z"].where(started).groupby(rows["_row"]).sum(),
    })

    label = all_lineups if all_lineups is not None else z_lineups
    pos = acq[keys + ["start_week", "_row"]].merge(label[keys + ["week", "position"]], on=keys)
    pos = pos[pos["week"] >= pos["start_week"]].sort_values(["_row", "week"], kind="stable")
    first_pos = pos.drop_duplicates("_row").set_index("_row")["position"]

    out = acq.join(agg, on="_row").join(first_pos.rename("position"), on="_row")
    out["weeks_rostered"] = out["weeks_rostered"].fillna(0).astype(int)
    out["total_z"] = out["total_z"].fillna(0.0)
    out["realized_z"] = out["realized_z"].fillna(0.0)
    return out.drop(columns="_row")

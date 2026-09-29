"""Which ESPN transaction rows are real roster moves.

The canonical `transactions` table keeps everything ESPN logged. This module
is the single definition of the subset that actually changed a roster, used by
every analysis of adds, drops, waivers, and trades.

The rule is verified against the legacy transactions file (engine/legacy.py).
"""

from __future__ import annotations

import pandas as pd

# Transaction types that move players between rosters.
MOVE_TYPES = {"DRAFT", "FREEAGENT", "WAIVER", "ROSTER", "TRADE_ACCEPT"}


def executed_moves(tx: pd.DataFrame) -> pd.DataFrame:
    """Rows that actually changed a roster.

    - League-feed rows count only with status EXECUTED. That excludes failed,
      cancelled, and pending waiver bids, and TRADE_ACCEPT rows with no status
      (accepted trades that never went through).
    - Player-card rows describe a player's actual history; they count unless
      they carry a non-EXECUTED status.
    """
    status = tx["status"]
    from_card = tx["source"].eq("playercard") if "source" in tx else False
    executed = status.eq("EXECUTED") | (from_card & status.isna())
    return tx[tx["type"].isin(MOVE_TYPES) & executed]

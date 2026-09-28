"""
Detect trade-and-immediate-reversal pairs in trades_mapped.csv.

Some trades in this league get made as a joke or in anger and are undone
shortly after (sometimes same day, sometimes ~1 day later) once the league
calls for a reversal. These pairs should never count as real trades in
Trade Analysis -- they never had any actual season impact.

A pair is detected when one Transaction_ID's full set of (Player, From, To)
moves is the exact mirror image of another Transaction_ID's moves.

Output: trades_mapped_clean.csv -- same schema as trades_mapped.csv, with
all rows belonging to a confirmed reversal pair removed, plus a
reversal_pairs_log.csv audit trail of what was excluded and why.
"""
import pandas as pd
from datetime import datetime, timezone

IN_PATH = "/mnt/user-data/uploads/trades_mapped.csv"
OUT_TRADES = "/mnt/user-data/outputs/trades_mapped_clean.csv"
OUT_LOG = "/mnt/user-data/outputs/reversal_pairs_log.csv"


def sig(sub):
    return frozenset(zip(sub["Player"], sub["From_Manager"], sub["To_Manager"]))


def reverse_sig(s):
    return frozenset((p, to, frm) for (p, frm, to) in s)


def find_reversal_pairs(df):
    trades = (
        df.groupby("Transaction_ID")
        .agg(
            Season=("Season", "first"),
            Scoring_Period=("Scoring_Period", "first"),
            Proposed_Date=("Proposed_Date_Unix_ms", "first"),
        )
        .reset_index()
    )
    sig_map = df.groupby("Transaction_ID").apply(sig)
    trades["sig"] = trades["Transaction_ID"].map(sig_map)
    trades["rev_sig"] = trades["sig"].apply(reverse_sig)

    rows = trades[
        ["Transaction_ID", "sig", "rev_sig", "Proposed_Date", "Season", "Scoring_Period"]
    ].values.tolist()

    pairs = []
    n = len(rows)
    for i in range(n):
        for j in range(i + 1, n):
            # only match within the same season to avoid spurious cross-season matches
            if rows[i][4] != rows[j][4]:
                continue
            if rows[i][1] == rows[j][2]:
                ta, tb = rows[i][0], rows[j][0]
                tsa, tsb = rows[i][3], rows[j][3]
                if tsa > tsb:
                    ta, tb, tsa, tsb = tb, ta, tsb, tsa
                pairs.append(
                    {
                        "Season": rows[i][4],
                        "Scoring_Period": rows[i][5],
                        "Transaction_ID_Original": ta,
                        "Transaction_ID_Reversal": tb,
                        "Original_Timestamp": tsa,
                        "Reversal_Timestamp": tsb,
                        "Gap_Minutes": round((tsb - tsa) / 1000 / 60, 1),
                    }
                )
    return pd.DataFrame(pairs)


def main():
    df = pd.read_csv(IN_PATH)
    pairs = find_reversal_pairs(df)

    excluded_ids = set(pairs["Transaction_ID_Original"]) | set(
        pairs["Transaction_ID_Reversal"]
    )

    print(f"Total trade transactions: {df['Transaction_ID'].nunique()}")
    print(f"Reversal pairs found: {len(pairs)}")
    print(f"Transactions excluded: {len(excluded_ids)}")
    print(
        f"Real trades remaining: {df['Transaction_ID'].nunique() - len(excluded_ids)}"
    )

    clean = df[~df["Transaction_ID"].isin(excluded_ids)].copy()

    pairs["Original_Date"] = pairs["Original_Timestamp"].apply(
        lambda ts: datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d %I:%M %p UTC"
        )
    )
    pairs["Reversal_Date"] = pairs["Reversal_Timestamp"].apply(
        lambda ts: datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%d %I:%M %p UTC"
        )
    )

    clean.to_csv(OUT_TRADES, index=False)
    pairs.to_csv(OUT_LOG, index=False)
    print(f"\nWrote: {OUT_TRADES}")
    print(f"Wrote: {OUT_LOG}")


if __name__ == "__main__":
    main()

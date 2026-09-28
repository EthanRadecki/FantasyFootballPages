import pandas as pd
import numpy as np
import json

# =============================================================================
# generate_fingerprints.py
# Computes 7 draft fingerprint dimensions per manager per season + career
# Output: fingerprints.json
# =============================================================================

EXCLUDE = {"Thomas Sullivan", "William Serafin"}
SKILL   = {"RB", "WR", "QB", "TE"}
SEASONS = [2020, 2021, 2022, 2023, 2024, 2025]

draft   = pd.read_csv("draft_history_all_positions.csv")
surplus = pd.read_csv("draft_surplus.csv")

# Clean up
draft   = draft[~draft["manager"].isin(EXCLUDE)].copy()
surplus = surplus[~surplus["manager"].isin(EXCLUDE)].copy()

# ── Dimension functions ───────────────────────────────────────────────────────

def early_pos_pct(df, pos):
    """% of rounds 1-3 skill picks going to a given position."""
    early = df[(df["round"] <= 3) & (df["position"].isin(SKILL))]
    if len(early) == 0:
        return 0.0
    return round(len(early[early["position"] == pos]) / len(early) * 100, 1)

def position_timing(df, pos):
    """Average round manager first drafts a position. Lower = earlier."""
    picks = df[df["position"] == pos]
    if len(picks) == 0:
        return None
    # Per season, take first pick of that position
    first_per_season = picks.groupby("season")["round"].min()
    return round(first_per_season.mean(), 2)

def skill_diversity(df):
    """
    Inverted Herfindahl concentration index across skill positions.
    Higher score = more evenly spread across RB/WR/QB/TE.
    Returns 0-100.
    """
    skill_picks = df[df["position"].isin(SKILL)]
    if len(skill_picks) == 0:
        return 50.0
    shares = skill_picks["position"].value_counts(normalize=True)
    # Fill missing positions with 0
    for p in SKILL:
        if p not in shares:
            shares[p] = 0.0
    hhi = (shares ** 2).sum()
    # HHI range: 0.25 (perfectly even 4 positions) to 1.0 (all one position)
    # Invert and normalize to 0-100
    diversity = round((1 - hhi) / (1 - 0.25) * 100, 1)
    return diversity

def kdst_patience(df, league_avg_k, league_avg_dst):
    """
    How much later than league average a manager takes their first K and DST.
    Positive = more patient (waits longer), negative = reaches early.
    We combine K and DST patience into one score, normalized.
    """
    scores = []
    for pos, league_avg in [("K", league_avg_k), ("DST", league_avg_dst)]:
        # handle both D/ST and DST spellings
        pos_picks = df[df["position"].isin([pos, "D/ST"])] if pos == "DST" else df[df["position"] == pos]
        if len(pos_picks) == 0:
            continue
        first_per_season = pos_picks.groupby("season")["round"].min()
        mgr_avg = first_per_season.mean()
        scores.append(mgr_avg - league_avg)  # positive = waited longer
    if len(scores) == 0:
        return 0.0
    return round(np.mean(scores), 2)

def avg_surplus(surplus_df):
    """Average surplus per pick, skill positions with 8+ games (or injury zeroed)."""
    scored = surplus_df[
        (surplus_df["position"].isin(SKILL)) &
        ((surplus_df["games_played"] >= 8) | (surplus_df["injury_zeroed"] == 1))
    ]
    if len(scored) == 0:
        return 0.0
    return round(scored["surplus"].mean(), 3)

# ── League-level averages for K and DST timing ───────────────────────────────
def league_first_pick_avg(df, pos):
    """League average round for first pick of a position per season."""
    if pos == "DST":
        picks = draft[draft["position"].isin(["D/ST", "DST"])]
    else:
        picks = draft[draft["position"] == pos]
    picks = picks[~picks["manager"].isin(EXCLUDE)]
    first = picks.groupby(["season", "manager"])["round"].min().reset_index()
    return first["round"].mean()

league_avg_k   = league_first_pick_avg(draft, "K")
league_avg_dst = league_first_pick_avg(draft, "DST")

print(f"League avg first K round:   {league_avg_k:.2f}")
print(f"League avg first DST round: {league_avg_dst:.2f}")

# ── Compute raw dimensions per manager per season + career ────────────────────
managers = [m for m in draft["manager"].unique() if m not in EXCLUDE]
managers = sorted(managers)

raw = {}  # raw[manager][season_or_"career"] = {dim: value}

for mgr in managers:
    raw[mgr] = {}

    for season in SEASONS:
        d = draft[(draft["manager"] == mgr) & (draft["season"] == season)]
        s = surplus[(surplus["manager"] == mgr) & (surplus["season"] == season)]
        if len(d) == 0:
            continue

        raw[mgr][season] = {
            "early_rb":    early_pos_pct(d, "RB"),
            "early_wr":    early_pos_pct(d, "WR"),
            "qb_timing":   position_timing(d, "QB"),
            "te_timing":   position_timing(d, "TE"),
            "diversity":   skill_diversity(d),
            "kdst_patience": kdst_patience(d, league_avg_k, league_avg_dst),
            "surplus":     avg_surplus(s),
        }

    # Career
    d_all = draft[draft["manager"] == mgr]
    s_all = surplus[surplus["manager"] == mgr]
    raw[mgr]["career"] = {
        "early_rb":    early_pos_pct(d_all, "RB"),
        "early_wr":    early_pos_pct(d_all, "WR"),
        "qb_timing":   position_timing(d_all, "QB"),
        "te_timing":   position_timing(d_all, "TE"),
        "diversity":   skill_diversity(d_all),
        "kdst_patience": kdst_patience(d_all, league_avg_k, league_avg_dst),
        "surplus":     avg_surplus(s_all),
    }

# ── Normalize each dimension to 0-100 across all manager-seasons ──────────────
# Collect all values per dimension for normalization bounds
dims = ["early_rb", "early_wr", "qb_timing", "te_timing", "diversity", "kdst_patience", "surplus"]

# For timing dims (qb_timing, te_timing): lower round = better (invert)
# For kdst_patience: higher = more patient = better
# For everything else: higher = more of that trait (not inherently better/worse)

# We normalize purely for radar display -- 0 = league min, 100 = league max
# For inverted dims, we flip after normalizing

all_vals = {d: [] for d in dims}
for mgr in raw:
    for period in raw[mgr]:
        for d in dims:
            v = raw[mgr][period].get(d)
            if v is not None:
                all_vals[d].append(v)

bounds = {}
for d in dims:
    vals = [v for v in all_vals[d] if v is not None]
    bounds[d] = {"min": min(vals), "max": max(vals)}

print("\n=== Dimension Bounds ===")
for d in dims:
    print(f"  {d}: {bounds[d]['min']:.2f} - {bounds[d]['max']:.2f}")

def normalize(val, d):
    """Normalize value to 0-100. Inverts timing dims so lower round = higher score."""
    if val is None:
        return 50.0  # league middle if no data
    mn, mx = bounds[d]["min"], bounds[d]["max"]
    if mx == mn:
        return 50.0
    scaled = (val - mn) / (mx - mn) * 100
    # Invert: earlier QB/TE timing = higher score (earlier = better in draft value sense)
    if d in ["qb_timing", "te_timing"]:
        scaled = 100 - scaled
    return round(scaled, 1)

# ── Build final output ────────────────────────────────────────────────────────
output = {}

for mgr in raw:
    output[mgr] = {}
    for period in raw[mgr]:
        r = raw[mgr][period]
        output[mgr][period] = {
            "raw": r,
            "normalized": {
                "early_rb":      normalize(r.get("early_rb"),      "early_rb"),
                "early_wr":      normalize(r.get("early_wr"),      "early_wr"),
                "qb_timing":     normalize(r.get("qb_timing"),     "qb_timing"),
                "te_timing":     normalize(r.get("te_timing"),     "te_timing"),
                "diversity":     normalize(r.get("diversity"),     "diversity"),
                "kdst_patience": normalize(r.get("kdst_patience"), "kdst_patience"),
                "surplus":       normalize(r.get("surplus"),       "surplus"),
            }
        }

# ── Print readable summary ────────────────────────────────────────────────────
print("\n=== Career Fingerprints (raw) ===")
for mgr in sorted(output.keys()):
    r = output[mgr]["career"]["raw"]
    print(f"\n{mgr}:")
    print(f"  Early RB%:      {r['early_rb']:.1f}%")
    print(f"  Early WR%:      {r['early_wr']:.1f}%")
    print(f"  QB Timing (rd): {r['qb_timing']}")
    print(f"  TE Timing (rd): {r['te_timing']}")
    print(f"  Diversity:      {r['diversity']:.1f}")
    print(f"  K/DST Patience: {r['kdst_patience']:+.2f} rounds vs avg")
    print(f"  Surplus/Pick:   {r['surplus']:+.3f}")

with open("fingerprints.json", "w") as f:
    json.dump(output, f, indent=2)

print("\nfingerprints.json written")

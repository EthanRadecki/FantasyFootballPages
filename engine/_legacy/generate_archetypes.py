import pandas as pd
import numpy as np
import json
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

# =============================================================================
# generate_archetypes.py
# Clusters managers by draft fingerprint dimensions using K-means
# Merges in season outcomes to analyze which archetypes win more
# Output: archetypes.json
# =============================================================================

EXCLUDE = {"Thomas Sullivan", "William Serafin"}
SEASONS = [2020, 2021, 2022, 2023, 2024, 2025]
DIMS    = ["early_rb","early_wr","qb_timing","te_timing","diversity","kdst_patience","surplus"]
K       = 4  # number of clusters

# ── Load fingerprints ─────────────────────────────────────────────────────────
with open("fingerprints.json") as f:
    fp = json.load(f)

# ── Build per-season feature matrix ──────────────────────────────────────────
rows = []
for mgr, seasons in fp.items():
    if mgr in EXCLUDE: continue
    for season, data in seasons.items():
        if season == "career": continue
        r = data["raw"]
        if any(r[d] is None for d in DIMS): continue
        rows.append({
            "manager": mgr,
            "season":  int(season),
            **{d: r[d] for d in DIMS}
        })

df = pd.DataFrame(rows)
print(f"Feature matrix: {len(df)} manager-seasons")

# ── Normalize for clustering ──────────────────────────────────────────────────
# For timing dims, invert so higher = earlier (consistent direction)
df["qb_timing_inv"] = -df["qb_timing"]
df["te_timing_inv"] = -df["te_timing"]

CLUSTER_DIMS = ["early_rb","early_wr","qb_timing_inv","te_timing_inv",
                "diversity","kdst_patience","surplus"]

X = df[CLUSTER_DIMS].values
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# ── K-means ───────────────────────────────────────────────────────────────────
np.random.seed(42)
kmeans = KMeans(n_clusters=K, n_init=50, random_state=42)
df["cluster"] = kmeans.fit_predict(X_scaled)

# ── Cluster centers (unscaled) for interpretation ────────────────────────────
centers_scaled = kmeans.cluster_centers_
centers = scaler.inverse_transform(centers_scaled)
center_df = pd.DataFrame(centers, columns=CLUSTER_DIMS)
center_df["qb_timing"] = -center_df["qb_timing_inv"]
center_df["te_timing"] = -center_df["te_timing_inv"]

print("\n=== Cluster Centers (raw dimensions) ===")
for i in range(K):
    c = center_df.iloc[i]
    print(f"\nCluster {i}:")
    print(f"  Early RB%:      {c['early_rb']:.1f}%")
    print(f"  Early WR%:      {c['early_wr']:.1f}%")
    print(f"  QB Timing:      Rd {c['qb_timing']:.1f}")
    print(f"  TE Timing:      Rd {c['te_timing']:.1f}")
    print(f"  Diversity:      {c['diversity']:.1f}")
    print(f"  K/DST Patience: {c['kdst_patience']:+.2f}")
    print(f"  Surplus:        {c['surplus']:+.3f}")

# ── Label clusters ────────────────────────────────────────────────────────────
# We'll assign names based on the dominant trait of each cluster center
# Names will be printed so you can confirm before hardcoding
print("\n=== Cluster Membership ===")
for i in range(K):
    members = df[df["cluster"]==i][["manager","season"]].values.tolist()
    print(f"\nCluster {i} ({len(members)} seasons):")
    by_mgr = {}
    for mgr, season in members:
        if mgr not in by_mgr: by_mgr[mgr] = []
        by_mgr[mgr].append(int(season))
    for mgr, seasons_list in sorted(by_mgr.items()):
        print(f"  {mgr}: {sorted(seasons_list)}")

# ── Load outcomes ─────────────────────────────────────────────────────────────
stats = pd.read_csv("preach_manager_stats.csv")
stats = stats[~stats["Manager"].isin(EXCLUDE)].copy()

# Normalize manager names -- strip trailing period
stats["Manager"] = stats["Manager"].str.strip()

# Merge outcomes into df
df = df.merge(
    stats[["Manager","Year","W","W%","PF/G","Playoffs","Champ_App"]],
    left_on=["manager","season"],
    right_on=["Manager","Year"],
    how="left"
)

# ── Outcome analysis by cluster ───────────────────────────────────────────────
print("\n=== Outcomes by Cluster ===")
outcome_cols = ["W","W%","PF/G","Playoffs","Champ_App"]
cluster_outcomes = df.groupby("cluster")[outcome_cols].agg(["mean","std"]).round(3)
print(cluster_outcomes.to_string())

# Simpler summary
print("\n=== Summary ===")
for i in range(K):
    sub = df[df["cluster"]==i]
    n   = len(sub)
    print(f"\nCluster {i} ({n} seasons):")
    print(f"  Avg Wins:       {sub['W'].mean():.1f}")
    print(f"  Avg Win%:       {sub['W%'].mean():.3f}")
    print(f"  Avg PF/G:       {sub['PF/G'].mean():.1f}")
    print(f"  Playoff Rate:   {sub['Playoffs'].mean()*100:.1f}%")
    print(f"  Champ App Rate: {sub['Champ_App'].mean()*100:.1f}%")

# ── Build JSON output ─────────────────────────────────────────────────────────
# Per manager-season assignments
assignments = []
for _, row in df.iterrows():
    assignments.append({
        "manager": row["manager"],
        "season":  int(row["season"]),
        "cluster": int(row["cluster"]),
        "dims": {d: round(row[d], 2) for d in DIMS},
        "outcomes": {
            "wins":      int(row["W"])    if not pd.isna(row["W"])    else None,
            "win_pct":   round(float(row["W%"]),3)  if not pd.isna(row["W%"])  else None,
            "pfg":       round(float(row["PF/G"]),1) if not pd.isna(row["PF/G"]) else None,
            "playoffs":  int(row["Playoffs"]) if not pd.isna(row["Playoffs"]) else None,
            "champ_app": int(row["Champ_App"]) if not pd.isna(row["Champ_App"]) else None,
        }
    })

# Cluster summaries
cluster_summary = []
for i in range(K):
    sub = df[df["cluster"]==i]
    c   = center_df.iloc[i]
    cluster_summary.append({
        "id": i,
        "n_seasons": int(len(sub)),
        "center": {
            "early_rb":      round(float(c["early_rb"]), 1),
            "early_wr":      round(float(c["early_wr"]), 1),
            "qb_timing":     round(float(c["qb_timing"]), 1),
            "te_timing":     round(float(c["te_timing"]), 1),
            "diversity":     round(float(c["diversity"]), 1),
            "kdst_patience": round(float(c["kdst_patience"]), 2),
            "surplus":       round(float(c["surplus"]), 3),
        },
        "outcomes": {
            "avg_wins":       round(float(sub["W"].mean()), 1),
            "avg_win_pct":    round(float(sub["W%"].mean()), 3),
            "avg_pfg":        round(float(sub["PF/G"].mean()), 1),
            "playoff_rate":   round(float(sub["Playoffs"].mean()), 3),
            "champ_app_rate": round(float(sub["Champ_App"].mean()), 3),
        }
    })

output = {
    "assignments":      assignments,
    "cluster_summary":  cluster_summary,
    "k":                K,
    "dims":             DIMS,
}

with open("archetypes.json", "w") as f:
    json.dump(output, f, indent=2)

print("\narchetypes.json written")
print(f"Total manager-seasons clustered: {len(assignments)}")

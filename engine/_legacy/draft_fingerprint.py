import pandas as pd
import numpy as np
import glob
import os
import re

# ============================================================
# CONFIGURATION
# ============================================================

DRAFT_FILE = "draft_history_all_positions.csv"

# Folder containing the raw FantasyPros ADP export .txt files
# (2020_adp.txt ... 2025_adp.txt)
ADP_FOLDER = "."
ADP_GLOB_PATTERN = "*_adp.txt"

SEASONS = list(range(2020, 2026))

POSITIONS = ["RB", "WR", "QB", "TE", "K", "DST"]

EARLY_PICKS = 3
DIVERSITY_PICKS = 6
RUN_PICKS = 10


# ============================================================
# LOAD DRAFT HISTORY
# ============================================================

draft = pd.read_csv(DRAFT_FILE)

required_draft_cols = [
    "season",
    "round",
    "draft_slot",
    "overall_pick",
    "player_name",
    "position",
    "manager"
]

missing = [c for c in required_draft_cols if c not in draft.columns]

if missing:
    raise ValueError(
        f"Draft file is missing required columns: {missing}"
    )

draft["season"] = draft["season"].astype(int)
draft["round"] = pd.to_numeric(draft["round"], errors="coerce")
draft["overall_pick"] = pd.to_numeric(
    draft["overall_pick"], errors="coerce"
)

draft["position"] = (
    draft["position"]
    .astype(str)
    .str.upper()
    .str.strip()
)

# The draft file spells the defense/special-teams position "D/ST".
# Standardize it to "DST" so it lines up with every other position
# code used throughout this script (and with the ADP data below).
draft["position"] = draft["position"].replace({"D/ST": "DST"})

draft["manager"] = draft["manager"].astype(str).str.strip()
draft["player_name"] = draft["player_name"].astype(str).str.strip()


# ============================================================
# NAME-NORMALIZATION HELPERS
# ============================================================
#
# The draft file stores clean player names ("Christian McCaffrey").
# The raw ESPN ADP export bundles the team abbreviation and bye week
# into the same field ("Christian McCaffrey CAR (13)"), and D/ST
# entries are written as "<City> <Mascot> DST (bye)" (e.g.
# "San Francisco 49ers DST (11)") rather than the "<Mascot> D/ST"
# convention used by the draft file (e.g. "49ers D/ST"). These
# helpers reconcile both formats so the merge below actually lines
# up player-for-player instead of silently producing all-NaN ADP
# columns.

TEAM_ABBR_BYE_RE = re.compile(r"\s+[A-Z]{2,3}\s*\(\d+\)\s*$")
POS_LETTER_RE = re.compile(r"^([A-Z]+)")
SUFFIX_RE = re.compile(r"\b(Jr|Sr|II|III|IV|V)\.?$", re.IGNORECASE)

# Franchises whose name changed during 2020-2025 and whose nickname
# can't be recovered by just taking the last word of the string.
# (Washington used "Football Team" for the 2020-2021 seasons before
# becoming the Commanders in 2022; the draft file already labels all
# seasons "Commanders D/ST".)
DST_NAME_OVERRIDES = {
    "washington football team": "Commanders",
    "washington redskins": "Commanders",
    "washington commanders": "Commanders",
}


def clean_name(raw):
    """Strip the trailing ' TEAM (bye)' suffix FantasyPros appends."""
    return TEAM_ABBR_BYE_RE.sub("", raw).strip()


def dst_nickname(cleaned_name):
    """Reduce a D/ST's city+mascot string down to just the mascot,
    matching the draft file's '<Mascot> D/ST' convention."""
    key = cleaned_name.lower().strip()
    if key in DST_NAME_OVERRIDES:
        return DST_NAME_OVERRIDES[key]
    parts = cleaned_name.split()
    return parts[-1] if parts else cleaned_name


def normalize_for_match(name):
    """Loose key used only for joining ADP to draft history: drops
    periods and Jr/Sr/II/III/IV/V suffixes and lowercases everything,
    since the two sources aren't always consistent about those."""
    n = name.replace(".", "")
    n = SUFFIX_RE.sub("", n).strip()
    n = re.sub(r"\s+", " ", n)
    return n.lower()


# ============================================================
# LOAD ADP FILES
# ============================================================

def detect_season(filename):
    """
    Attempts to detect a 4-digit season from filename.
    Example:
        2025_adp.txt -> 2025
    """
    match = re.search(r"(20\d{2})", os.path.basename(filename))

    if match:
        return int(match.group(1))

    return None


def standardize_adp_file(filepath):
    """
    Reads a raw FantasyPros ADP export and extracts exactly:
        season, player_name, position, adp (ESPN's ADP column only)

    These exports are NOT clean CSVs. Depending on the year, the
    header is either a single tab-separated row, or each column name
    on its own line preceded by a title line (e.g. "Average Draft
    Position (ADP) - PPR Leagues 2024 | FantasyPros"). The number and
    order of the ranking-site columns after POS also varies by year
    (some years have MFL, others have Sleeper/NFL/CBS/etc.).

    Rather than trying to parse a header that shifts shape every
    year, this relies on the one thing that IS constant across every
    file: the first four tab-separated fields of every data row are
    always Rank, "Player Team (Bye)", POS, ESPN - in that order. Data
    rows are detected as the first line (and beyond) whose first
    tab-separated field is a plain integer.
    """

    season = detect_season(filepath)

    if season is None:
        raise ValueError(
            f"Could not determine season from filename: {filepath}"
        )

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        raw_lines = f.read().splitlines()

    data_start = None
    for i, line in enumerate(raw_lines):
        first_field = line.split("\t")[0].strip()
        if first_field.isdigit() and "\t" in line:
            data_start = i
            break

    if data_start is None:
        raise ValueError(
            f"Could not locate the start of data rows in {filepath}"
        )

    rows = []
    for line in raw_lines[data_start:]:
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        rows.append((fields[1], fields[2], fields[3]))

    if not rows:
        raise ValueError(f"No data rows parsed from {filepath}")

    out = pd.DataFrame(
        rows, columns=["name_team_bye", "pos_raw", "espn_raw"]
    )

    out["season"] = season
    out["player_name"] = out["name_team_bye"].apply(clean_name)

    out["position"] = out["pos_raw"].str.extract(POS_LETTER_RE)
    # FantasyPros labels defenses "DST" already, matching POSITIONS

    out["adp"] = pd.to_numeric(
        out["espn_raw"].str.strip(), errors="coerce"
    )

    # Build the join key used to match against draft history:
    # for D/ST, reduce to the mascot only; everything else, just
    # the loosely-normalized clean name.
    is_dst = out["position"] == "DST"
    out["match_key"] = out["player_name"].apply(normalize_for_match)
    out.loc[is_dst, "match_key"] = (
        out.loc[is_dst, "player_name"]
        .apply(dst_nickname)
        .apply(normalize_for_match)
    )

    return out[
        ["season", "player_name", "position", "adp", "match_key"]
    ]


adp_files = glob.glob(
    os.path.join(ADP_FOLDER, ADP_GLOB_PATTERN)
)

if not adp_files:
    raise ValueError(
        f"No ADP files matching {ADP_GLOB_PATTERN} found in {ADP_FOLDER}"
    )

adp_list = []

for filepath in adp_files:
    adp_list.append(
        standardize_adp_file(filepath)
    )

adp = pd.concat(
    adp_list,
    ignore_index=True
)

adp = adp[
    adp["season"].isin(SEASONS)
].copy()

# Drop rows with no ESPN ADP at all (ESPN didn't rank that player,
# even though another site's ADP may have contributed to that
# player's AVG column in the raw export). This is a real absence of
# ESPN ADP data, not a parsing failure.
adp = adp.dropna(subset=["player_name", "adp"])


# ============================================================
# CREATE POSITIONAL ADP ORDER
# ============================================================

adp["position_order"] = (
    adp.groupby(["season", "position"])["adp"]
    .rank(method="first", ascending=True)
)


# ============================================================
# MERGE DRAFT + ADP
# ============================================================

draft["match_key"] = draft["player_name"].apply(normalize_for_match)

is_dst_draft = draft["position"] == "DST"
draft.loc[is_dst_draft, "match_key"] = (
    draft.loc[is_dst_draft, "player_name"]
    .str.replace(" D/ST", "", regex=False)
    .apply(normalize_for_match)
)

data = draft.merge(
    adp[
        [
            "season",
            "position",
            "match_key",
            "adp",
            "position_order"
        ]
    ],
    on=["season", "position", "match_key"],
    how="left",
    suffixes=("", "_adp")
)

match_rate = data["adp"].notna().mean()
print(f"\nOverall ESPN ADP match rate: {match_rate:.1%}")
print("Match rate by position:")
print(
    data.groupby("position")["adp"]
    .apply(lambda s: s.notna().mean())
    .to_string()
)

data["adp_deviation"] = (
    data["adp"] - data["overall_pick"]
)

# Positive = reach
# Negative = value


# ============================================================
# HELPER: NORMALIZED PERCENTILE
# ============================================================

def percentile_score(value, series, reverse=False):
    """
    Returns a 0-100 percentile score.

    If reverse=True:
        smaller raw values become higher scores.

    Used for patience:
        later pick = higher patience
    """

    series = pd.Series(series).dropna()

    if len(series) < 2 or pd.isna(value):
        return np.nan

    percentile = (
        series.rank(pct=True).loc[
            series.index[series == value]
        ].mean()
        * 100
    )

    if reverse:
        percentile = 100 - percentile

    return percentile


# ============================================================
# POSITION PATIENCE
# ============================================================


# Patience weighting, by position group. Two components only:
#   - overall pick timing (percentile of overall_pick vs. the rest
#     of the league at that position, that season)
#   - position-order timing (percentile of position_order, i.e. how
#     many players at that position were already off the board)
#
# The round component from the original formula was dropped: within
# a season, round is a deterministic function of overall_pick (fixed
# team count => round = ceil(pick / n_teams)), confirmed with zero
# exceptions across all 6 seasons of draft history. Including it
# alongside overall_pick didn't add information, it just gave
# "absolute timing" 75% of the composite weight instead of 50%.
#
# QB/TE: overall_pick has real spread (CV ~0.4) and is highly
# correlated with position_order (r = 0.87-0.91) in this league's
# history, so absolute timing is treated as the dominant signal.
#
# K/DST: overall_pick is compressed into a narrow late-draft window
# (CV ~0.13-0.17) - reflecting roster mechanics (there's nowhere
# else to put these picks) more than real decision-making - and it
# diverges more from position_order (r = 0.72-0.74). Position_order
# carries most of the real behavioral signal here, so it's weighted
# far more heavily.
PATIENCE_WEIGHTS = {
    "QB":  {"pick": 0.70, "order": 0.30},
    "TE":  {"pick": 0.70, "order": 0.30},
    "K":   {"pick": 0.20, "order": 0.80},
    "DST": {"pick": 0.20, "order": 0.80},
}


def calculate_patience(manager_df, position):
    """
    Calculates a composite patience score for the first
    player selected at a given position, using position-specific
    weights (see PATIENCE_WEIGHTS above). first_{position}_round is
    still returned for reference/inspection, but no longer feeds the
    composite score.

    Higher = more patient.
    """

    weights_cfg = PATIENCE_WEIGHTS.get(
        position, {"pick": 0.50, "order": 0.50}
    )

    pos_df = manager_df[
        manager_df["position"] == position
    ].copy()

    if pos_df.empty:
        return {
            f"{position.lower()}_patience": np.nan,
            f"first_{position.lower()}_pick": np.nan,
            f"first_{position.lower()}_round": np.nan,
            f"first_{position.lower()}_order": np.nan
        }

    first = (
        pos_df
        .sort_values("overall_pick")
        .iloc[0]
    )

    season = first["season"]

    season_pos = data[
        (data["season"] == season) &
        (data["position"] == position)
    ].copy()

    # --------------------------------------------------------
    # Pick patience
    # --------------------------------------------------------

    pick_score = percentile_score(
        first["overall_pick"],
        season_pos["overall_pick"],
        reverse=False
    )

    # Later pick = greater patience.
    # percentile_score is naturally higher for later picks.

    # --------------------------------------------------------
    # Position-order patience
    # --------------------------------------------------------

    order_score = percentile_score(
        first["position_order"],
        season_pos["position_order"],
        reverse=False
    )

    # --------------------------------------------------------
    # Composite (position-specific weighting, see PATIENCE_WEIGHTS)
    # --------------------------------------------------------

    scores = [
        pick_score,
        order_score
    ]

    weights = [
        weights_cfg["pick"],
        weights_cfg["order"]
    ]

    valid = [
        (s, w)
        for s, w in zip(scores, weights)
        if not pd.isna(s)
    ]

    if valid:
        composite = (
            sum(s * w for s, w in valid)
            /
            sum(w for s, w in valid)
        )
    else:
        composite = np.nan

    return {
        f"{position.lower()}_patience": composite,
        f"first_{position.lower()}_pick": first["overall_pick"],
        f"first_{position.lower()}_round": first["round"],
        f"first_{position.lower()}_order": first["position_order"]
    }


# ============================================================
# BUILD MANAGER-SEASON METRICS
# ============================================================

manager_seasons = []

for (season, manager), df in data.groupby(
    ["season", "manager"]
):

    df = df.sort_values("overall_pick").copy()

    result = {
        "season": season,
        "manager": manager
    }

    # ========================================================
    # EARLY RB / WR
    # ========================================================

    first_three = df.head(EARLY_PICKS)

    result["early_rb_pct"] = (
        (first_three["position"] == "RB").mean() * 100
    )

    result["early_wr_pct"] = (
        (first_three["position"] == "WR").mean() * 100
    )

    # ========================================================
    # RB / WR BALANCE
    # ========================================================

    rbwr = first_three[
        first_three["position"].isin(["RB", "WR"])
    ]

    if len(rbwr) == 0:
        result["rb_wr_balance"] = np.nan

    else:
        rb_share = (
            rbwr["position"]
            .eq("RB")
            .mean()
        )

        # 1 at 50/50
        # 0 at completely one-sided
        result["rb_wr_balance"] = (
            1 - abs(rb_share - 0.5) / 0.5
        ) * 100

    # ========================================================
    # POSITIONAL DIVERSITY
    # ========================================================

    diversity_picks = df.head(DIVERSITY_PICKS)

    unique_positions = (
        diversity_picks["position"]
        .nunique()
    )

    result["positional_diversity"] = (
        unique_positions / len(POSITIONS)
    ) * 100

    # ========================================================
    # POSITIONAL CONCENTRATION
    # ========================================================

    position_counts = (
        diversity_picks["position"]
        .value_counts(normalize=True)
    )

    # Herfindahl-style concentration
    hhi = (
        position_counts ** 2
    ).sum()

    # Normalize to 0-100 where:
    # 0 = perfectly diverse
    # 100 = all same position

    min_hhi = 1 / len(POSITIONS)
    max_hhi = 1

    concentration = (
        (hhi - min_hhi)
        /
        (max_hhi - min_hhi)
    ) * 100

    result["positional_concentration"] = concentration

    # ========================================================
    # SAME-POSITION RUN RATE
    # ========================================================

    run_df = df.head(RUN_PICKS)

    positions = run_df["position"].tolist()

    if len(positions) > 1:

        same_position = [
            positions[i] == positions[i - 1]
            for i in range(1, len(positions))
        ]

        result["same_position_run_rate"] = (
            np.mean(same_position) * 100
        )

    else:
        result["same_position_run_rate"] = np.nan

    # ========================================================
    # POSITION PATIENCE
    # ========================================================

    for position in ["QB", "TE", "K", "DST"]:

        patience = calculate_patience(
            df,
            position
        )

        result.update(patience)

    # ========================================================
    # ADP METRICS
    # ========================================================

    adp_df = df.dropna(
        subset=["adp_deviation"]
    )

    if len(adp_df) > 0:

        # Average deviation
        result["avg_adp_deviation"] = (
            adp_df["adp_deviation"].mean()
        )

        # Average positive deviation
        # = average size of reaches
        reaches = adp_df[
            adp_df["adp_deviation"] > 0
        ]

        if len(reaches) > 0:
            result["reach_tendency"] = (
                reaches["adp_deviation"].mean()
            )
        else:
            result["reach_tendency"] = 0

        # Average negative deviation
        # = average size of values
        values = adp_df[
            adp_df["adp_deviation"] < 0
        ]

        if len(values) > 0:
            result["value_hunting"] = (
                abs(values["adp_deviation"].mean())
            )
        else:
            result["value_hunting"] = 0

        # Absolute deviation
        result["draft_conviction"] = (
            adp_df["adp_deviation"]
            .abs()
            .mean()
        )

        # ADP correlation
        if (
            adp_df["adp"].nunique() > 1
            and
            adp_df["overall_pick"].nunique() > 1
        ):
            result["adp_independence"] = (
                1 -
                adp_df[
                    ["adp", "overall_pick"]
                ]
                .corr()
                .iloc[0, 1]
            ) * 100

        else:
            result["adp_independence"] = np.nan

    else:

        result["avg_adp_deviation"] = np.nan
        result["reach_tendency"] = np.nan
        result["value_hunting"] = np.nan
        result["draft_conviction"] = np.nan
        result["adp_independence"] = np.nan

    # ========================================================
    # POSITION-SPECIFIC ADP DEVIATION
    # ========================================================

    for position in POSITIONS:

        pos = adp_df[
            adp_df["position"] == position
        ]

        result[
            f"{position.lower()}_adp_deviation"
        ] = (
            pos["adp_deviation"].mean()
            if len(pos) > 0
            else np.nan
        )

    manager_seasons.append(result)


manager_season_metrics = pd.DataFrame(
    manager_seasons
)


# ============================================================
# CAREER FINGERPRINT
# ============================================================

# Average the season-level fingerprints rather than
# pooling every pick together.

metric_columns = [
    c for c in manager_season_metrics.columns
    if c not in ["season", "manager"]
]

career_metrics = (
    manager_season_metrics
    .groupby("manager")[metric_columns]
    .mean()
    .reset_index()
)


# ============================================================
# YEAR-TO-YEAR ADAPTABILITY
# ============================================================

# Calculate standard deviation of each manager's strategy
# across seasons.

strategy_columns = [
    "early_rb_pct",
    "early_wr_pct",
    "qb_patience",
    "te_patience",
    "k_patience",
    "dst_patience",
    "rb_wr_balance",
    "positional_diversity",
    "positional_concentration",
    "same_position_run_rate"
]

strategy_columns = [
    c for c in strategy_columns
    if c in manager_season_metrics.columns
]

adaptability = (
    manager_season_metrics
    .groupby("manager")[strategy_columns]
    .std()
    .mean(axis=1)
    .reset_index(name="draft_adaptability")
)

career_metrics = career_metrics.merge(
    adaptability,
    on="manager",
    how="left"
)


# ============================================================
# OUTPUT
# ============================================================

manager_season_metrics.to_csv(
    "draft_fingerprint_manager_season.csv",
    index=False
)

career_metrics.to_csv(
    "draft_fingerprint_career.csv",
    index=False
)

data.to_csv(
    "draft_history_with_adp.csv",
    index=False
)


print("\nCreated:")
print("  draft_fingerprint_manager_season.csv")
print("  draft_fingerprint_career.csv")
print("  draft_history_with_adp.csv")

print("\nManager-season shape:")
print(manager_season_metrics.shape)

print("\nCareer shape:")
print(career_metrics.shape)

print("\nMetrics:")
print(
    "\n".join(
        f"  - {c}"
        for c in career_metrics.columns
    )
)

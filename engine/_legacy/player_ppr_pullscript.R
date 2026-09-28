nflreadr::.clear_cache()

# =============================================================================
# Preach Fantasy — NFL Player Stats Pull
# nflfastR | Seasons 2020-2025 | PPR Scoring
# =============================================================================
# Outputs:
#   player_stats_weekly.csv   — one row per player per game (Tier 4 analyses)
#   player_stats_season.csv   — season averages, all players incl. injury busts
#   player_stats_benchmark.csv — season averages, 10+ game players only (baselines)
# =============================================================================

library(nflfastR)
library(tidyverse)

# -----------------------------------------------------------------------------
# 1. Pull weekly offensive stats 2020-2025
# -----------------------------------------------------------------------------
cat("Pulling player stats from nflfastR...\n")

seasons <- 2020:2025

stats_raw <- load_player_stats(seasons = seasons, stat_type = "offense")

cat("Raw rows pulled:", nrow(stats_raw), "\n")

# Check what seasons are actually in the data
stats_raw %>% 
  count(season) %>% 
  print()

# -----------------------------------------------------------------------------
# 2. Filter positions and calculate PPR points
# -----------------------------------------------------------------------------
stats_weekly <- stats_raw %>%
  filter(position %in% c("RB", "WR", "TE", "QB")) %>%
  mutate(
    ppr_points = (passing_yards   * 0.04) +
      (passing_tds     * 4)    -
      (interceptions   * 2)    +
      (rushing_yards   * 0.1)  +
      (rushing_tds     * 6)    +
      (receptions      * 1)    +   # PPR point
      (receiving_yards * 0.1)  +
      (receiving_tds   * 6)    -
      (sack_fumbles_lost    * 2) -
      (rushing_fumbles_lost * 2)
  ) %>%
  select(
    player_id,
    player_name,
    position,
    season,
    week,
    ppr_points
  ) %>%
  arrange(season, week, player_name)

cat("Filtered weekly rows (RB/WR/TE/QB):", nrow(stats_weekly), "\n")

# -----------------------------------------------------------------------------
# 3. Season summary — ALL players, no games filter
#    Use for: surplus value actuals, draft outcome analysis
#    Injured players kept — they count against a manager's surplus score
# -----------------------------------------------------------------------------
stats_season <- stats_weekly %>%
  group_by(player_id, player_name, position, season) %>%
  summarise(
    games_played = n(),
    total_ppr    = round(sum(ppr_points,  na.rm = TRUE), 2),
    ppr_per_game = round(mean(ppr_points, na.rm = TRUE), 2),
    weekly_sd    = round(sd(ppr_points,   na.rm = TRUE), 2),
    .groups = "drop"
  ) %>%
  arrange(season, position, desc(ppr_per_game))

cat("Season summary rows (all players):", nrow(stats_season), "\n")

# -----------------------------------------------------------------------------
# 4. Benchmark summary — 10+ game players only
#    Use for: expected production baselines, positional scarcity map,
#             surplus value index expected values
#    Injured players excluded — we want clean comps for what a slot "should" produce
# -----------------------------------------------------------------------------
stats_benchmark <- stats_season %>%
  filter(games_played >= 10)

cat("Benchmark rows (10+ games played):", nrow(stats_benchmark), "\n")

# -----------------------------------------------------------------------------
# 5. Quick sanity check — top 5 PPR/game per position in 2024
# -----------------------------------------------------------------------------
cat("\n--- Sanity check: Top 5 PPR/game per position, 2024 ---\n")

stats_benchmark %>%
  filter(season == 2024) %>%
  group_by(position) %>%
  slice_max(ppr_per_game, n = 5) %>%
  select(player_name, position, season, games_played, ppr_per_game) %>%
  print(n = 20)

# -----------------------------------------------------------------------------
# 6. Write outputs
# -----------------------------------------------------------------------------
write_csv(stats_weekly,   "player_stats_weekly.csv")
write_csv(stats_season,   "player_stats_season.csv")
write_csv(stats_benchmark,"player_stats_benchmark.csv")

cat("\n=== Done ===\n")
cat("player_stats_weekly.csv   —", nrow(stats_weekly),    "rows\n")
cat("player_stats_season.csv   —", nrow(stats_season),    "rows\n")
cat("player_stats_benchmark.csv—", nrow(stats_benchmark), "rows\n")

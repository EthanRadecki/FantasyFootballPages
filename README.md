# Preach Fantasy

A custom stats and history site for **Preach Fantasy**, a 14-manager fantasy football league established in 2020. The site covers six seasons (2020-2025) of matchups, drafts, transactions, and league-wide analytics.

## Tech Stack

- **Frontend:** Vanilla HTML/CSS/JS, JSON as the data layer
- **Pipeline:** Python scripts build JSON from raw league exports
- **Data sources:** `weekly_rosters_bracket_only.csv`, `matchup_data.csv`, plus derived per-page JSON (e.g. `data/matchups.json`)

## Site Map

### `index.html`
Home page. All-time sortable leaderboard (W/L, win %, playoffs, championships, PF/G, luck, best/worst season), current champion banner, and a nav grid linking to every section below.

### `pages/weekly-rankings.html`
Power rankings by season and week, with season/week dropdown filters. Includes a season ranking trajectory chart and a retrospective playoff odds tracker (5,000 simulated playouts per week, regular season only).

### `pages/champions.html`
Hall of champions: a full championship timeline, championship-game score chart, and a list of every title team.

### `pages/managers.html`
Manager Profiles hub. Selecting a manager loads a full career dashboard:
- Career stats (wins, losses, win %, playoffs, championships, PF/G) with league ranks
- Best/worst head-to-head rivalries
- Season-by-season table
- Best single-week performances (filterable by position/season)
- Franchise leaders (total points, PPG, games, weeks rostered)
- Workhorse vs. Rental scatter (bubble = total points, ring color = position)
- Roster timeline (started vs. benched/IR weeks)
- Performance over time, schedule luck, head-to-head chart, scoring distribution, seasonal trends, power ranking trajectory
- Draft fingerprint radar and draft board performance heatmap

### `pages/matchups.html`
Matchup Explorer. Every regular-season and playoff game, filterable by season/phase, searchable by manager, sortable (recent, closest, biggest blowouts, etc.), with head-to-head comparison mode and infinite scroll ("Load More").

- Playoff round naming is season-aware (2020, 2021, and 2022-2025 each use different round-label schemes, since bracket structure changed).
- A small number of non-competitive games (e.g. a manager who deliberately sat their roster) are excluded from blowout/superlative calculations but remain fully visible in the explorer.

### `pages/draft-analysis.html`
Draft Analysis hub, covering:
- Playoff rate and manager-adjusted performance by draft slot
- Detailed slot-by-slot breakdown table
- Manager distribution by slot
- Hit rate by round (early/middle/late) and by position within each round
- Late-round legends (best value picks, round 8+)
- Preview of the Surplus Value Index, linking out to the full page

**Subpages:**
- **`pages/surplus-value.html`** - Career draft rankings by average surplus per pick (position-relative value vs. draft-slot opportunity cost, with round weighting), season-by-season draft grade heatmap, each manager's best/worst pick ever, and full best-picks / biggest-busts tables.
- **`pages/draft-history.html`** - Full draft board, every pick from every season, filterable by season and manager, color-coded by position.
- **`pages/draft-fingerprints.html`** - 20 drafting signals distilled to a 10-trait radar per manager, a sortable metric explorer, K-means draft archetypes (k=4) with a cluster scatter and archetype-outcome comparison, plus a methodology section (PCA, imputation, known exclusions).

### `pages/transaction-analysis.html`
Transaction Analysis hub covering every draft pick, waiver claim, drop, and trade since 2020, sourced from ESPN's transaction log.

**Subpages:**
- **`pages/lineup-efficiency.html`** - Actual vs. optimal lineup points, week by week. Covers missed wins, a career efficiency-gap leaderboard, a weekly efficiency calendar heatmap, league-wide trend by season, bench depth, depth-adjusted efficiency, and the biggest single-week lineup blunders (click a row to view the full roster).
- **`pages/waiver-value.html`** - Position-adjusted value (z-score) per pickup. Career leaderboard, contested vs. uncontested (waiver vs. free agent) splits, total value earned, "waiver upside" (positive-only value), value by week added, and the best pickups ever.
- **`pages/trade-value.html`** - Every real trade graded on four metrics (Trade Grade, Realized Gains, Fit Score, Necessity Score) combined into a QUAD composite. Includes a manager leaderboard, trade quality vs. win % scatter, an interactive trade network graph, a filterable trade explorer, most-traded players, trades by week, and a full trade table.

### `pages/extra-analytics.html`
Deep-dive analytics grab bag:
- Head-to-head matrix (all-time records, every manager vs. every manager)
- Closest games ever
- Championship Gauntlet (how hard each title run was, weighted 70/15/15 across opponent points/dominance/hot streak) plus the same methodology applied to every 3-week stretch in league history
- Conference analysis (DEM vs. REP, a fixed conference assignment since 2020)
- Schedule luck (actual vs. expected wins vs. the weekly league median)
- Schedule swap (replaying each manager's scores against every other manager's schedule)
- Seasonal analysis (which quarter of the season best predicts making the playoffs)
- Positional production (which positions actually predict winning, RB/WR strongest, K/D-ST weakest)
- Win % attribution (a 5-factor regression: draft surplus, waiver upside, missed wins, trade QUAD, schedule luck; explains 44% of season-to-season win% variance)

## Design System

- **Managers:** each of the 14 managers has a dedicated accent color, logo (`../images/logos/{LastName}.png`), and appears consistently across every page.
- **Positions:** fixed color coding throughout - QB (red), RB (green), WR (blue), TE (gold), K (grey), D/ST (dark brown).
- **Seasons:** each season (2020-2025) has its own swatch color, used consistently on season filter buttons across every page.
- **Glass-panel** styling (`.glass`) is the base container style site-wide.

## Standing Conventions

- **No em dashes anywhere on the site.** Use periods, commas, or parentheses instead.
- Superlative/blowout calculations exclude known non-competitive games (e.g. deliberately-sat rosters) while keeping those games fully visible in the UI. This is a data-integrity vs. data-visibility distinction applied consistently across the Matchup Explorer and related pages.
- Thomas Sullivan and William Serafin (both 2020-only managers) are excluded from surplus-based draft analysis, waiver value, and trade value, since no surplus join exists for that season.
- Consolation/loser-bracket weeks are excluded from most "real games" analyses (lineup efficiency, waiver value, trade value, closest games, schedule luck, win% attribution); only real bracket games count.
- Playoff round labels are season-aware: 2020 and 2021 use different schemes than 2022-2025 due to bracket-format changes.

## Data Pipeline

- **Raw data:** `weekly_rosters_bracket_only.csv` (player-level, weekly), `matchup_data.csv` (team-level, weekly)
- **Build script:** `build_matchups.py` (Python) transforms raw CSVs into page-ready JSON
- **Frontend consumes:** JSON files under `data/` (e.g. `data/matchups.json`)

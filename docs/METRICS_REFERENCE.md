# Preach Fantasy: Metrics Reference

A plain-language guide to every custom metric on the site: what it measures, how it's calculated, and why it was built the way it was. Where a metric went through a real methodology debate, that reasoning is included too, since it explains *why* the current version looks the way it does.

---

## Shared Conventions

A few rules apply across multiple pages, not just one metric:

- **Excluded managers:** Thomas Sullivan and William Serafin (2020-only participants) count in every calculation (medians, baselines, comparison pools, schedules) but are never shown: schedule and draft rows carry a `hidden` flag, ranks count visible managers only, and publishing leaves hidden rows out. Per-manager record lists (franchise leaders, best weeks, blunders) simply leave them out, since nothing there is computed across managers.
- **Consolation weeks never count, anywhere.** Only the regular season and winners-bracket playoff games matter.
- **Counted games** (records, lineups, flip rates, standings): finished regular-season games and winners-bracket games. Bye weeks are not games.
- **Bracket weeks** (trades, waivers, position production): every finished regular-season week, bye weeks included (the NFL player still played), plus the playoff weeks a team spent in the winners bracket.
- **Forfeited lineups:** a week where a manager never set a real lineup (scored 0 because nothing was started) is excluded from every calculation that measures decision quality, the same way a consolation week is. This came up directly in the trade pipeline: a forfeited week is technically still a "bracket" week, so a naive filter that only excludes consolation games can still let a forfeit's 0-point score contaminate other calculations.
- **Playoff weighting** (used in trade value calculations): Regular Season 1.0x, First Round 1.15x, Quarterfinal 1.3x, Semifinal 1.6x, Championship 2.0x. A great or terrible week matters more if it happened with the season on the line.
- **Name aliases:** `Carmine Pittelli Jr.` and `Ryan P McQuaid` are the full names used internally in some files; other pages shorten these to `Carmine Pittelli` and `Ryan McQuaid`.

---

## Trade Analysis (trade-value.html)

### QUAD (the overall trade grade)

**What it is:** a single number summarizing how good a trade was for one manager, from that manager's side. Every trade produces two (or more, for multi-team deals) QUAD scores, one per manager involved.

**Why it exists:** raw trade outcomes ("I got a good player") don't account for context: how much you gave up, whether you actually needed the player, or whether the trade fit your existing roster. QUAD combines four separate questions into one score so trades can be ranked and compared.

**How it's built:** four components, each first turned into a z-score (how many standard deviations above or below the average trade, across every trade in league history), then combined with fixed weights:

| Component | Weight | Question it answers |
|---|---|---|
| Realized Gains | 35% | Of the value each side actually *used* (started, not benched), who came out ahead? |
| Trade Grade | 30% | Overall, who came out ahead, whether the value was used or just sat on a bench? |
| Fit Score | 20% | Did this trade actually address a real roster weakness? |
| Necessity | 15% | Did the acquiring manager actually need this, or did they already have a good enough alternative? |

The weighted combination is z-scored a second time, so the final QUAD number is centered at 0 with a standard deviation of about 1. A QUAD of +1 is a solidly good trade, +2 or higher is one of the best in league history.

---

### Trade Grade & Realized Gains

**What they measure:** for each side of a trade, take the players received and the players given up. For each player, compute their **position-relative z-score** every week they were rostered: `(their points that week − average points at their position that week) / standard deviation at that position that week`, and sum it across their whole stint.

`Trade Grade = (received players' summed z-score) − (given-up players' summed z-score)`

**Realized Gains is the same idea, restricted to weeks the player was actually started** (not sitting on the bench). Trade Grade credits total value regardless of use; Realized Gains only credits value the manager actually captured.

**Why position-relative, not raw points:** a kicker who scores 12 points had a very different week than a running back who scores 12 points, since kickers and RBs have completely different scoring distributions league-wide. Z-scoring against the position's own weekly average puts every position on the same scale.

**A real methodology fix, worth knowing:** the given-up player's z-score comes from their stint with *whichever manager received them*. Meaning, historically, if that manager mismanaged them (or if a data bug counted an invalid week against them), it could inflate or deflate the *other* manager's grade for a trade they had no further control over. Two real bugs were found and fixed here:
1. A forfeited week could still count toward a traded player's stint length, artificially inflating however bad or good that stretch looked.
2. There was no way to flag a trade that was, in spirit, barely a real trade at all (see **Low-Stakes Dampener** below).

---

### Fit Score

**What it measures:** did the trade actually help a position of need, or was it just moving players around for no structural reason? Computed by comparing the manager's average z-score at the affected position(s) *before* the trade versus *after*.

**Why it exists:** a manager could "win" a trade in raw value terms while still not solving a real roster problem (e.g., trading for a third good WR when the actual need was at RB). Fit Score rewards trades that improve a position the manager was actually weak at.

---

### Necessity Score

**What it measures:** did the acquiring manager already have a comparable player sitting on their own bench, making this trade redundant? For each acquired player, the pipeline looks at what was already on the manager's bench (at a matching position) the week before the trade, and compares.

**Why it exists:** a trade for a player who wasn't meaningfully better than an existing bench option isn't really solving anything. Necessity is supposed to catch "this didn't need to be a trade."

**A real gap, partially fixed:** necessity originally only evaluated RB/WR/TE acquisitions. A trade for a kicker or D/ST always defaulted to a neutral score, regardless of whether it was actually needed. This has been extended to cover K/D-ST too. The practical effect is limited, though: most managers only roster one kicker or one D/ST at a time, so there's often no bench alternative to compare against even now. Real data: about 19% of manager-weeks carry a bench kicker, 34% carry a bench D/ST, so necessity now produces a real signal in those cases and defaults to neutral the rest of the time. Catching "there was a comparable option on *waivers*" would need weekly free-agent-pool data the pipeline doesn't currently have.

---

### Low-Stakes Dampener

**What it is:** a trade where an entire side of the exchange was nothing but a kicker or D/ST (e.g., a struggling RB traded straight-up for a kicker) has its QUAD multiplied by **0.15** for both managers involved.

**Why it exists:** this came out of a real example. A trade that, on paper, produced a solidly positive QUAD for one manager and a solidly negative one for the other, purely because a mediocre RB happened to have a worse few months than a kicker who was dropped after one game. In spirit, that trade was barely different from each manager independently working the waiver wire. It shouldn't be able to produce a QUAD that looks as meaningful as an actual trade of real assets.

**How it's detected:** *not* simply "does a K or D/ST appear anywhere in this trade." That would wrongly flatten a genuine blockbuster trade that happens to include a throwaway D/ST as one small piece of a much larger deal. Instead, it checks whether *removing* every K/D-ST player from one side of the trade leaves that side completely empty. Only then is it flagged. Checked directly against the data: 8 of 328 trade-sides get flagged this way, and zero of the actual top/bottom 10 most significant trades in league history are among them.

**Why 0.15 and not zero:** a hard zero would treat every flagged trade as identical regardless of how lopsided it actually was. 0.15 keeps a faint, proportional signal (a genuinely terrible low-stakes trade still reads as slightly worse than a mild one) without letting any of them compete with real trades for attention. Real trades in the data span roughly −3 to +4; a dampened trade now lands around ±0.1 to ±0.3.

---

### Average QUAD vs. Total QUAD

The Manager Leaderboard offers both, and they answer genuinely different questions:

- **Average QUAD**: the typical quality of this manager's trades, regardless of how many they made. A manager with 5 trades and a manager with 40 trades are compared on equal footing.
- **Total QUAD**: the sum of QUAD across every trade this manager has made. This rewards (or penalizes) *volume* as well as quality. A manager who makes many decent trades can out-total a manager who made one brilliant one.

**Checked directly:** these two rankings agree most of the time (rank correlation ≈0.94 at the career level) but genuinely diverge in specific cases. The clearest example: one manager has the single best average QUAD in the league but only ~20 trades; another has a lower average but nearly 35 trades, and comes out on top by total. Neither ranking is "more correct." They're deliberately different lenses, which is why both are shown rather than picking one.

### Trade Explorer

One node per trade (a multi-team trade is one node), with each manager's players got and given and their Trade Grade, Realized Gains, Fit, Necessity per week, and QUAD. The positions on a node are every player moved, as ESPN listed him that season. Every manager is shown, the two excluded managers included: the explorer shows what happened in a trade, and hiding a participant would misstate it. Player names are ESPN's for that season, so a player ESPN has since renamed (Will/William Fuller V) shows his current name.

---

## Waiver Value (waiver-value.html)

**What it measures:** how much value a manager has extracted from waiver-wire pickups, using the same position-relative z-score logic as trade grading. A pickup's value each week is `(their points − position average that week) / position standard deviation that week`, summed across however long they stayed rostered.

**Why position-relative:** the same reasoning as trades. A streaming D/ST scoring 10 points and a WR2 scoring 10 points represent very different levels of "good," and z-scoring against the position's own weekly average puts them on a comparable scale.

**What counts as a pickup (a waiver stint):** an executed waiver claim or free-agent add, running until the manager lets the player go (drop or trade) in a later week or later the same week, otherwise to the end of that team's season. Weeks counted are the team's real bracket weeks (regular season plus winners-bracket playoff games), bench weeks included; IR weeks are not counted (a stashed injured player is neither a hit nor a miss). Not a pickup:
- a same-week drop and re-add of a player who came from the draft or a trade (a roster shuffle, not a find)
- claiming a player your own trade dropped that same week

A drop that ESPN records inside another manager's trade (a roster move forced when the trade is accepted, undone within minutes) does not end a stint.

**Leaderboards:** points per week and z per week are weighted by weeks rostered (total points / total weeks, total z / total weeks), per career or season, position, and claim vs free agent. The best-pickups lists need a positive total z and at least 3 weeks rostered.

**Trades by Week of the Season chart:** shows two things together: how many pickups happened each week (bars) and the average value of those pickups (line). This reveals *when* good pickups tend to happen (e.g., bye-week streaming spikes, injury-driven scrambles) separately from *how good* they tend to be.

---

## Lineup Efficiency (lineup-efficiency.html)

### Efficiency Gap

**What it measures:** `Optimal Points - Actual Points` for a given week, meaning how many points were left on the bench by not starting the best possible lineup from that week's full roster. Optimal is computed respecting real slot rules (1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX, 1 D/ST, 1 K).

**Why it exists:** the simplest, most direct measure of lineup-setting decision quality. Lower is better: a manager who reliably starts their best players has a low average gap.

**What gets excluded, and why:** IR players and bye weeks are excluded (they were never real, playable alternatives). Two specific exceptions get excluded from the *average* entirely (but still count toward Missed Wins if applicable, see below):
1. **Full forfeits**: a lineup that was never set at all.
2. **Partial lineup neglect**: 2 or more mandatory starting slots left completely empty despite a real, active (non-bye) alternative sitting on the bench for at least one of them. A *single* empty slot doesn't qualify; that's normal, everyday decision-making and stays in as real signal. This threshold (1 vs. 2+) was chosen specifically because it's the real dividing line found in the actual data between "a normal lapse" and "didn't really field a lineup that week."

---

### Missed Wins

**What it measures:** a loss that would have been a win, had the manager started their optimal lineup that week.

**Missed %, a real methodology decision:** this is missed wins divided by **losses**, not by every game played. A missed win is, by definition, always a subset of losses. You can't have "would have won with a better lineup" in a game you already won. Dividing by total games instead would mix in something unrelated to decision quality: how often a manager loses in the first place. A manager who rarely loses would show a misleadingly low rate even if *every* loss was self-inflicted, simply because losses are a small slice of a large denominator. Checked directly: switching from "all games" to "losses only" meaningfully reshuffles the rankings. It's not a cosmetic difference.

---

### Bench Depth

**What it measures:** how much talent sat on a manager's bench, independent of whether it ever got played. For each bench player each week, compute `their points − average points among all *other benches league-wide* at that position that week`, then sum across the whole bench that week, then average across the season or career.

**Why this specific design, and not simpler alternatives:**
- **Baseline is other benches, not starters.** Comparing to starters would answer a different question, "how much unrealized *starter-caliber* value existed," which is what the Depth-Adjusted Efficiency metric below needs. Depth is meant to be a standalone, general measure of roster construction, so it's benchmarked against other benches instead.
- **Summed across the whole bench, not just the best player.** An earlier version used only the single best bench asset each week, but that's noisier (one lucky game dominates) and doesn't reflect overall bench quality. Summing the whole bench and using a bench-vs-bench baseline was specifically checked to *not* reward roster size: since an average bench player nets to roughly zero by construction, a deep bench full of merely-average players doesn't get punished just for having more players in it.

**What a depth score number actually means:** a score of, say, 3.99 means a manager's *entire bench, added together*, nets out to about 4 points above what a league-average bench would post in a typical week. It's not "each bench player is 4 points better than average." It's the whole bench, combined.

**Checked against two specific failure modes, and cleared both:**
1. *Is a manager's depth score secretly propped up by one repeatedly-benched star?* Checked directly: for every manager, their single most-repeated positive contributor accounts for well under 15% of their total positive value. Depth reflects broad roster construction, not one buried asset.
2. *Does depth correlate with how often a manager's games are already decided (so they can "afford" to sit good players)?* Checked directly: correlation between a manager's blowout rate and their depth score is essentially zero (−0.05). This isn't happening.

---

### Depth-Adjusted Efficiency

**What it is:** because bench depth and raw Efficiency Gap are correlated (checked directly: about 81%), a manager with a weak bench will structurally post a lower average gap, since there's simply less good stuff to miss, regardless of how sharp their actual decisions are. Depth-Adjusted Efficiency corrects for this.

**How it's calculated:** a straight line is fit through the data (each manager's depth score vs. their raw efficiency gap), producing a prediction: "given this depth score, here's the gap a typical manager would post." The adjusted number is `actual gap − predicted gap`.

**How to read it:** a negative (green) value means the manager beat what their own bench depth would predict: genuinely sharp decisions, not just a thin bench. A positive (red) value means they underperformed even what their depth predicted: worse than expected, even after accounting for how little (or how much) they had to work with.

**A concrete worked example:** a manager with a weak bench (depth score −3.66) gets a predicted gap of about 12.7 from the fitted line. Someone with that little bench talent would typically post around that gap just from having less to miss. Their actual gap was 11.4, better than even that lowered bar, so their adjusted score is negative (about −1.35): genuinely better decision-making, not just a lack of opportunity to be bad.

---

### League Trend by Season

**What it is:** the league-wide average Efficiency Gap for each season, showing whether lineup-setting has gotten sharper or sloppier over time league-wide, independent of any one manager.

---

### Biggest Lineup Blunders

**What it is:** the single worst individual weeks in league history, ranked by raw Efficiency Gap. These are the actual instances behind the aggregate leaderboard numbers, with full roster detail (who was started, who was benched, and by how much) available per entry.

---

## Schedule Luck and Schedule Swap (extra-analytics.html)

Both use finished regular-season games only. Playoff games of every tier are left out: once the field shrinks to 8, 4, then 2 teams, comparing a score with "the league" stops meaning anything. Bye weeks are not games and never count.

### Schedule Luck

**What it measures:** wins a manager got (or lost) because of who they happened to play. Each week, a score above the league median "should have" won regardless of the opponent. Luck = actual wins - expected wins, per season, summed for the career chart.

**Ties and the median:** a tie counts as half a win, and a score exactly equal to the median is half an expected win. The second case is common, not a rounding curiosity: in a week with an odd number of teams (2020, 15 teams with rotating byes), the middle team's score *is* the median. The legacy version gave that team 0 expected wins.

**Excluded managers:** Sullivan and Serafin count in every calculation (their scores set the weekly median, their games count) and are only hidden from view.

### Schedule Swap

**What it measures:** every manager's own weekly score, replayed against every other manager's real opponents and the scores those opponents put up. Each cell is "manager A wearing B's schedule"; the summary is A's average win% across all the other schedules, compared with A's real win%.

**Why win% and not wins:** schedules are not all the same length (2020 had rotating byes, so managers played 9 to 11 games), so records compare as percentages. Wins gained converts the win% difference back into wins over that season's regular-season length (13 weeks in 2020 and 2021, 14 since).

**Weeks left out of one pairing:**
1. **B played A that week.** A cannot play itself, so that week drops from "A wearing B's schedule" only. Most pairs meet once a season; rivalry pairs meet twice.
2. **A had no game that week** (a 2020 bye).
3. **A forfeited that week** (Castaldo 2024 week 14, a sat lineup scoring 0). The loss stays in his real record, but the 0 is not a performance, so it is never used as his score on someone else's schedule.

A forfeit still counts as the opponent's score: Slansky got the win against Castaldo's 0 in 2024 week 14, so every manager wearing Slansky's schedule gets that win too.

**Excluded managers:** Sullivan and Serafin count in every calculation (their schedules are worn, their games stay in everyone else's schedule, and their rows feed each average) and are only hidden from view.

---

## Manager Season Stats (index.html, managers.html)

One row per manager and season, from finished regular-season games only (no byes, no playoff games of any tier), so every team's record covers the same weeks. The live season covers the weeks finished so far. Replaces `data/preach_manager_stats.csv`, which was kept by hand.

- **Record:** wins, losses, ties, games; win% = (wins + ties / 2) / games.
- **Per game:** PF/G and PA/G; point differential = PF/G - PA/G. The Castaldo 2024 week 14 forfeit (a sat lineup, league.yaml `exclude_games`, `from: [ppg]`): Castaldo's 0 leaves his PF/G and Slansky's PA/G; Slansky's points still count for his PF/G and Castaldo's PA/G, and the result counts.
- **Dominance:** PF/G as a z-score within the season (sample standard deviation). Sullivan and Serafin count in the average.
- **PA z-score:** PA/G the same way (the legacy file called it `LR_zscore`).
- **Ranks and luck rating:** PF/G rank (1 = most scored) and PA/G rank (1 = fewest allowed) within the season, visible managers only, tied values sharing the best rank. Luck rating = PF/G rank - PA/G rank: positive when a team allowed fewer points than its scoring would suggest.
- **From ESPN:** final place, playoff seed, made the playoffs, reached and won the final, draft slot, division. Empty while the season is live. ESPN's division names changed over the years (2020 East/West, 2021-2022 West/East, 2023-2024 AFC/NFC, 2025 on Republicans/Democrats) but each division kept its ESPN id and its conference, so `division_name` is that season's name and `conference` is the stable label from `league.conference_labels` (id 0 REP, id 1 DEM), for anything that compares seasons.

**Legacy differences:** the file divided point differential by regular-season weeks played, a bye week included (2020 teams with a bye: 12 games over 13), ranked Sullivan and Serafin, and included the forfeit in PF/G. It also carried hand rounding (2021-2024), one mistyped PA (Maney 2025, 1609.20 vs 1608.20) and a few hand-entered ranks; its z-scores were computed from those typed values. The overall and weighted rank columns it had are not ported: no page reads them.

### Draft Slot Results (draft-analysis.html)

The finished seasons grouped by draft slot (tables `draft_slot_results` and `draft_slot_managers`).

- **Per slot:** seasons drafted from it, playoff rate, championship rate, mean PF/G and mean dominance of those seasons.
- **Expected dominance:** each manager's career dominance (mean over all their finished seasons), averaged over the slot's seasons. **Over/under** = dominance - expected: positive when managers did better from that slot than they usually do.
- Sullivan and Serafin count. 2020 had 15 teams, so slot 15 has one season; the page shows slots 1-14.
- **Who drafted from each slot:** every season, the live one included.

**Legacy differences:** the builder is lost. Playoff %, dominance, expected and over/under are reproduced from the manager season file. The page's Champ % and Avg PF/G contradict that file (the page puts champions in slots 1, 2 and 7; they drafted from 3, 6 and 9) and are replaced with the real values. The manager season fixes (forfeit, per-game differential) carry over, e.g. slot 3's over/under -0.43 -> -0.36.

---

## Win% Attribution (extra-analytics.html)

**What it measures:** how much of each manager's win% comes from the draft, waivers, lineups, trades, and schedule luck.

**Data:** one row per finished manager-season. Win% over counted games (regular season and winners bracket). Five factors: draft (sum of weighted draft surplus), waiver (sum of each waiver stint's total z, upside only: a bad pickup counts as 0, not a penalty), lineup (minus the missed wins), trade (sum of QUAD, 0 with no trades), luck (schedule luck).

**Model:** an ordinary least squares fit of win% (points out of 100) on the five factors. Standardized coefficients (coefficient x SD of the factor / SD of win%, both sample SDs) rank the factors. Each manager's waterfall starts at the league intercept (the prediction at league-average inputs); each step is the coefficient times how far the manager's average for that factor sits from the league average; the residual is what the five factors do not explain.

**Excluded managers:** Sullivan's and Serafin's 2020 seasons are data points in the fit and are only hidden from the waterfall.

**Forfeits:** the Castaldo 2024 week 14 forfeit counts as a missed lineup win: a better lineup from the same roster would have won.

**Legacy differences:** the legacy fit left Sullivan and Serafin out (n 83, now 85) and divided a sample SD by a population SD in the standardized coefficients.

---

## Schedule Gauntlet (extra-analytics.html)

**What it measures:** how hard a run of consecutive opponents was. The champions' cards score each title run; the hardest and easiest lists show the toughest and softest three-game stretches any manager faced.

**Window:** n consecutive games of one manager (3, or 4 for the 2020 champion's four-round run), no earlier than their 6th game. Each opponent is scored three ways, each as a z-score against the league: the points they put up in that game, their season dominance (PF/G z-score), and their surge coming in (their average over the previous 5 games minus their regular-season average). The three averages are shrunk by n / (n + 1), mapped to 0-100 with a logistic curve, and weighted 70% points, 15% dominance, 15% surge.

**Games:** finished regular-season and winners-bracket games. The Castaldo 2024 week 14 forfeit is left out for both teams, so no window runs through it. Champion runs come from the bracket (2021's first-round bye leaves a three-game run).

**Excluded managers:** Sullivan's and Serafin's games stay in (their opponents really played them), and their own windows are ranked but hidden from the lists. Legacy dropped every game they were in.

**Legacy differences:** the page's champion cards came from an earlier variant (raw dominance, older league averages), so the card scores and ranks disagreed slightly (2024 Slansky 62.1 on the card, 62.2 in the rank). The engine computes cards, ranks, and lists once. It also ranks on the unrounded score, ties sharing a rank.

---

## Head-to-Head, Closest Games, Conference Analysis (extra-analytics.html)

All from counted games (finished regular-season and winners-bracket games). The Castaldo 2024 week 14 forfeit is a real game: the loss counts in every record.

**Head-to-head:** every manager's record against every other manager.

**Closest games:** the smallest winning margins, for all counted games, the regular season, and the playoffs.

**Conference analysis:** each manager's conference is the league's label for the division ESPN put their team in (`league.conference_labels`: id 0 REP, id 1 DEM; ESPN's division names changed over the years, the ids did not). Per manager: record, PF and PA per game against the other conference. Per season: each conference's record against the other. Totals per conference: titles, title-game trips, playoff trips, wins against the other conference (regular season, playoffs), points per game. Rivalries: every pair's meetings and record, ordered by meetings, then the closest record, then the names.

**Forfeit in the averages:** under `exclude_games` (`from: [ppg]`), Castaldo's 0 leaves his PF/G and Slansky's PA/G; Slansky's points count for Slansky's PF/G and Castaldo's PA/G, and the result counts. The legacy page left the whole game out of both teams' averages.

**Points per game by conference:** over all counted games (regular season and playoffs). The legacy cards (111.9, 110.9) were typed by hand.

**Excluded managers:** games against Sullivan and Serafin count in their opponents' records and in the conference totals, and their own 2020 playoff trips count for their conferences; their rows are hidden. The legacy page dropped their games.

---

## Positional Production and the Quarterly Playoff Model (extra-analytics.html)

**Positional production:** weekly started points per position (0 when a manager started no one there), over counted games (regular season and winners bracket). The manager table shows the career average and week-to-week SD per position and career regular-season win%. The season model is an ordinary least squares fit of each manager-season's regular-season win% on its six position averages: standardized coefficients (sample SDs), p-values, R2, and each position's correlation with win%.

**Quarterly playoff model:** each manager-season's average regular-season score in weeks 1-3, 4-6, 7-9, and 10 to the end of that season's regular season, against whether they finished in the league's playoff field (division winners, then the best records up to the league's cutoff of 8, as on the D/ST page; the real brackets took all 15 teams in 2020 and 9 in 2021). A logistic regression on standardized quarter averages gives each quarter's coefficient, p-value, and odds ratio, plus AUC; each quarter's correlation with making the playoffs.

**Both:** finished seasons; Sullivan and Serafin are data points (hidden from the table); the Castaldo 2024 week 14 forfeit week leaves the point averages (the result counts in win%).

**Legacy differences:** the page's quarterly coefficients and p-values (all p = 0.000) could not be reproduced and are replaced by the correct fit; its last quarter stopped at week 13, leaving out week 14 of 14-week seasons, and it used the real brackets (every 2020 team made the playoffs).

---

## Projected Strength of Schedule (weekly rankings)

**What it measures:** how hard each manager's remaining regular-season schedule looks, from ESPN's weekly projections. Rest of season only: the weeks still to play, from the first week without a final result (no week number to bump by hand).

**Each team's projected total for a week:** the best projected lineup the team could set that week from its whole roster, IR included, filled into the league's starting slots (fixed slots first, then flex). A player on bye or ruled out has no projection or a zero one and is never picked, so an injured player counts again from the week ESPN projects him back. If no one on the roster can fill a slot with a positive projection, the slot takes the best projected available player (free agent or waivers) at that position that week, which sizes itself to the league: in a deep league the best available player is weaker.

**The numbers:**
- **Own projected average:** the manager's own weekly totals, averaged.
- **Opponent projected average (SOS):** the scheduled opponents' weekly totals, averaged. Higher is harder.
- **SOS rank:** 1 is the hardest remaining schedule (ties broken on the unrounded average).

**Limits:** rosters and availability are a snapshot from the latest pull. Pickups, drops, and trades after that are not known, and every pull refreshes the numbers.

**Replaced method:** the first version used each team's current starters, swapped a bench player in for a starter on bye or projected at zero, and used a fixed number per position when no bench player fit. It missed benched or injured players returning later in the season, and its week 1 to 3 values used an early draft of the league schedule rather than the final one.

---

## Playoff Odds (weekly rankings)

**What it measures:** each manager's chance of making the playoffs, as the league stood before that week was played. The rest of the regular season is simulated 50,000 times; the odds are the share of simulations in which the manager qualifies.

**Scoring model:** each team's weekly score is drawn from a normal distribution.
- **Mean, results side:** points scored so far, pulled toward the league average: (games x own average + 3 x league average) / (games + 3). One or two big weeks early do not dominate.
- **Mean, forward-looking side (live season, current week):** the team's projected total for each remaining week (its best projected lineup, from the SOS module), blended in with weight 3 / (games + 3). Early in the season the projections lead; as games accumulate, real results take over. Before any games, projections alone.
- **Spread:** the team's score variance so far, pulled toward the league's the same way.
- A forfeit (a sat lineup scoring 0) keeps its loss but is not a scoring sample.

**Who qualifies (from the league, nothing hardcoded):** the playoff spots are `analysis.playoff_odds.cutoff` in league.yaml (Preach: 8), else ESPN's playoff team count. When the league has divisions, each division's best team (wins, then points) qualifies, and the remaining spots go to the best other teams by wins, then points for. Season length comes from each season's settings.

**Which weeks:** every finished week is computed from real results only, so every past week reproduces exactly. Week 1 of a finished season (no games yet) is a flat cutoff / teams for everyone. Only the live season's current week uses projections. Each week has its own random seed.

**History:** 2020-2025 and the live 2026 week 3 were first built by two scripts; the engine reproduces them exactly in legacy mode. The published 2026 weeks 2 and 3 used an early draft of the schedule, so the engine's values for those weeks differ.

---

## Position Impact and Life Without Defense (position-impact.html, dst-impact.html)

**Flip rate:** remove one position's started points from both teams in every counted game and recheck the winner. A tie after removal counts as a flip (the win is gone). Net impact per manager is wins gained minus wins lost.

**Nth pick:** for draft questions, each manager's Nth pick at a position, where N is the number of starting slots that position has in the league's lineup (Preach: the 1st QB, TE, K, and D/ST; the 2nd RB and WR, since nearly everyone takes an RB1 and WR1 early regardless of philosophy). It adapts to any lineup.

**Draft vs waiver:** real-game PPG (started, not IR) of that Nth pick by the round it was taken, against the PPG of players the manager never drafted. **Draft order:** the same by league-wide order of that pick within a season. **Draft capital:** the round of the Nth pick each season (streamed when there was none). The D/ST page reads the D/ST slice of these same numbers.

**Consistency:** each player-season's coefficient of variation (standard deviation / average) over at least 4 starts with a positive average.

**Correlation:** a team's season PPG at the position, and its Nth-pick round, against regular-season win%.

**Where production comes from:** every rostered week (bench included, IR not) is credited to how the player reached that roster: inside a waiver stint is waiver/free agent; otherwise the latest trade into the team is traded; otherwise drafted. The three parts add up exactly to the manager's points at the position.

**Would the playoffs change without defense?** Per finished season: the playoff field under regular-season records with D/ST removed, using the league's real rule (league.yaml cutoff, division winners in first), versus the actual field; which real playoff games flip; and whether the champion's own run survives.

---

## Draft Board (draft-history.html)

Every pick of every season in draft order (the corrected order for 2021), with the player's name and position as ESPN listed them that season, and his PPG and games that season from the full player pool. Every position gets its PPG, kickers and defenses included, and the live season shows the season so far.

**Replaced method:** `generate_draft_board_data.py` showed PPG for skill positions only, none for the live season, and a hand-kept list of eight picks shown as 0 games (players it could not match by name); the engine matches by player id and shows their real stats.

---

## Draft Profiles (draft-fingerprints.html, managers.html)

**What it measures:** how each manager drafts, not how well: when they take each position, how far they stray from the market, and how much their approach changes from year to year.

**Data:** every pick, all positions, every manager (excluded managers count and are hidden). A season needs only its draft, so the live season is profiled once the draft is done; career covers finished seasons. ADP is the market's average draft position for that season (see ADP below).

**Draft shape** (from the first picks, by overall pick):
- **Early RB% / Early WR%:** share of the first 3 picks at RB, at WR.
- **RB/WR balance:** 100 when those RB and WR picks split evenly, 0 when all one position.
- **Positional diversity:** distinct positions in the first 6 picks, as a % of the league's positions (taken from its drafts, so a league without kickers has five).
- **Positional concentration:** how bunched those 6 picks are (Herfindahl), 0 spread evenly to 100 all one position.
- **Run rate:** % of back-to-back pairs in the first 10 picks at the same position.

**Patience** (QB, TE, K, D/ST): the manager's first pick at the position, as a percentile of every pick at that position that season, measured two ways: overall pick, and position order (how many players at the position the market ranked above him). Combined 70/30 for QB and TE; 20/80 for K and D/ST, whose picks bunch at the end of every draft so position order carries the signal. Higher means waited longer.

**ADP deviation** = ADP minus the pick number. Positive: taken before the market would have (a reach). Negative: fell to the manager (value).
- **Avg ADP deviation**, and per position.
- **Reach tendency:** average size of the reaches. **Value hunting:** average size of the values.
- **Draft conviction:** average absolute deviation, reaches and values alike.
- **ADP independence:** 100 x (1 - correlation between ADP and pick number).
Picks without an ADP (usually late kickers and defenses) are left out of these.

**Career:** the average of the manager's seasons (each season weighs the same), plus **draft adaptability**, the average across ten strategy measures (early RB/WR, the four patience scores, balance, diversity, concentration, run rate) of their season-to-season standard deviation.

**ADP:** ESPN's own ADP when `engine pull` saved it within 3 days of the league's draft; otherwise the engine's shared library of FantasyPros PPR exports (ESPN column), one per season. ESPN's API only serves a live ADP that keeps changing through the season, so it cannot be looked up later (decision 0004).

**Archetypes (draft-fingerprints.html):** each manager-season is grouped with the drafts it most resembles.
- **Missing K and D/ST ADP deviation** (late picks outside the ADP list) is filled from a straight-line fit on that position's patience over the league's finished seasons, clipped to the observed range. With fewer than 10 observed rows, the observed average is used; with none, the value stays blank. Filled values are flagged.
- **Features:** the ten radar measures, ADP deviation by position, and the ADP summary (average deviation, reach, value hunting, independence), standardized, then reduced with PCA to 10 components (about 88% of the variance for Preach). PCA damps the four ADP summary measures, which largely say the same thing.
- **Groups:** k-means with 4 groups, fit on finished seasons; the live season is placed in the nearest group once its draft is done. Leagues with fewer than 30 finished manager-seasons get no archetypes. Group numbers go by size (0 is the largest), so they stay put when the fit is rerun; the names on the page are editorial.
- **Checks shown with them:** silhouette (how separated the groups are) on the PCA components and on the raw features, a 3-group Gaussian mixture's silhouette, and bootstrap agreement (ARI over 100 resamples, seeded). Win% and PPG across groups are compared with a Kruskal-Wallis test (Preach: p = 0.23 and 0.57, no real difference).

**Radar scaling:** each radar measure is scaled 0 to 100 within its season (all managers, hidden ones included), or across careers; 50 when every manager has the same value. The page's scales are the league-wide [min, max] of every measure over finished seasons, and over careers.

**Outcomes beside each profile:** win% and PPG from the manager's season stats (counted games), and draft surplus per pick = the pick-weighted average of surplus (sum of weighted surplus / sum of round weights), career pooled over every finished-season pick. Excluded managers get their surplus like everyone else.

**Replaced method:** `draft_fingerprint.py` read the ADP exports by hand and joined them to the draft by name; the engine joins by player id (same result for every legacy pick). It numbered picks the way ESPN first recorded them; the engine uses the corrected draft order (2021), which moves K and D/ST patience for a few 2021 managers. The page's builder (lost; recovered from the page) averaged weighted surplus per pick without dividing by the weights, averaged career surplus over seasons, rounded each season's win% and PPG before averaging a career, and left the two excluded managers without surplus. `generate_fingerprints.py` built a separate 7-measure radar for managers.html; it is replaced by these profiles at publish.

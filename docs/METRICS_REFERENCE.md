# Preach Fantasy: Metrics Reference

A plain-language guide to every custom metric on the site: what it measures, how it's calculated, and why it was built the way it was. Where a metric went through a real methodology debate, that reasoning is included too, since it explains *why* the current version looks the way it does.

---

## Shared Conventions

A few rules apply across multiple pages, not just one metric:

- **Excluded managers:** Thomas Sullivan and William Serafin (2020-only participants) are excluded from all cross-season analysis.
- **Valid games only:** a game counts if its week label starts with "Week" (real regular season) OR it's flagged as a real playoff bracket game. Consolation/loser-bracket games are excluded everywhere. They don't count toward efficiency, missed wins, depth, or trade value.
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

---

## Waiver Value (waiver-value.html)

**What it measures:** how much value a manager has extracted from waiver-wire pickups, using the same position-relative z-score logic as trade grading. A pickup's value each week is `(their points − position average that week) / position standard deviation that week`, summed across however long they stayed rostered.

**Why position-relative:** the same reasoning as trades. A streaming D/ST scoring 10 points and a WR2 scoring 10 points represent very different levels of "good," and z-scoring against the position's own weekly average puts them on a comparable scale.

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

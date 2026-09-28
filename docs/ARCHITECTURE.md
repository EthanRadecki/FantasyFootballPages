# Architecture

Status: proposed, 2026-09-28. Owner: Ethan Radecki.

## 1. Goal

Turn Preach Fantasy from a hand-assembled site into a product:

1. **A clean, professional codebase** for the Preach Fantasy league that is easy to update every week and easy for anyone (including an employer) to read.
2. **A reusable engine** that builds the same site for any ESPN league from its league ID and credentials. Preach Fantasy becomes instance #1 of that engine, not a special case.

The rule that makes both possible: **nothing league-specific lives in engine or template code.** Every Preach-specific fact is data in a config file, and every hand-written piece of content lives in an editorial folder.

Scope for v1: ESPN only. Sleeper and Yahoo come later behind the same provider interface.

## 2. The three layers

| Layer | Contains | Owned by | Changes |
|---|---|---|---|
| **Engine** | Python pipeline (providers, normalization, analytics, build CLI) and the web template (pages, CSS, JS) | The product | Per release |
| **League config** | League ID, seasons, rules, manager identities, colors, logos, exclusions, enabled features | Each league | Rarely |
| **Editorial** | Weekly rankings, blurbs, screenshots, champion photos | Each league, optional | Weekly |

A league with no editorial content still gets every analytics page. Pages whose data or content is missing hide themselves instead of breaking.

## 3. Target repository layout

```
<repo>/
├── engine/                     Python package (pip-installable)
│   ├── providers/
│   │   ├── base.py             Provider interface
│   │   └── espn.py             ESPN implementation (espn_api library)
│   ├── normalize/              Raw provider data -> canonical tables
│   ├── analytics/              One module per feature, pure functions over canonical tables
│   ├── publish/                Canonical + analytics -> versioned site JSON
│   ├── cli.py                  `engine pull | build | validate | serve`
│   └── tests/
│       └── golden/             Known-good outputs from the current site, used as regression fixtures
├── web/                        Site template; contains zero league data
│   ├── index.html
│   ├── pages/
│   └── assets/
│       ├── css/                tokens.css, base.css, components.css, pages/*.css
│       └── js/
│           ├── core/           config.js, data.js (loader), managers.js, colors.js, nav.js, format.js
│           ├── components/     manager-card.js, chart-theme.js, tabs.js, lightbox.js, ...
│           └── pages/          one module per page
├── leagues/
│   └── preach/
│       ├── league.yaml         Everything league-specific (section 5)
│       ├── assets/             logos, league logos by season, champion photos
│       └── editorial/
│           └── rankings/2026/  week03.json, images/week03/*.webp
├── docs/
│   ├── ARCHITECTURE.md         This file
│   ├── INVENTORY.md            Current-state map (migration input)
│   ├── DATA_DICTIONARY.md      Canonical tables and site JSON schemas
│   ├── RUNBOOK.md              Weekly update steps
│   ├── METRICS_REFERENCE.md    Moved in from the pipeline folder
│   └── decisions/              Short numbered decision records (ADRs)
├── tools/                      Image optimizer, path checker, em dash linter
├── .github/workflows/
│   ├── validate.yml            Tests, schema checks, path checks on every push
│   └── deploy.yml              `engine build leagues/preach` -> Pages
└── dist/                       Build output (gitignored)
```

Build output is assembled, never hand-edited:

```
dist/ = web/  +  data/ (generated)  +  config.json (from league.yaml)  +  leagues/preach/assets  +  leagues/preach/editorial
```

## 4. Pipeline

```
 ESPN API
    │  extract    providers/espn.py             raw JSON cached per season in .cache/
    ▼
 raw cache
    │  normalize  normalize/                    typed, validated, name-resolved
    ▼
 canonical tables (Parquet)
    │  analyze    analytics/<feature>.py        pure functions, no I/O
    ▼
 analysis results
    │  publish    publish/                      one JSON per page, with schema_version
    ▼
 dist/data/
```

### Canonical tables

Every analysis reads only these, never provider output directly. This is the seam that makes Sleeper and Yahoo possible later.

| Table | Grain |
|---|---|
| `managers` | one row per person, keyed by provider member ID (not name) |
| `teams` | manager x season (team name, logo) |
| `matchups` | team x week, with bracket/consolation flags |
| `lineups` | team x week x player slot (started, points) |
| `transactions` | one row per add, drop, trade leg, with FAAB bid |
| `draft_picks` | season x pick |
| `player_stats` | player x week |
| `nfl_schedule` | NFL team x week, opponent |

### Incremental builds, one code path

Completed seasons are pulled once and cached; only the current season is refreshed. The same code produces career and in-season outputs. This replaces today's split between `*_2026_live.py` scripts, `update_2026.py` patching JSON in place, and full-history scripts, and matches the existing point-in-time rule of one code path for backtest and live use.

### Identity

Managers are keyed by ESPN member ID. Display names, aliases ("Carmine Pittelli Jr.", "Ryan P McQuaid"), colors, and logos hang off that ID in config. Name-string joins go away.

## 5. League config (`league.yaml`) sketch

```yaml
league:
  name: Preach Fantasy
  provider: espn
  league_id: 9954376
  first_season: 2020
  logo: assets/league/logo_{season}.png

rules:
  regular_season_weeks: { default: 14, 2020: 13, 2021: 13 }
  playoff_round_names:
    2020: ["The Round of 15", "..."]
    default: [Quarterfinals, Semifinals, Championship]
  scoring_modifications:
    dst_floor_zero: true
  faab_budget: 300

managers:
  - id: "{ESPN member id}"
    name: Ethan Radecki
    color: "#ea9a2e"
    logo: { default: assets/logos/radecki.png, 2020: assets/logos/radecki_2020.png }
  - id: "{ESPN member id}"
    name: Carmine Pittelli
    aliases: ["Carmine Pittelli Jr."]
    color: "#3a261d"

analysis:
  exclude_managers: [thomas-sullivan, william-serafin]
  exclude_games:
    - { manager: ben-castaldo, season: 2024, week: 14, from: [ppg] }

features:
  weekly_rankings: true
  champions_gallery: true

theme:
  season_colors: { 2026: "#c292b8" }
```

Credentials (`espn_s2`, `SWID`) never go in this file. Locally they come from a gitignored `.env`; in CI from repository secrets.

Colors and logos are optional for other leagues: the engine generates a palette and falls back to ESPN team logos.

## 6. Frontend

- **No JavaScript build step.** Plain ES modules served as static files, matching GitHub Pages and the current vanilla stack.
- **One source of truth per concept.** Every page reads `config.json` for managers, colors, logos, nav, and season labels, instead of hardcoding them.
- **No data inside HTML.** Pages fetch JSON from `data/`. Today eight pages carry their data inline.
- **No global-variable data files.** The six `data/*.js` files become JSON.
- **Pages declare what they need.** Each page lists the data files and features it requires; nav hides pages a league cannot support.
- **Design system in tokens.** Colors, spacing, type, and glass-panel styles live in `tokens.css` and shared components; page CSS holds only what is unique to that page.

## 7. Quality gates (CI)

On every push:

- Python tests, including golden-file tests that compare analytics output to the current site's known-good JSON.
- JSON schema validation of everything in `dist/data/`.
- Broken path check: every image and data path referenced by HTML or JS must exist in `dist/`.
- Style lint: no em dashes anywhere in the codebase; no hardcoded manager names or hex colors outside `leagues/`.

## 8. Migration strategy

The live site keeps deploying from the repo root, unchanged, until the new build reaches parity. The new structure is built alongside it in new folders (`engine/`, `web/`, `leagues/`). Cutover is one switch: GitHub Pages moves from "deploy from branch" to the Actions build. Weekly updates continue on the old layout until then.

Parity is proven, not eyeballed: generated JSON must match the current files (golden tests), and pages are checked side by side before cutover.

## 9. Phases

| # | Phase | Exit criteria |
|---|---|---|
| 0 | **Inventory** (done) | `docs/INVENTORY.md` maps every page to its data and producer |
| 1 | **Foundations** | Repo skeleton, `.gitignore` hardened, pipeline scripts committed as-is to `engine/_legacy/`, CI runs, `league.yaml` drafted |
| 2 | **Canonical data** | ESPN provider + normalize reproduce `weekly_rosters_bracket_only.csv`, `matchup_data.csv`, `transactions_clean.csv`, `draft_history.csv` exactly for 2020-2026 |
| 3 | **Analytics port** | Each feature rebuilt as a module over canonical tables; output matches golden files; legacy script deleted when its replacement passes |
| 4 | **Frontend refactor** | Core JS modules and tokens in place; every page config-driven, data fetched not inlined; zero hardcoded manager refs in `web/` |
| 5 | **Editorial + assets** | Rankings, blurbs, images moved to `leagues/preach/editorial/` with season-scoped paths; screenshots in WebP |
| 6 | **Cutover** | Pages deploys from the Actions build; old root files removed |
| 7 | **Second league** | A different ESPN league builds and renders with only a new `league.yaml` |
| 8 | **Productization** | Distribution model chosen and built; onboarding docs; landing page and demo site |

Phase 3 order, most-shared first: matchups and manager records, then lineups and stints, then the trade family, draft family, position and D/ST impact, playoff odds, surplus value.

## 10. Product considerations

These do not block the cleanup but shape it, so they are recorded now.

- **Distribution.** Two realistic models:
  - *Template repo + GitHub Actions:* the user brings their own repo, secrets, and Pages. No hosting cost, no credential custody. Hard to charge for, since the code is visible.
  - *Hosted service:* the user enters league ID and credentials on your site; you build and host `theirleague.<domain>`. Chargeable, but you store ESPN cookies and pay for hosting.
  The engine's `build` command serves either, so the choice can wait until phase 8.
- **Repo visibility.** GitHub Pages on a free plan requires a public repo. If the engine becomes a paid product, it likely moves to a private repo, with the Preach site as a public consumer of it.
- **ESPN terms.** The ESPN fantasy API is unofficial and undocumented. It can change without notice, and commercial use carries terms-of-service risk that should be checked before charging money.
- **Privacy.** A generated site publishes leaguemates' names and records. The product should support private or unlisted sites, and a public demo should use an anonymized league.
- **Data availability.** How far back ESPN returns transactions and lineups for older seasons needs to be verified per season; features depending on it must degrade gracefully.
- **League variety.** Analytics tuned on 14 teams (replacement levels, tier cutoffs, clustering k) must be parameterized and tested on other league sizes.

## 11. Open decisions

| Decision | Options | Needed by |
|---|---|---|
| Product name | TBD | Phase 8 (repo and package names use neutral placeholders until then) |
| Trade/waiver grading engine in scope? | Include as a premium feature / keep separate | Phase 3 |
| Distribution model | Template repo / hosted service | Phase 8 |
| Canonical storage | Parquet (proposed) / CSV / DuckDB | Phase 2 |

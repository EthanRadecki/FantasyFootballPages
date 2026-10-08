# Runbook

How to run the engine. Commands run from the repo root in the Codespace. ESPN cookies come from the `ESPN_S2` and `SWID` secrets.

## Build the site (phase 4)

```
python -m engine.cli update leagues/preach/league.yaml --verify
```

`update` runs the four steps below in order and stops at the first failure. Each can also be run alone:

| Step | Command | Writes |
|---|---|---|
| pull | `python -m engine.cli pull leagues/preach/league.yaml` | `.cache/espn/<league>/<season>/` raw ESPN data (finished seasons are kept, the live season refreshed) |
| normalize | `python -m engine.cli normalize leagues/preach/league.yaml` | `.cache/canonical/...` canonical tables |
| analyze | `python -m engine.cli analyze leagues/preach/league.yaml` | `.cache/analysis/...` analysis tables |
| build | `python -m engine.cli build leagues/preach/league.yaml --verify` | `dist/` (gitignored): the site, `config.json`, generated data, `build-manifest.json` |

`update --skip-pull` rebuilds from the cached ESPN data. `build --verify` checks the build: site files copied byte for byte, every page model file against its JSON schema, every asset path in `config.json`, every data and image path referenced by the pages, and (from PR A2 on) each page's Stage A check against its golden. League editorial files the build reads live in `leagues/<league>/editorial/` (from PR A5: `archetypes.yaml`, the draft archetype names; from B3: `champions.yaml`, the photos on the champions page, each shown below the season named in `after`); every page works without them.

To look at the build: `python -m http.server 8000 --directory dist`, then open the forwarded port.

From milestone M1 (docs/PUBLISH_PLAN.md section 8) the live site is this build, made by the deploy below; the old weekly process on the PC is retired, and the data files committed in `data/` are no longer updated (the build replaces every one it generates).

## Deploy (milestone M1)

GitHub Pages deploys from `.github/workflows/deploy.yml`:

- on every push to `main` (a weekly rankings commit, a code change);
- on a schedule: Tuesday and Friday at 13:23 UTC (9:23 am New York time in summer time, 8:23 in winter), after Monday Night Football and after ESPN's stat corrections; GitHub can start scheduled runs some minutes late;
- from Actions → Deploy → Run workflow, any time.

Each run does `engine update --verify` with the Actions secrets, the sanity checks against the last deploy (`deploy-stats.json`: no season loses games, the live week never goes backwards, every visible manager has its files), the change report, and the page test on the build and on the assembled site. Only when all of that passes is the build published; every published file is checked against the build (with `SITE_ROOT=legacy`, byte for byte, and every committed page, style and image is in it). When anything fails, nothing is deployed: the live site keeps the last good build and the run fails, so GitHub emails you; the first failed step's log says why.

One-time setup (done at M0): repository Settings → Secrets and variables → Actions → New repository secret, `ESPN_S2` and `SWID` (the same values as the Codespaces secrets); Settings → Pages → Build and deployment → Source: GitHub Actions.

ESPN cookies expire every few months; when the pull step reports expired cookies, update both secrets (Codespaces and Actions), then Run workflow.

What the root serves (M2, 2026-10-07): the new site (`web/`) by default. The repository variable `SITE_ROOT` picks it: `web` (or unset) for the new site, with `/next/` redirecting old preview links to the same page at the root; `legacy` for the Stage A pages on engine data, with the new site back at `/next/`. To roll the live site back: Settings → Secrets and variables → Actions → Variables → New repository variable, `SITE_ROOT` = `legacy`, then Actions → Deploy → Run workflow (about 8 minutes). Delete the variable (or set it to `web`) and run it again to go forward. The share-preview tags follow the same setting.

Undo: revert the commit that caused a problem (the push redeploys), or Run workflow once a fix is in. Each run keeps its build as the `site` artifact for 30 days and page screenshots for 14.

GitHub turns scheduled runs off in a repository with no commits for 60 days; the weekly rankings commits keep it on during the season. If the schedule stops in the offseason, Actions → Deploy → Enable workflow.

### The change report

Each deploy publishes `/changes.html` (and `changes.json`), with one line per page on the run's summary page (Actions → the Deploy run). It compares every page's data (the page models in `data/v1/`, from M2 on) in the new build with the site that was live before it, so it is the release notes of that run: values changed, filled in or left blank, records only one side has, and examples. Counted apart, not as differences: numbers that differ only in rounding, games listed with their sides the other way round, and anything in the live season, which changes every week. A difference outside the live season is a stat correction, a rule change in that commit, or something to look into.

The first M1 run compared with the PC's files and listed the reasons for each page (reviewed by Ethan, 2026-10-06). To make the report locally after a build with `--verify`:

    python tools/change_report.py --dist dist --site https://ethanradecki.github.io/FantasyFootballPages --models

(`--site .` compares with the files committed in the repo instead.)

## Page test and build provenance

`python tools/smoke_pages.py` opens every page of the site in headless Chromium (needs `pip install playwright` and `python -m playwright install chromium`) and fails on JavaScript errors or a blank page; `--screenshots DIR` saves one PNG per page, `-v` lists resources that did not load. CI runs it on every push. `build-manifest.json` in each build lists what the build was made from (`provenance`): two builds with the same digests write the same data.

## The new pages (Stage B preview)

The Stage B pages live in `web/` (the template: no league data; `tools/check_web.py` checks) and read `config.json` and `data/v1/`. Every build writes them to `dist/next/` with their data, and the deploy publishes them at `/next/` beside the live site, so a moved page can be compared with the live one side by side. Pages not moved yet link to the live page. Every page moved by B7 (#56); from M2 the deploy puts the new site at the root (see Deploy above).

To look at the preview locally after a build: `python -m http.server 8000 --directory dist`, then open `/next/`.

## The synthetic league (F1)

A generated test league that is not Preach, for checking the engine end to end on another league's shape (`engine/testing/synthetic.py`):

```
python tools/synthetic_league.py --cache .cache-synthetic
python -m engine.cli normalize leagues/synthetic/league.yaml --cache .cache-synthetic
python -m engine.cli analyze leagues/synthetic/league.yaml --cache .cache-synthetic
python -m engine.cli build leagues/synthetic/league.yaml --cache .cache-synthetic --out dist-synthetic --verify
```

CI runs the same steps on every push. Both folders are gitignored. After changing the generator's managers, rewrite its config with `python tools/synthetic_league.py --yaml leagues/synthetic/league.yaml`.

## Weekly rankings

Each ranked week is an editorial file (`leagues/<league>/editorial/rankings/<season>_weekNN.json`: ranks, synopses, blurbs, the matchup of the week) plus a frozen snapshot of its computed fields (`leagues/<league>/snapshots/rankings/`); the build adds record, PPG, streak and the rank fields (docs/METRICS_REFERENCE.md, Weekly Rankings).

Each week, in the Codespace once the week's games are final (Tuesday):

```
python -m engine.cli update leagues/preach/league.yaml --verify
python -m engine.cli rankings new leagues/preach/league.yaml --week 5
```

writes the week's snapshot (refused if one exists; `--force` regenerates it) and, when the week has no editorial file yet, a draft with last week's order to rewrite. Fill in the ranks, synopses, blurbs and the matchup of the week (`"matchup_of_the_week": {"team_a": "<manager>", "team_b": "<manager>", "blurb": "..."}`), then commit and push both files: the push deploys the week. `tools/split_rankings.py` imported the PC's weekly files before M1 and is no longer needed.

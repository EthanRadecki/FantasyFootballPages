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

`update --skip-pull` rebuilds from the cached ESPN data. `build --verify` checks the build: site files copied byte for byte, every page model file against its JSON schema, every asset path in `config.json`, every data and image path referenced by the pages, and (from PR A2 on) each page's Stage A check against its golden. League editorial files the build reads live in `leagues/<league>/editorial/` (from PR A5: `archetypes.yaml`, the draft archetype names); every page works without them.

To look at the build: `python -m http.server 8000 --directory dist`, then open the forwarded port.

Until milestone M1 (docs/PUBLISH_PLAN.md section 8) the live site is still updated the old way; `dist/` is for review only.

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

Until M1 (the PC still writes `data/rankings/<season>_weekNN.json`), import each new week into those folders and commit them with the week:

```
python tools/split_rankings.py leagues/preach/league.yaml
```

`build --verify` lists any week file in `data/rankings/` that has not been imported. From M1 on, after the weekly `engine update`:

```
python -m engine.cli rankings new leagues/preach/league.yaml --week 5
```

writes the week's snapshot (refused if one exists; `--force` regenerates it) and, when the week has no editorial file yet, a draft with last week's order to rewrite. Fill in the ranks, synopses, blurbs and the matchup of the week (`"matchup_of_the_week": {"team_a": "<manager>", "team_b": "<manager>", "blurb": "..."}`), then commit both files.

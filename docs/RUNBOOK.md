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

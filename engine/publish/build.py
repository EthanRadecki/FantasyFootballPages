"""`engine build`: assemble dist/ from the site template, config.json and the
page data publish generates, then (with --verify) check it.

    dist/ = current site files (Stage A template, copied byte for byte)
          + config.json
          + page model files (data/..., each with a meta block and a schema)
          + legacy views (today's data files, rebuilt; they overwrite the copies)
          + build-manifest.json (every file, its sha256, and where it came from)

A page is added by a Publisher (engine/publish/pages/): `outputs(ctx)` returns
the files to write; `verify(ctx)` returns Stage A checks against the goldens.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from engine.legacy import Comparison
from engine.publish import config_json
from engine.publish.site import copy_site, pages_for, sha256
from engine.publish.writer import dump, with_meta, write_text

SCHEMA_DIR = Path(__file__).parent / "schemas"
REPO_ROOT = Path(__file__).resolve().parents[2]
SIZE_LIMIT = 5_000_000      # bytes: a generated file above this fails the build check (a page loads it whole)
SIZE_NOTICE = 1_500_000     # bytes: generated files above this are listed in an INFO line
MANIFEST = "build-manifest.json"
MARKER = ".engine-build-in-progress"   # present while a build runs, so a failed build can be cleared next time


@dataclass
class Output:
    """One file to write into dist/.

    path:    relative to dist/, e.g. "data/matchups.json"
    payload: dict (a page model, or a JSON legacy view) or str (raw text: a
             legacy .js global or .csv file)
    schema:  page model schema name (engine/publish/schemas/<name>.schema.json)
             and version; None for a legacy view
    """
    path: str
    payload: Any
    schema: str | None = None
    version: int | None = None


@dataclass
class BuildContext:
    cfg: dict
    tables: dict[str, pd.DataFrame]              # canonical tables
    analysis: dict[str, pd.DataFrame]            # analysis tables (engine analyze)
    build: dict                                  # build_info()
    site_root: Path = Path(".")
    golden_dir: Path | None = Path("engine/tests/golden")   # None: a league without legacy files (no Stage A)
    legacy_site: bool = True                     # build on the current (Stage A) site and write its legacy views
    league_dir: Path | None = None               # the folder of league.yaml (editorial files live beside it)
    cache: dict = field(default_factory=dict)    # shared work between publishers (legacy-mode inputs)

    @cached_property
    def names(self) -> dict[str, str]:
        return {m["key"]: m["name"] for m in self.config["managers"]}

    @cached_property
    def config(self) -> dict:
        return config_json.build_config(self.cfg, self.tables, self.build)

    @cached_property
    def golden(self) -> dict:
        from engine.cli import load_goldens
        return load_goldens(Path(self.golden_dir))

    def memo(self, key: str, fn):
        """Compute once per build (for example the legacy-mode analysis several checks share)."""
        if key not in self.cache:
            self.cache[key] = fn()
        return self.cache[key]


class Publisher(Protocol):
    name: str

    def outputs(self, ctx: BuildContext) -> list[Output]: ...

    def verify(self, ctx: BuildContext) -> list: ...   # Comparisons (Stage A checks) and INFO strings


@dataclass
class BuildResult:
    out: Path
    copied: list[str] = field(default_factory=list)
    generated: list[Output] = field(default_factory=list)


def _prepare(out: Path) -> None:
    """Empty `out`, refusing to delete anything that is not a previous build."""
    if out.exists():
        if any(out.iterdir()) and not (out / MANIFEST).exists() and not (out / MARKER).exists():
            raise SystemExit(f"error: {out} exists and is not a build output (no {MANIFEST}); "
                             f"choose another --out or remove it yourself")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / MARKER).write_text("engine build in progress\n")


def run_build(ctx: BuildContext, out: Path, publishers: list | None = None) -> BuildResult:
    from engine.publish.pages import PUBLISHERS

    publishers = PUBLISHERS if publishers is None else publishers
    _prepare(out)
    # A league on the Stage A template gets the current site and its legacy data views; any other league
    # gets config.json and the page models only, until the Stage B pages read them (docs/PUBLISH_PLAN.md)
    copied = [str(p).replace("\\", "/") for p in copy_site(ctx.site_root, out)] if ctx.legacy_site else []
    outputs = []
    for pub in publishers:
        outputs += [o for o in pub.outputs(ctx) if o.schema or ctx.legacy_site]
    # config.json last: its page list keeps only pages whose data this build produced
    ctx.config["pages"] = pages_for(ctx.cfg.get("features"), {o.path for o in outputs})
    outputs.insert(0, Output("config.json", ctx.config, config_json.SCHEMA, config_json.SCHEMA_VERSION))
    seen: set[str] = set()
    for o in outputs:
        if o.path in seen:
            raise ValueError(f"two outputs write {o.path}")
        seen.add(o.path)
        if o.schema:
            text = dump(with_meta(o.schema, o.version, ctx.build, o.payload))
        elif isinstance(o.payload, str):
            text = o.payload
        else:
            text = dump(o.payload)
        write_text(out / o.path, text)
    generated = {o.path for o in outputs}
    from engine.publish.preview import write_preview
    preview = set(write_preview(ctx.site_root, out, ctx.legacy_site))   # the Stage B pages at next/ (web/)
    files = sorted(str(p.relative_to(out)).replace("\\", "/") for p in out.rglob("*") if p.is_file() and p.name != MARKER)
    manifest = {"build": ctx.build, "provenance": provenance(ctx), "files": [
        {"path": f, "sha256": sha256(out / f), "bytes": (out / f).stat().st_size,
         "source": "generated" if f in generated else "preview" if f in preview else "site"} for f in files]}
    write_text(out / MANIFEST, json.dumps(manifest, indent=1))
    (out / MARKER).unlink()
    return BuildResult(out, copied, outputs)


# ---------------------------------------------------------------- provenance

def _engine_version() -> str | None:
    try:
        import tomllib
        with open(REPO_ROOT / "pyproject.toml", "rb") as f:
            return tomllib.load(f).get("project", {}).get("version")
    except (OSError, ValueError):
        return None


def _git() -> dict:
    """The commit the build ran from, and whether the working tree had uncommitted changes."""
    def run(*args):
        try:
            return subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, cwd=REPO_ROOT,
                                  check=False).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    commit = os.environ.get("GITHUB_SHA") or run("rev-parse", "HEAD")
    return {"commit": commit or None, "dirty": bool(run("status", "--porcelain", "--untracked-files=no"))
            if commit else None}


def _files_digest(paths: list[Path], base: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.relative_to(base).as_posix().encode())
        h.update(b"\0")
        h.update(p.read_bytes())
    return h.hexdigest()


def tables_digest(tables: dict[str, pd.DataFrame]) -> str:
    """One sha256 over every table (its name and its rows as CSV text), so the same inputs give the
    same digest and any changed value changes it."""
    h = hashlib.sha256()
    for name in sorted(tables):
        h.update(name.encode() + b"\0")
        h.update(tables[name].to_csv(index=False, lineterminator="\n").encode())
    return h.hexdigest()


def provenance(ctx: BuildContext) -> dict:
    """What this build was made from, for build-manifest.json: the engine version and commit, the
    league's config and editorial files, and the input tables, each as a sha256. Two builds with the
    same provenance write the same data (only the build id and times differ)."""
    league = Path(ctx.league_dir) if ctx.league_dir else None
    cfg_file = league / "league.yaml" if league else None
    league_files = [p for d in ("editorial", "snapshots") if league and (league / d).is_dir()
                    for p in (league / d).rglob("*") if p.is_file()]
    return {
        "engine_version": _engine_version(), **_git(),
        "python": sys.version.split()[0], "pandas": pd.__version__,
        "league_config_sha256": sha256(cfg_file) if cfg_file and cfg_file.is_file() else None,
        "league_files_sha256": _files_digest(league_files, league) if league_files else None,
        "league_files": len(league_files),
        "canonical_tables_sha256": tables_digest(ctx.tables),
        "analysis_tables_sha256": tables_digest(ctx.analysis) if ctx.analysis else None,
    }


# ---------------------------------------------------------------- verify

def _schema(name: str) -> dict:
    with open(SCHEMA_DIR / f"{name}.schema.json", encoding="utf-8") as f:
        return json.load(f)


def check_schemas(result: BuildResult) -> Comparison:
    try:
        import jsonschema
    except ImportError:
        raise SystemExit("error: jsonschema is not installed; run `pip install jsonschema`")
    models = [o for o in result.generated if o.schema]
    c = Comparison("page model files vs their JSON schemas", len(models), len(models))
    bad = []
    for o in models:
        with open(result.out / o.path, encoding="utf-8") as f:
            doc = json.load(f)
        validator = jsonschema.Draft202012Validator(_schema(o.schema))
        errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
        if errors:
            bad.append(f"{o.path}: {errors[0].message} at /{'/'.join(map(str, errors[0].path))}"
                       + (f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""))
    c.mismatched["files"] = len(bad)
    c.examples = bad[:4]
    return c


def check_sizes(result: BuildResult) -> list:
    """Page data budget: no generated file above SIZE_LIMIT (a page downloads its file whole); an INFO
    line lists the files above SIZE_NOTICE and the page models' total."""
    sizes = {o.path: (result.out / o.path).stat().st_size for o in result.generated}
    c = Comparison(f"generated files within the {SIZE_LIMIT / 1e6:.0f} MB page data budget", len(sizes), len(sizes))
    over = sorted((p for p, b in sizes.items() if b > SIZE_LIMIT), key=lambda p: -sizes[p])
    c.mismatched["files"] = len(over)
    c.examples = [f"{p}: {sizes[p] / 1e6:.1f} MB" for p in over[:4]]
    big = sorted((p for p, b in sizes.items() if SIZE_NOTICE < b <= SIZE_LIMIT), key=lambda p: -sizes[p])
    models = sum(b for p, b in sizes.items() if p.startswith("data/v1/"))
    info = (f"INFO  page data sizes: page models {models / 1e6:.1f} MB in all; over {SIZE_NOTICE / 1e6:.1f} MB: "
            + (", ".join(f"{p} {sizes[p] / 1e6:.1f} MB" for p in big) if big else "none"))
    return [c, info]


def check_site_copy(result: BuildResult, site_root: Path) -> Comparison:
    """Every site file not replaced by a generated file is byte-identical to the repo's."""
    generated = {o.path for o in result.generated}
    kept = [f for f in result.copied if f not in generated]
    c = Comparison("site files in dist vs the repo (byte for byte)", len(kept), len(kept))
    bad = [f for f in kept if sha256(result.out / f) != sha256(site_root / f)]
    c.mismatched["files"] = len(bad)
    c.examples = bad[:4]
    return c


def check_assets(result: BuildResult, config: dict) -> Comparison:
    paths = config_json.asset_paths(config)
    c = Comparison("config.json asset paths vs dist", len(paths), len(paths))
    missing = [p for p in paths if not (result.out / p).is_file()]
    c.missing = len(missing)
    c.examples = missing[:4]
    return c


def check_paths(result: BuildResult, site_root: Path) -> Comparison:
    """tools/check_paths.py on dist: every data and image path in HTML and JS exists."""
    script = site_root / "tools" / "check_paths.py"
    proc = subprocess.run([sys.executable, str(script), str(result.out)], capture_output=True, text=True)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    c = Comparison("referenced data and image paths in dist", 1, 1)
    if proc.returncode != 0:
        c.missing = sum(1 for ln in lines if ": missing " in ln)
        c.examples = [ln for ln in lines if ": missing " in ln][:4] or lines[-2:]
    return c


def verify_build(ctx: BuildContext, result: BuildResult, publishers: list | None = None) -> list:
    from engine.publish.pages import PUBLISHERS

    publishers = PUBLISHERS if publishers is None else publishers
    checks = [check_site_copy(result, ctx.site_root), check_schemas(result), *check_sizes(result)]
    if ctx.legacy_site:
        checks += [check_assets(result, ctx.config), check_paths(result, ctx.site_root)]
    if ctx.golden_dir is None:
        return checks + ["INFO  no legacy golden files for this league (legacy.golden_dir): Stage A checks skipped"]
    for pub in publishers:
        checks += pub.verify(ctx)
    return checks

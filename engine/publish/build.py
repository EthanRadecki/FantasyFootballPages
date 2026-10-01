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

import json
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
    golden_dir: Path = Path("engine/tests/golden")
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
    copied = [str(p).replace("\\", "/") for p in copy_site(ctx.site_root, out)]
    outputs = []
    for pub in publishers:
        outputs += pub.outputs(ctx)
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
    files = sorted(str(p.relative_to(out)).replace("\\", "/") for p in out.rglob("*") if p.is_file() and p.name != MARKER)
    manifest = {"build": ctx.build, "files": [
        {"path": f, "sha256": sha256(out / f), "bytes": (out / f).stat().st_size,
         "source": "generated" if f in generated else "site"} for f in files]}
    write_text(out / MANIFEST, json.dumps(manifest, indent=1))
    (out / MARKER).unlink()
    return BuildResult(out, copied, outputs)


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
    checks = [check_site_copy(result, ctx.site_root), check_schemas(result), check_assets(result, ctx.config),
              check_paths(result, ctx.site_root)]
    for pub in publishers:
        checks += pub.verify(ctx)
    return checks

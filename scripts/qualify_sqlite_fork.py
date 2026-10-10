"""Build and qualify an unpublished SQLite-only fork from one OSS commit."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import tomlkit

ROOT = Path(__file__).resolve().parents[1]
FORK_NAME = "dblift-sqlite-fork-fixture"
FORK_CLI = "dblift-fork-fixture"
IDENTITY = (
    (
        'DEFAULT_HISTORY_TABLE = "dblift_schema_history"',
        'DEFAULT_HISTORY_TABLE = "forklift_schema_history"',
    ),
    (
        'MIGRATION_LOCK_TABLE = "dblift_migration_lock"',
        'MIGRATION_LOCK_TABLE = "forklift_migration_lock"',
    ),
    ('ENV_PREFIX = "DBLIFT_"', 'ENV_PREFIX = "FORKLIFT_"'),
    (
        'DBLIFT_SCHEMA_SNAPSHOTS_TABLE = "dblift_schema_snapshots"',
        'DBLIFT_SCHEMA_SNAPSHOTS_TABLE = "forklift_schema_snapshots"',
    ),
    (
        'DBLIFT_DATA_CHANGE_SET_TABLE = "dblift_data_change_set"',
        'DBLIFT_DATA_CHANGE_SET_TABLE = "forklift_data_change_set"',
    ),
    (
        'DBLIFT_DATA_AUDIT_TABLE = "dblift_data_audit"',
        'DBLIFT_DATA_AUDIT_TABLE = "forklift_data_audit"',
    ),
)


def replace_once(path: Path, old: str, new: str) -> None:
    """Replace exactly one expected source fragment, or refuse a drifted fork."""
    source = path.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise ValueError(
            f"Expected exactly one source match in {path.name}: {old.split(' =', 1)[0]}"
        )
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def _run(args: list[str], cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "DBLIFT_DISABLE_CLI_EXTENSIONS"):
        environment.pop(key, None)
    return subprocess.run(
        args, cwd=cwd, env=environment, text=True, capture_output=True, check=True, timeout=timeout
    )


def _transform(source: Path) -> tuple[list[str], list[str], str]:
    pyproject = source / "pyproject.toml"
    original_toml = pyproject.read_text(encoding="utf-8")
    original = tomllib.loads(original_toml)
    if original["project"]["name"] != "dblift":
        raise ValueError("Expected original dblift distribution")
    if original["project"]["scripts"] != {"dblift": "dblift.cli.main:main"}:
        raise ValueError("Expected one original dblift console script")
    providers = original["project"]["entry-points"]["dblift.providers"]
    if "sqlite" not in providers or not providers["sqlite"].startswith("dblift.db.plugins.sqlite."):
        raise ValueError("Expected SQLite provider entry point")
    original_plugins = sorted(value.split(":", 1)[0].split(".")[3] for value in providers.values())
    if len(original_plugins) != len(set(original_plugins)):
        raise ValueError("Provider entry points do not map one-to-one to plugin directories")
    removed = sorted(plugin for plugin in original_plugins if plugin != "sqlite")
    for plugin in removed:
        directory = source / "dblift" / "db" / "plugins" / plugin
        if not directory.is_dir():
            raise ValueError(f"Expected provider directory {plugin}")
    constants = source / "dblift" / "core" / "constants.py"
    old_constants = constants.read_text(encoding="utf-8")
    for old, new in IDENTITY:
        replace_once(constants, old, new)
    document = tomlkit.parse(original_toml)
    project = document["project"]
    project["name"] = FORK_NAME
    scripts = project["scripts"]
    del scripts["dblift"]
    scripts[FORK_CLI] = "dblift.cli.main:main"
    entry_points = project["entry-points"]["dblift.providers"]
    for key in list(entry_points):
        if key != "sqlite":
            del entry_points[key]
    descriptors = project["entry-points"].get("dblift.provider_descriptors")
    if descriptors is not None:
        for key in list(descriptors):
            if key != "sqlite":
                del descriptors[key]
    extras = project["optional-dependencies"]
    engine_extras = set(providers) - {"sqlite"}
    for key in list(extras):
        if key in engine_extras:
            del extras[key]
    original_all = original["project"]["optional-dependencies"]["all"]
    referenced = set()
    for requirement in original_all:
        match = re.fullmatch(r"dblift\[([^]]+)\]", requirement)
        if match is None:
            raise ValueError("Unexpected original all-extra requirement")
        referenced.update(match.group(1).split(","))
    if referenced != engine_extras:
        raise ValueError("Original all extra does not cover exactly the removable engines")
    extras["all"] = tomlkit.array()
    rewritten_toml = tomlkit.dumps(document)
    parsed = tomllib.loads(rewritten_toml)
    assert parsed["project"]["name"] == FORK_NAME
    assert parsed["project"]["scripts"] == {FORK_CLI: "dblift.cli.main:main"}
    assert parsed["project"]["entry-points"]["dblift.providers"] == {"sqlite": providers["sqlite"]}
    original_descriptors = original["project"]["entry-points"].get("dblift.provider_descriptors")
    if original_descriptors is not None:
        assert parsed["project"]["entry-points"]["dblift.provider_descriptors"] == {
            "sqlite": original_descriptors["sqlite"]
        }
    assert parsed["project"]["optional-dependencies"]["all"] == []
    assert not any(key in parsed["project"]["optional-dependencies"] for key in engine_extras)
    for key in ("dependencies", "classifiers"):
        assert parsed["project"][key] == original["project"][key]
    if "license" in original["project"]:
        assert parsed["project"]["license"] == original["project"]["license"]
    pyproject.write_text(rewritten_toml, encoding="utf-8")
    for plugin in removed:
        shutil.rmtree(source / "dblift" / "db" / "plugins" / plugin)
    if not (source / "dblift" / "core" / "premium_manifest.py").is_file():
        raise ValueError("Premium manifest disappeared from the fork")
    changes = [f"Removed provider directory dblift/db/plugins/{plugin}/\n" for plugin in removed]
    for filename, before, after in (
        ("dblift/core/constants.py", old_constants, constants.read_text(encoding="utf-8")),
        ("pyproject.toml", original_toml, rewritten_toml),
    ):
        changes.extend(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{filename}",
                tofile=f"b/{filename}",
            )
        )
    return original_plugins, removed, "".join(changes)


def qualify(
    revision: str,
    output: Path,
    corpus_probe: Path | None = None,
    corpus_fixtures: Path | None = None,
) -> int:
    result: dict[str, Any] = {"status": "fail", "revision": revision}
    try:
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("revision must be a full 40-character commit SHA")
        resolved = _run(
            ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"], ROOT
        ).stdout.strip()
        if resolved != revision:
            raise ValueError("revision does not resolve to the exact requested commit")
        if corpus_probe is not None and not corpus_probe.is_file():
            raise ValueError("corpus probe is missing")
        if corpus_fixtures is not None and (corpus_probe is None or not corpus_fixtures.is_dir()):
            raise ValueError("corpus fixtures require a probe and directory")
        status_before = _run(["git", "status", "--short"], ROOT).stdout
        archive = subprocess.run(
            ["git", "archive", "--format=tar", revision],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        with tempfile.TemporaryDirectory(prefix="dblift-sqlite-fork-") as temporary:
            work = Path(temporary)
            source = work / "source"
            source.mkdir()
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(source, filter="data")
            original_plugins, removed, diff = _transform(source)
            dist = work / "dist"
            dist.mkdir()
            _run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    "--no-deps",
                    "--wheel-dir",
                    str(dist),
                    str(source),
                ],
                work,
            )
            wheels = list(dist.glob("*.whl"))
            if len(wheels) != 1 or not wheels[0].name.startswith("dblift_sqlite_fork_fixture-"):
                raise ValueError("Fork build did not produce exactly one expected wheel")
            venv = work / "venv"
            _run([sys.executable, "-m", "venv", str(venv)], work)
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            # Installation logs can contain index credentials; never copy them into the report.
            _run([str(python), "-m", "pip", "install", str(wheels[0])], work)
            _run([str(python), "-m", "pip", "check"], work)
            probe = Path(__file__).with_name("sqlite_fork_installed_probe.py")
            if not probe.is_file():
                raise ValueError("Installed fork probe is missing")
            installed = json.loads(
                _run([str(python), "-I", str(probe), str(work), json.dumps(removed)], work).stdout
            )
            if installed["providers"] != ["sqlite"] or not installed["sqlite_migrate"]:
                raise ValueError("Installed fork did not qualify SQLite")
            if corpus_probe is not None:
                copied_corpus = work / "corpus_probe.py"
                shutil.copyfile(corpus_probe, copied_corpus)
                if corpus_fixtures is not None:
                    shutil.copytree(corpus_fixtures, work / "fixtures")
                version = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))[
                    "project"
                ]["version"]
                corpus = json.loads(
                    _run(
                        [
                            str(python),
                            "-I",
                            str(copied_corpus),
                            version,
                            json.dumps(removed),
                        ],
                        work,
                    ).stdout
                )
                if (
                    corpus["status"] != "pass"
                    or not Path(corpus["origin"]).resolve().is_relative_to(venv.resolve())
                    or Path(corpus["workdir"]).resolve() != work.resolve()
                    or corpus["history_table"] != "forklift_schema_history"
                    or not corpus["removed_imports_blocked"]
                ):
                    raise ValueError("Installed fork corpus did not qualify")
            status_after = _run(["git", "status", "--short"], ROOT).stdout
            if status_before != status_after:
                raise ValueError("Source checkout changed during fork qualification")
            output.parent.mkdir(parents=True, exist_ok=True)
            destination = output.parent / wheels[0].name
            diff_path = output.with_suffix(".diff")
            shutil.copy2(wheels[0], destination)
            diff_path.write_text(diff, encoding="utf-8")
            result.update(
                status="pass",
                wheel=str(destination.resolve()),
                wheel_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
                diff=str(diff_path.resolve()),
                diff_sha256=hashlib.sha256(diff_path.read_bytes()).hexdigest(),
                original_plugins=original_plugins,
                removed_plugins=removed,
                installed=installed,
                **({"corpus": corpus} if corpus_probe is not None else {}),
                source_status_unchanged=True,
            )
            return 0
    except (
        OSError,
        ValueError,
        KeyError,
        AssertionError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        tarfile.TarError,
    ) as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:180]}"
        return 1
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--corpus-probe", type=Path)
    parser.add_argument("--corpus-fixtures", type=Path)
    args = parser.parse_args()
    return qualify(args.revision, args.output, args.corpus_probe, args.corpus_fixtures)


if __name__ == "__main__":
    sys.exit(main())

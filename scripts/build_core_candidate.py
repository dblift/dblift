"""Build unpublished core/bundle qualification artifacts from one Git commit."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_VERSION = "999.0.0.dev1"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _change(path: Path, old: str, new: str, expected: int) -> dict:
    before = path.read_bytes()
    text = before.decode("utf-8")
    count = text.count(old)
    if count != expected:
        raise ValueError(f"{path.name}: expected {expected} version references, found {count}")
    after = text.replace(old, new).encode("utf-8")
    path.write_bytes(after)
    return {
        "old": old,
        "new": new,
        "replacements": count,
        "sha256_before": _sha256(before),
        "sha256_after": _sha256(after),
    }


def build(revision: str, output: Path) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision must be a full commit SHA")
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be empty")
    resolved = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"], cwd=ROOT, text=True
    ).strip()
    if resolved != revision:
        raise ValueError("revision does not resolve exactly")
    archived = subprocess.check_output(["git", "archive", "--format=tar", revision], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix="dblift-candidate-") as temporary:
        source = Path(temporary) / "source"
        source.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archived)) as archive:
            archive.extractall(source, filter="data")
        core_project = source / "pyproject.toml"
        bundle_project = source / "packages" / "dblift" / "pyproject.toml"
        package_init = source / "dblift" / "__init__.py"
        core = tomllib.loads(core_project.read_text(encoding="utf-8"))["project"]
        bundle = tomllib.loads(bundle_project.read_text(encoding="utf-8"))["project"]
        old_version = core["version"]
        if core["name"] != "dblift-core" or bundle["name"] != "dblift":
            raise ValueError("archive does not contain the expected distribution pair")
        if bundle["version"] != old_version:
            raise ValueError("core and bundle versions differ")
        transforms = {
            "pyproject.toml": _change(
                core_project,
                f'version = "{old_version}"',
                f'version = "{CANDIDATE_VERSION}"',
                1,
            ),
            "packages/dblift/pyproject.toml": _change(
                bundle_project,
                old_version,
                CANDIDATE_VERSION,
                2 + len(bundle.get("optional-dependencies", {})),
            ),
            "dblift/__init__.py": _change(
                package_init,
                f'__version__ = "{old_version}"',
                f'__version__ = "{CANDIDATE_VERSION}"',
                1,
            ),
        }
        output.mkdir(parents=True, exist_ok=True)
        for project in (source, source / "packages" / "dblift"):
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--sdist",
                    "--wheel",
                    "--outdir",
                    str(output),
                    str(project),
                ],
                cwd=source,
                capture_output=True,
                text=True,
                check=True,
                timeout=300,
            )
        artifacts = list(output.glob("*.whl")) + list(output.glob("*.tar.gz"))
        if len(artifacts) != 4:
            raise ValueError("candidate build did not produce four artifacts")
        manifest = {
            "revision": revision,
            "source_version": old_version,
            "candidate_version": CANDIDATE_VERSION,
            "transforms": transforms,
            "sha256": {path.name: _sha256(path.read_bytes()) for path in sorted(artifacts)},
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        build(args.revision, args.output.resolve())
    except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"Candidate build failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

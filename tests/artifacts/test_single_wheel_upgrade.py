"""A published single-wheel installation must upgrade to the release candidate."""

import hashlib
import subprocess
import sys
import tomllib
from pathlib import Path

from tests.artifacts._clean_source import archived_source

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED_4100_SHA256 = "b979a3ff5abb84a75e751c105b5c4fceb597e094e4e996f6df31f281ccd26dc5"
CANDIDATE_VERSION = "999.0.0.dev1"


def _run(*args: str, cwd: Path) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_published_wheel_upgrades_to_single_wheel_candidate(tmp_path):
    source = archived_source(ROOT, tmp_path / "source")
    project = source / "pyproject.toml"
    metadata = tomllib.loads(project.read_text(encoding="utf-8"))
    assert metadata["project"]["name"] == "dblift"
    previous_version = metadata["project"]["version"]
    project.write_text(
        project.read_text(encoding="utf-8").replace(
            f'version = "{previous_version}"', f'version = "{CANDIDATE_VERSION}"', 1
        ),
        encoding="utf-8",
    )
    package = source / "dblift" / "__init__.py"
    package.write_text(
        package.read_text(encoding="utf-8").replace(
            f'__version__ = "{previous_version}"', f'__version__ = "{CANDIDATE_VERSION}"', 1
        ),
        encoding="utf-8",
    )
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    _run(sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(wheels), str(source), cwd=tmp_path)
    candidate = next(wheels.glob("dblift-*.whl"))

    published = tmp_path / "published"
    published.mkdir()
    _run(
        sys.executable,
        "-m",
        "pip",
        "download",
        "--no-deps",
        "--only-binary=:all:",
        "-d",
        str(published),
        "dblift==4.10.0",
        cwd=tmp_path,
    )
    old_wheel = next(published.glob("dblift-4.10.0-*.whl"))
    assert hashlib.sha256(old_wheel.read_bytes()).hexdigest() == PUBLISHED_4100_SHA256

    venv = tmp_path / "venv"
    _run(sys.executable, "-m", "venv", str(venv), cwd=tmp_path)
    python = venv / "bin" / "python"
    cli = venv / "bin" / "dblift"
    _run(str(python), "-m", "pip", "install", str(old_wheel), cwd=tmp_path)
    _run(
        str(python),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(wheels),
        "--upgrade",
        "--pre",
        "dblift",
        cwd=tmp_path,
    )
    _run(str(python), "-m", "pip", "check", cwd=tmp_path)
    assert CANDIDATE_VERSION in _run(str(cli), "--version", cwd=tmp_path)
    assert "migrate" in _run(str(cli), "--help", cwd=tmp_path)
    assert candidate.is_file()

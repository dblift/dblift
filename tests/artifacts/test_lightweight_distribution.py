"""Installed distribution checks, including the qualifier's failure contract."""

import configparser
import json
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from tests.artifacts._clean_source import archived_source

ROOT = Path(__file__).resolve().parents[2]
QUALIFIER = ROOT / "scripts" / "qualify_lightweight_core.py"


def _retain(source: Path, name: str) -> None:
    directory = os.environ.get("E4_EVIDENCE_DIR")
    if directory:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def test_missing_wheel_fails_without_pass_result(tmp_path):
    output = tmp_path / "result.json"
    run = subprocess.run(
        [
            sys.executable,
            str(QUALIFIER),
            "--wheel",
            str(tmp_path / "missing.whl"),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode != 0
    result = json.loads(output.read_text())
    assert result["status"] == "fail"
    assert result["probes"] == {}


@pytest.mark.parametrize("artifact", ["wheel", "sdist"])
def test_standard_distribution_outside_checkout(tmp_path, artifact):
    """The wheel built from the sdist gets its own fresh target environment."""
    build = tmp_path / "build"
    build.mkdir()
    source = archived_source(ROOT, tmp_path / "source")
    if artifact == "wheel":
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(build),
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        subprocess.run(
            [sys.executable, "-m", "build", "--sdist", "--outdir", str(build), str(source)],
            check=True,
            capture_output=True,
            text=True,
        )
        import tarfile

        archive = next(build.glob("*.tar.gz"))
        _retain(archive, f"standard-sdist/{archive.name}")
        extracted = tmp_path / "extracted"
        extracted.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(extracted, filter="data")
        source = next(extracted.iterdir())
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(build),
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
    wheel = next(build.glob("*.whl"))
    _retain(wheel, f"standard-{artifact}/{wheel.name}")
    output = tmp_path / "result.json"
    run = subprocess.run(
        [sys.executable, str(QUALIFIER), "--wheel", str(wheel.resolve()), "--output", str(output)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr + output.read_text() if output.exists() else run.stderr
    result = json.loads(output.read_text())
    assert result["status"] == "pass"
    _retain(output, f"{artifact}-distribution.json")
    assert result["installed"]["dblift"]
    assert result["probes"]["installed"]["returncode"] == 0
    if artifact == "wheel":
        failing_probe = tmp_path / "failing_probe.py"
        failing_probe.write_text("raise SystemExit(7)\n", encoding="utf-8")
        failed_output = tmp_path / "failed.json"
        failed = subprocess.run(
            [
                sys.executable,
                str(QUALIFIER),
                "--wheel",
                str(wheel.resolve()),
                "--output",
                str(failed_output),
                "--probe",
                str(failing_probe),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert failed.returncode != 0
        failure = json.loads(failed_output.read_text())
        assert failure["status"] == "fail"
        assert failure["probes"]["installed"]["returncode"] == 7


@pytest.fixture(scope="module")
def candidate_wheel(tmp_path_factory):
    directory = tmp_path_factory.mktemp("candidate-wheel")
    source = archived_source(ROOT, directory / "source")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(directory),
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return next(directory.glob("*.whl"))


def test_wheel_contains_only_active_html_report_template(candidate_wheel):
    with zipfile.ZipFile(candidate_wheel) as archive:
        templates = {
            name
            for name in archive.namelist()
            if name.startswith("dblift/core/logger/templates/") and name.endswith(".html")
        }

    assert templates == {"dblift/core/logger/templates/report.html"}


def test_wheel_contains_provider_descriptors_and_legacy_entry_points(candidate_wheel):
    with zipfile.ZipFile(candidate_wheel) as archive:
        metadata_path = next(
            name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt")
        )
        parser = configparser.ConfigParser()
        parser.read_string(archive.read(metadata_path).decode())
        legacy = dict(parser.items("dblift.providers"))
        descriptors = dict(parser.items("dblift.provider_descriptors"))
        assert set(descriptors) == set(legacy)
        for name, reference in descriptors.items():
            module, attribute = reference.split(":")
            assert attribute == "DESCRIPTOR"
            assert module.replace(".", "/") + ".py" in archive.namelist(), name

    source_points = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["entry-points"]
    assert legacy == source_points["dblift.providers"]


def test_wrong_distribution_cannot_qualify(candidate_wheel, tmp_path):
    wrong_wheel = tmp_path / "other-1.0.0-py3-none-any.whl"
    wrong_wheel.write_bytes(candidate_wheel.read_bytes())
    output = tmp_path / "wrong.json"
    run = subprocess.run(
        [sys.executable, str(QUALIFIER), "--wheel", str(wrong_wheel), "--output", str(output)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode != 0
    assert json.loads(output.read_text())["error"] == "candidate distribution is not dblift"


def test_missing_console_script_cannot_qualify(candidate_wheel, tmp_path):
    no_script_wheel = tmp_path / candidate_wheel.name
    with (
        zipfile.ZipFile(candidate_wheel) as source,
        zipfile.ZipFile(no_script_wheel, "w") as target,
    ):
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename.endswith(".dist-info/entry_points.txt"):
                content = b"[dblift.providers]" + content.split(b"[dblift.providers]", 1)[1]
            target.writestr(item, content)
    output = tmp_path / "no-script.json"
    run = subprocess.run(
        [sys.executable, str(QUALIFIER), "--wheel", str(no_script_wheel), "--output", str(output)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode != 0
    assert json.loads(output.read_text())["status"] == "fail"


def test_malformed_probe_payload_cannot_pass(candidate_wheel, tmp_path):
    malformed_probe = tmp_path / "malformed_probe.py"
    malformed_probe.write_text('print("{\\"installed\\": null}")\n', encoding="utf-8")
    output = tmp_path / "malformed.json"
    run = subprocess.run(
        [
            sys.executable,
            str(QUALIFIER),
            "--wheel",
            str(candidate_wheel),
            "--output",
            str(output),
            "--probe",
            str(malformed_probe),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode != 0
    assert json.loads(output.read_text())["status"] == "fail"

"""Qualify a DBLift wheel in a fresh environment outside the source checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path


def checked_run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("DBLIFT_DISABLE_CLI_EXTENSIONS", None)
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=300,
        check=True,
    )


def _record(result: dict, name: str, args: list[str], cwd: Path) -> bool:
    try:
        completed = checked_run(args, cwd)
    except subprocess.CalledProcessError as exc:
        result["probes"][name] = {
            "returncode": exc.returncode,
            "stdout": exc.stdout,
            "stderr": exc.stderr,
        }
        return False
    except subprocess.TimeoutExpired:
        result["probes"][name] = {"returncode": None, "error": "timeout"}
        return False
    result["probes"][name] = {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    return True


def _candidate_version(wheel: Path) -> str | None:
    try:
        with zipfile.ZipFile(wheel) as archive:
            metadata_files = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_files) != 1:
                return None
            message = Parser().parsestr(archive.read(metadata_files[0]).decode("utf-8"))
    except (OSError, ValueError, zipfile.BadZipFile, UnicodeError):
        return None
    version = message.get("Version")
    if message.get("Name", "").lower().replace("_", "-") != "dblift" or not version:
        return None
    if not wheel.name.startswith(f"dblift-{version}-"):
        return None
    if metadata_files[0].split("/", 1)[0] != f"dblift-{version}.dist-info":
        return None
    return version


def qualify(
    wheel: Path,
    output: Path,
    probe: Path,
    corpus_probe: Path | None = None,
    corpus_fixtures: Path | None = None,
) -> int:
    result: dict = {
        "artifact_sha256": None,
        "python": None,
        "installed": {},
        "probes": {},
        "status": "fail",
    }
    try:
        if not wheel.is_absolute() or not wheel.is_file() or wheel.suffix != ".whl":
            result["error"] = "wheel must be an existing absolute .whl file"
            return 1
        if not probe.is_file():
            result["error"] = "installed probe is missing"
            return 1
        if corpus_probe is not None and not corpus_probe.is_file():
            result["error"] = "corpus probe is missing"
            return 1
        if corpus_fixtures is not None and (corpus_probe is None or not corpus_fixtures.is_dir()):
            result["error"] = "corpus fixtures require a probe and directory"
            return 1
        candidate_version = _candidate_version(wheel)
        if candidate_version is None:
            result["error"] = "candidate distribution is not dblift"
            return 1
        result["artifact_sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix="dblift-qualify-") as root:
            root_path = Path(root)
            env_path = root_path / "env"
            work = root_path / "work"
            work.mkdir()
            checked_run([sys.executable, "-m", "venv", str(env_path)], work)
            python = env_path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            result["python"] = checked_run([str(python), "--version"], work).stdout.strip()
            # Installation output can contain index credentials; record only its status.
            try:
                checked_run([str(python), "-m", "pip", "install", str(wheel)], work)
                checked_run([str(python), "-m", "pip", "check"], work)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                result["error"] = f"wheel installation failed ({type(exc).__name__})"
                return 1
            copied_probe = work / "installed_probe.py"
            shutil.copyfile(probe, copied_probe)
            ok = _record(
                result, "installed", [str(python), "-I", str(copied_probe), candidate_version], work
            )
            if ok:
                try:
                    details = json.loads(result["probes"]["installed"]["stdout"])
                    installed = details["installed"]
                    if (
                        not isinstance(installed, dict)
                        or installed.get("dblift") != candidate_version
                    ):
                        raise ValueError("installed version does not match candidate")
                    required = ("dblift", "PyYAML", "rich", "Jinja2", "sqlglot", "SQLAlchemy")
                    if not all(
                        isinstance(installed.get(name), str) and installed[name]
                        for name in required
                    ):
                        raise ValueError("installed dependency versions are missing")
                    if not Path(details["origin"]).resolve().is_relative_to(env_path.resolve()):
                        raise ValueError("installed origin is outside target environment")
                    if (
                        "sqlite" not in details["providers"]
                        or details["sqlite_migrate"] is not True
                    ):
                        raise ValueError("installed probe did not verify SQLite")
                    result["installed"] = installed
                except (ValueError, KeyError, TypeError):
                    result["error"] = "installed probe returned malformed JSON"
                    ok = False
            if ok and corpus_probe is not None:
                copied_corpus = work / "corpus_probe.py"
                shutil.copyfile(corpus_probe, copied_corpus)
                if corpus_fixtures is not None:
                    shutil.copytree(corpus_fixtures, work / "fixtures")
                ok = _record(
                    result,
                    "corpus",
                    [str(python), "-I", str(copied_corpus), candidate_version],
                    work,
                )
                if ok:
                    try:
                        corpus = json.loads(result["probes"]["corpus"]["stdout"])
                        if corpus["status"] != "pass":
                            raise ValueError("corpus probe did not pass")
                        if not Path(corpus["origin"]).resolve().is_relative_to(env_path.resolve()):
                            raise ValueError("corpus origin is outside target environment")
                        if Path(corpus["workdir"]).resolve() != work.resolve():
                            raise ValueError("corpus workdir is not neutral")
                        result["corpus"] = corpus
                    except (ValueError, KeyError, TypeError):
                        result["error"] = "corpus probe returned malformed JSON"
                        ok = False
            if ok:
                result["status"] = "pass"
            return 0 if ok else 1
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        result["error"] = f"qualification setup failed ({type(exc).__name__})"
        return 1
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--probe", type=Path, default=Path(__file__).with_name("lightweight_installed_probe.py")
    )
    parser.add_argument("--corpus-probe", type=Path)
    parser.add_argument("--corpus-fixtures", type=Path)
    args = parser.parse_args()
    return qualify(args.wheel, args.output, args.probe, args.corpus_probe, args.corpus_fixtures)


if __name__ == "__main__":
    sys.exit(main())

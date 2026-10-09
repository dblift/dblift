"""Qualify the functional corpus inside the installed wheel's environment."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tests.artifacts._clean_source import archived_source

ROOT = Path(__file__).resolve().parents[2]
QUALIFIER = ROOT / "scripts" / "qualify_lightweight_core.py"
FORK_QUALIFIER = ROOT / "scripts" / "qualify_sqlite_fork.py"
CORPUS = Path(__file__).with_name("lightweight_corpus_probe.py")
FIXTURES = Path(__file__).parent / "fixtures" / "lightweight"
DIAGNOSTIC = Path(__file__).with_name("lightweight_diagnostic_probe.py")
PUBLISHED_4100_SHA256 = "b979a3ff5abb84a75e751c105b5c4fceb597e094e4e996f6df31f281ccd26dc5"


def _retain(source: Path, name: str) -> None:
    directory = os.environ.get("E4_EVIDENCE_DIR")
    if directory:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


@pytest.fixture(scope="module")
def candidate_wheel(tmp_path_factory):
    dist = tmp_path_factory.mktemp("corpus-wheel")
    source = archived_source(ROOT, dist / "source")
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(dist), str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(dist.glob("dblift-*.whl"))
    _retain(wheel, wheel.name)
    return wheel


def test_candidate_wheel_excludes_retired_storage_modules(candidate_wheel):
    retired = (
        "dblift/db/plugins/base_snapshot_manager.py",
        "dblift/db/plugins/cosmosdb/cosmosdb/snapshot_manager.py",
        "dblift/db/plugins/mongodb/mongodb/snapshot_manager.py",
    )
    assert all(not (ROOT / path).exists() for path in retired)
    with zipfile.ZipFile(candidate_wheel) as archive:
        assert not set(retired).intersection(archive.namelist())


def test_candidate_wheel_excludes_generation_only_modules(candidate_wheel):
    retired = {
        "dblift/core/state/sql_statement.py",
        "dblift/db/generator_protocol.py",
        "dblift/extensions/sql_generation.py",
    }
    with zipfile.ZipFile(candidate_wheel) as archive:
        assert not retired.intersection(archive.namelist())


def test_candidate_wheel_excludes_builtin_catalog_hooks(candidate_wheel, tmp_path):
    with zipfile.ZipFile(candidate_wheel) as archive:
        assert "dblift/db/plugins/oracle/introspection/oracle_utils.py" not in archive.namelist()

    probe = tmp_path / "catalog_probe.py"
    probe.write_text(
        "import importlib.util\n"
        "import json\n"
        "from pathlib import Path\n"
        "import dblift\n"
        "from dblift.db.base_quirks import BaseQuirks\n"
        "from dblift.db.plugins.oracle.quirks import OracleQuirks\n"
        "from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks\n"
        "for cls in (BaseQuirks, OracleQuirks, PostgresqlQuirks):\n"
        "    for name in ('enrich_view_from_row', 'fetch_unique_constraints', "
        "'index_no_sort_types', 'introspector_class', 'vendor_queries_class'):\n"
        "        assert not hasattr(cls, name), (cls.__name__, name)\n"
        "assert importlib.util.find_spec('dblift.db.plugins.oracle.introspection') is None\n"
        "print(json.dumps({'status': 'pass', 'origin': str(Path(dblift.__file__).resolve()), "
        "'workdir': str(Path.cwd().resolve())}))\n",
        encoding="utf-8",
    )
    output = tmp_path / "catalog_result.json"
    run = subprocess.run(
        [
            sys.executable,
            str(QUALIFIER),
            "--wheel",
            str(candidate_wheel.resolve()),
            "--output",
            str(output),
            "--corpus-probe",
            str(probe),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "pass"


def test_corpus_probe_uses_the_installed_wheel_and_neutral_workdir(candidate_wheel, tmp_path):
    probe = tmp_path / "corpus_probe.py"
    probe.write_text(
        "import json\n"
        "from pathlib import Path\n"
        "import dblift\n"
        "print(json.dumps({'status': 'pass', 'origin': str(Path(dblift.__file__).resolve()), "
        "'workdir': str(Path.cwd().resolve())}))\n",
        encoding="utf-8",
    )
    output = tmp_path / "result.json"
    run = subprocess.run(
        [
            sys.executable,
            str(QUALIFIER),
            "--wheel",
            str(candidate_wheel.resolve()),
            "--output",
            str(output),
            "--corpus-probe",
            str(probe),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "pass"
    corpus = result["corpus"]
    assert corpus["status"] == "pass"
    assert Path(corpus["origin"]).is_relative_to(Path(corpus["workdir"]).parent)
    assert not Path(corpus["origin"]).is_relative_to(ROOT)


def test_corpus_fixtures_are_copied_outside_the_checkout(candidate_wheel, tmp_path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "marker.txt").write_text("isolated", encoding="utf-8")
    probe = tmp_path / "corpus_probe.py"
    probe.write_text(
        "import json\n"
        "from pathlib import Path\n"
        "import dblift\n"
        "assert Path('fixtures/marker.txt').read_text() == 'isolated'\n"
        "print(json.dumps({'status': 'pass', 'origin': str(Path(dblift.__file__).resolve()), "
        "'workdir': str(Path.cwd().resolve())}))\n",
        encoding="utf-8",
    )
    output = tmp_path / "result.json"
    run = subprocess.run(
        [
            sys.executable,
            str(QUALIFIER),
            "--wheel",
            str(candidate_wheel.resolve()),
            "--output",
            str(output),
            "--corpus-probe",
            str(probe),
            "--corpus-fixtures",
            str(fixtures),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["corpus"]["status"] == "pass"


def test_corpus_copy_failure_cannot_report_pass(candidate_wheel, tmp_path):
    corpus = tmp_path / "deleted_probe.py"
    corpus.write_text("print('{}')\n", encoding="utf-8")
    standard = tmp_path / "standard_probe.py"
    standard.write_text(
        "import json\n"
        "import sys\n"
        "from pathlib import Path\n"
        "from importlib import metadata\n"
        "import dblift\n"
        f"Path({str(corpus)!r}).unlink()\n"
        "names = ('PyYAML', 'rich', 'Jinja2', 'sqlglot', 'SQLAlchemy')\n"
        "installed = {'dblift': sys.argv[1]}\n"
        "installed.update({name: metadata.version(name) for name in names})\n"
        "print(json.dumps({'origin': str(Path(dblift.__file__).resolve()), "
        "'installed': installed, 'providers': ['sqlite'], 'sqlite_migrate': True}))\n",
        encoding="utf-8",
    )
    output = tmp_path / "result.json"
    run = subprocess.run(
        [
            sys.executable,
            str(QUALIFIER),
            "--wheel",
            str(candidate_wheel.resolve()),
            "--output",
            str(output),
            "--probe",
            str(standard),
            "--corpus-probe",
            str(corpus),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode != 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "fail"


def test_real_sqlite_corpus_runs_from_installed_wheel(candidate_wheel, tmp_path):
    output = tmp_path / "result.json"
    run = subprocess.run(
        [
            sys.executable,
            str(QUALIFIER),
            "--wheel",
            str(candidate_wheel.resolve()),
            "--output",
            str(output),
            "--corpus-probe",
            str(CORPUS),
            "--corpus-fixtures",
            str(FIXTURES),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr + output.read_text(encoding="utf-8")
    _retain(output, "candidate-corpus.json")
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "pass"
    assert {row["requirement"] for row in result["corpus"]["cases"]} >= {
        "L2-04",
        "L5-02",
        "L5-03",
        "L5-04",
        "L5-05",
    }
    assert all(row["outcome"] == "pass" for row in result["corpus"]["cases"])
    cli_case = next(row for row in result["corpus"]["cases"] if row["requirement"] == "L2-04")
    assert cli_case["evidence"]["text_stdout_contains_error"] is True
    assert cli_case["evidence"]["success_cli"]["migrate_success"] is True
    assert cli_case["evidence"]["success_cli"]["repeatable_applied"] is True
    assert cli_case["evidence"]["success_cli"]["undo_success"] is True
    core_case = next(row for row in result["corpus"]["cases"] if row["requirement"] == "L5-02")
    assert core_case["evidence"]["final_info_version"] is None
    assert core_case["evidence"]["final_history"]
    assert core_case["evidence"]["callbacks_after_repeatable"]
    async_case = next(row for row in result["corpus"]["cases"] if row["requirement"] == "L2-02")
    assert async_case["evidence"]["sync_async_rows_match"] is True
    assert async_case["evidence"]["stdout"] == async_case["evidence"]["stderr"] == ""
    rollback_case = next(row for row in result["corpus"]["cases"] if row["requirement"] == "L5-04")
    assert rollback_case["evidence"]["prior_write_rolled_back"] is True
    concurrency_case = next(
        row for row in result["corpus"]["cases"] if row["requirement"] == "L5-05"
    )
    assert concurrency_case["evidence"]["worker_origins_verified"] is True


def test_sqlite_corpus_matches_published_4100(candidate_wheel, tmp_path):
    baseline_dir = tmp_path / "published"
    baseline_dir.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--only-binary=:all:",
            "--no-deps",
            "--dest",
            str(baseline_dir),
            "dblift==4.10.0",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    baseline = next(baseline_dir.glob("dblift-*.whl"))
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == PUBLISHED_4100_SHA256
    _retain(baseline, f"baseline/{baseline.name}")
    results = []
    for label, wheel in (("baseline", baseline), ("candidate", candidate_wheel)):
        output = tmp_path / f"{label}.json"
        run = subprocess.run(
            [
                sys.executable,
                str(QUALIFIER),
                "--wheel",
                str(wheel.resolve()),
                "--output",
                str(output),
                "--corpus-probe",
                str(CORPUS),
                "--corpus-fixtures",
                str(FIXTURES),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, run.stderr + output.read_text(encoding="utf-8")
        _retain(output, f"{label}-parity-corpus.json")
        results.append(json.loads(output.read_text(encoding="utf-8")))
    before, after = results
    assert before["status"] == after["status"] == "pass"
    assert before["corpus"]["cases"] == after["corpus"]["cases"]


def test_installed_silent_api_without_presentation_dependencies(candidate_wheel, tmp_path):
    output = tmp_path / "result.json"
    environment = os.environ.copy()
    environment["DBLIFT_E4_DIAGNOSTIC_PROFILE"] = "presentation"
    run = subprocess.run(
        [
            sys.executable,
            str(QUALIFIER),
            "--wheel",
            str(candidate_wheel.resolve()),
            "--output",
            str(output),
            "--corpus-probe",
            str(DIAGNOSTIC),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr + output.read_text(encoding="utf-8")
    _retain(output, "presentation-uninstall.json")
    diagnostic = json.loads(output.read_text(encoding="utf-8"))["corpus"]
    assert diagnostic["status"] == "pass"
    assert diagnostic["missing"] == ["Jinja2", "rich"]
    assert diagnostic["pip_check_returncode"] != 0
    assert diagnostic["venv_verified_before_uninstall"] is True
    assert "rich" in diagnostic["pip_check_output"].lower()
    assert diagnostic["silent_sqlite"] is True
    assert diagnostic["no_implicit_report_files"] is True


def test_installed_low_level_sqlite_without_sqlglot(candidate_wheel, tmp_path):
    output = tmp_path / "result.json"
    environment = os.environ.copy()
    environment["DBLIFT_E4_DIAGNOSTIC_PROFILE"] = "sqlglot"
    run = subprocess.run(
        [
            sys.executable,
            str(QUALIFIER),
            "--wheel",
            str(candidate_wheel.resolve()),
            "--output",
            str(output),
            "--corpus-probe",
            str(DIAGNOSTIC),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr + output.read_text(encoding="utf-8")
    _retain(output, "sqlglot-uninstall.json")
    diagnostic = json.loads(output.read_text(encoding="utf-8"))["corpus"]
    assert diagnostic["profile"] == "sqlglot"
    assert diagnostic["missing"] == ["sqlglot"]
    assert diagnostic["venv_verified_before_uninstall"] is True
    assert "sqlglot" in diagnostic["pip_check_output"].lower()
    assert diagnostic["low_level_v_u"] is True
    assert diagnostic["standard_client_failed_before_mutation"] is True
    assert "sqlglot" in diagnostic["standard_client_failure"]["failure"].lower()
    assert diagnostic["standard_client_failure"]["tables_after_failure"] == []


def test_fork_runs_the_same_installed_sqlite_corpus(candidate_wheel, tmp_path):
    candidate_output = tmp_path / "candidate.json"
    candidate = subprocess.run(
        [
            sys.executable,
            str(QUALIFIER),
            "--wheel",
            str(candidate_wheel.resolve()),
            "--output",
            str(candidate_output),
            "--corpus-probe",
            str(CORPUS),
            "--corpus-fixtures",
            str(FIXTURES),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert candidate.returncode == 0, candidate.stderr
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    output = tmp_path / "fork.json"
    fork = subprocess.run(
        [
            sys.executable,
            str(FORK_QUALIFIER),
            "--revision",
            revision,
            "--output",
            str(output),
            "--corpus-probe",
            str(CORPUS),
            "--corpus-fixtures",
            str(FIXTURES),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert fork.returncode == 0, fork.stderr
    _retain(output, "fork-corpus.json")
    result = json.loads(output.read_text(encoding="utf-8"))
    _retain(Path(result["wheel"]), Path(result["wheel"]).name)
    _retain(Path(result["diff"]), "fork.diff")
    assert result["status"] == "pass"
    assert result["corpus"]["removed_imports_blocked"] is True
    assert all(row["outcome"] == "pass" for row in result["corpus"]["cases"])
    assert result["corpus"]["history_table"] == "forklift_schema_history"
    candidate_cases = json.loads(candidate_output.read_text(encoding="utf-8"))["corpus"]["cases"]
    assert result["corpus"]["cases"] == candidate_cases

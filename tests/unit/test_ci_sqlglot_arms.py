"""The statement-facts corpus is recorded on two sqlglot releases; CI runs it on both.

``constraints-ci.txt`` pins sqlglot at the declared minimum, so the main unit-test job runs
the corpus on that arm. The ``sqlglot-newest`` job installs the extras without the constraints
file and then the newest release the corpus was recorded on. These tests read the workflow so
neither arm can silently drop out.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "unit-tests.yml"
CONSTRAINTS = ROOT / "constraints-ci.txt"
VERSIONS = ROOT / "tests" / "support" / "facts_corpus" / "VERSIONS.json"
CORPUS_TESTS = "tests/unit/core/sql_parser"


def _jobs() -> Dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _steps(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    return job["steps"]


def _run_text(job: Dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in _steps(job))


def _install_step(job: Dict[str, Any]) -> Dict[str, Any]:
    (step,) = [step for step in _steps(job) if "sqlglot==" in step.get("run", "")]
    return step


def test_the_newest_job_installs_the_recorded_release() -> None:
    step = _install_step(_jobs()["sqlglot-newest"])
    assert "VERSIONS.json" in step["run"] and "newest" in step["run"]
    assert 'pip install "sqlglot==$NEWEST' in step["run"]


def test_the_newest_job_installs_the_extras_without_the_constraints_file_first() -> None:
    job = _jobs()["sqlglot-newest"]
    run = _install_step(job)["run"]
    assert run.index('pip install -e ".[dev,') < run.index("sqlglot==")
    assert "PIP_CONSTRAINT" not in json.dumps(job)


def test_the_newest_job_fails_unless_the_installed_sqlglot_is_the_recorded_one() -> None:
    """A job that silently ran another release would certify nothing."""
    lines = [
        line
        for line in _install_step(_jobs()["sqlglot-newest"])["run"].splitlines()
        if "sqlglot.__version__" in line
    ]
    assert [line for line in lines if "assert" in line and "$NEWEST" in line]


def test_the_newest_job_runs_the_corpus_tests() -> None:
    job = _jobs()["sqlglot-newest"]
    tests = [step["run"] for step in _steps(job) if "pytest" in step.get("run", "")]
    assert len(tests) == 1
    assert CORPUS_TESTS in tests[0]


def test_there_is_no_second_job_installing_a_sqlglot_release() -> None:
    others = {
        name: job
        for name, job in _jobs().items()
        if name != "sqlglot-newest" and re.search(r"sqlglot==", _run_text(job))
    }
    assert others == {}


def test_the_main_job_runs_the_corpus_on_the_arm_the_constraints_pin() -> None:
    main = _jobs()["unit-tests"]
    assert "tests/unit/" in _run_text(main)
    assert "constraints-ci.txt" in main["env"]["PIP_CONSTRAINT"]
    floor = json.loads(VERSIONS.read_text(encoding="utf-8"))["floor"]
    pins = {
        canonicalize_name(Requirement(line).name): Requirement(line).specifier
        for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert str(pins["sqlglot"]) == f"=={floor}"


def test_the_recorded_arms_lie_inside_the_supported_range() -> None:
    versions = json.loads(VERSIONS.read_text(encoding="utf-8"))
    dependencies = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]["analysis"]
    (spec,) = [Requirement(d).specifier for d in dependencies if d.startswith("sqlglot")]
    assert versions["floor"] in spec and versions["newest"] in spec
    assert f">={versions['floor']}" in str(spec)

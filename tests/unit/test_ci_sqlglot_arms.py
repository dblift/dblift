"""The statement-facts corpus is recorded on two sqlglot releases; CI runs it on both.

``constraints-ci.txt`` pins sqlglot at the declared minimum, so the main unit-test job already
runs the corpus on that arm. The ``sqlglot-floor`` job installs the extras without the
constraints file and then one explicit release per matrix leg: the declared minimum, and the
newest release the corpus was recorded on. These tests read the workflow so the two legs cannot
silently become one.
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


def _install_steps(job: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        arm: next(step for step in _steps(job) if step.get("if") == f"matrix.arm == '{arm}'")
        for arm in ("floor", "newest")
    }


def test_the_job_runs_one_leg_per_recorded_arm() -> None:
    job = _jobs()["sqlglot-floor"]
    assert job["strategy"]["matrix"]["arm"] == ["floor", "newest"]
    assert set(_install_steps(job)) == {"floor", "newest"}


def test_the_floor_leg_keeps_its_check_name() -> None:
    """Branch protection names the check; only the added leg is new."""
    name = _jobs()["sqlglot-floor"]["name"]
    assert "matrix.arm == 'newest'" in name and name.startswith("sqlglot-floor")


def test_the_floor_leg_installs_the_declared_minimum_and_the_newest_leg_the_recorded_release() -> (
    None
):
    floor, newest = _install_steps(_jobs()["sqlglot-floor"]).values()
    assert "pyproject.toml" in floor["run"] and "sqlglot==" in floor["run"]
    assert "VERSIONS.json" in newest["run"] and "newest" in newest["run"]
    assert "sqlglot==" in newest["run"]


def test_both_legs_install_the_extras_without_the_constraints_file_first() -> None:
    job = _jobs()["sqlglot-floor"]
    for step in _install_steps(job).values():
        first = step["run"].index('pip install -e ".[dev,')
        assert first < step["run"].index("sqlglot==")
    assert "PIP_CONSTRAINT" not in json.dumps(job)


def test_each_leg_fails_unless_the_installed_sqlglot_is_the_one_it_intended() -> None:
    """A leg that silently ran the other release would certify nothing."""
    floor, newest = _install_steps(_jobs()["sqlglot-floor"]).values()
    for step, variable in ((floor, "FLOOR"), (newest, "NEWEST")):
        lines = [line for line in step["run"].splitlines() if "sqlglot.__version__" in line]
        asserting = [line for line in lines if "assert" in line and f"${variable}" in line]
        assert asserting, f"{variable}: no line asserts the installed version"
        assert 'pip install "sqlglot==$' + variable in step["run"]


def test_both_legs_run_the_corpus_tests() -> None:
    job = _jobs()["sqlglot-floor"]
    tests = [step["run"] for step in _steps(job) if "pytest" in step.get("run", "")]
    assert len(tests) == 1, "one test step serves both legs"
    assert CORPUS_TESTS in tests[0]
    assert not [step for step in _steps(job) if "pytest" in step.get("run", "") and "if" in step]


def test_there_is_no_second_job_installing_a_sqlglot_release() -> None:
    others = {
        name: job
        for name, job in _jobs().items()
        if name != "sqlglot-floor" and re.search(r"sqlglot==", _run_text(job))
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
        "dependencies"
    ]
    (spec,) = [Requirement(d).specifier for d in dependencies if d.startswith("sqlglot")]
    assert versions["floor"] in spec and versions["newest"] in spec
    assert f">={versions['floor']}" in str(spec)

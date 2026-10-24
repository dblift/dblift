"""The base install is lightweight: presentation and analysis are opt-in extras.

``pip install dblift`` carries the execution path (PyYAML, SQLAlchemy). The
command line needs Rich and Jinja2 (``cli``); full SQL analysis needs SQLGlot
(``analysis``). ``dblift[all]`` keeps meaning "everything", so it reaches both.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[2]
_PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
_EXTRAS: dict[str, list[str]] = _PROJECT["optional-dependencies"]


def _names(specs: list[str]) -> set[str]:
    return {canonicalize_name(Requirement(spec).name) for spec in specs}


def _reachable(extra: str, seen: frozenset[str] = frozenset()) -> set[str]:
    """Extras reachable from ``extra`` through ``dblift[...]`` self-references."""
    found = {extra}
    for spec in _EXTRAS.get(extra, []):
        requirement = Requirement(spec)
        if canonicalize_name(requirement.name) == "dblift":
            for inner in requirement.extras:
                if inner not in seen | found:
                    found |= _reachable(inner, seen | found)
    return found


def test_base_install_is_execution_only():
    assert _names(_PROJECT["dependencies"]) == {"pyyaml", "sqlalchemy"}


def test_cli_extra_carries_the_presentation_libraries():
    assert _names(_EXTRAS["cli"]) == {"rich", "jinja2"}


def test_analysis_extra_carries_sqlglot_with_its_bounds():
    (requirement,) = [Requirement(spec) for spec in _EXTRAS["analysis"]]
    assert canonicalize_name(requirement.name) == "sqlglot"
    assert {(s.operator, s.version.split(".")[0]) for s in requirement.specifier} == {
        (">=", "30"),
        ("<", "31"),
    }


@pytest.mark.parametrize("extra", ["all", "dev", "mcp", "django", "flask", "fastapi"])
def test_extras_that_run_the_client_reach_cli_and_analysis(extra):
    """Each of these used to get Rich, Jinja2 and SQLGlot from the base install."""
    assert {"cli", "analysis"} <= _reachable(extra)


def test_all_still_reaches_every_engine_extra():
    engines = set(_EXTRAS) - {
        "all",
        "dev",
        "cli",
        "analysis",
        "django",
        "flask",
        "fastapi",
        "mcp",
        "otel",
    }
    assert engines <= _reachable("all")

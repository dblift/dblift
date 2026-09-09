"""CI dependency determinism for the ``mcp`` extra.

``constraints-ci.txt`` exists so a pull request fails for its own changes and
not because a dependency published a release that morning:
``.github/workflows/unit-tests.yml`` sets ``PIP_CONSTRAINT`` to it for every
event except the weekly ``latest`` schedule.

The protection only reaches distributions the file actually names. When the
``mcp`` extra was added to the workflow's install line the constraints file was
not regenerated with it, so the whole SDK subtree — ``mcp`` itself plus
``pydantic``, ``anyio``, ``starlette``, ``jsonschema`` and the rest — installed
unpinned while every other dependency was frozen. Nothing in the repository
noticed, because nothing compared the two lists.

These tests compare them.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[2]
CONSTRAINTS = ROOT / "constraints-ci.txt"
UNIT_TESTS_WORKFLOW = ROOT / ".github" / "workflows" / "unit-tests.yml"

# ``pip install -e ".[a,b,c]"`` — the extras list of an editable install.
_EXTRAS_INSTALL = re.compile(r'pip install -e "\.\[([^\]]+)\]"')

# Every distribution `pip install -c constraints-ci.txt "mcp>=2.2,<3"` resolves
# that no other extra already pins, on Python 3.11, against mcp 2.2.0. The list
# is deliberately explicit: when an SDK release adds or drops a dependency the
# regenerated file changes, this test fails, and the change gets read rather
# than absorbed silently. Names are canonicalised on both sides.
MCP_SUBTREE = frozenset(
    {
        "annotated-types",
        "anyio",
        "attrs",
        "h11",
        "httpcore2",
        "httpx2",
        "jsonschema",
        "jsonschema-specifications",
        "mcp",
        "mcp-types",
        "pydantic",
        "pydantic-core",
        "python-multipart",
        "referencing",
        "rpds-py",
        "sse-starlette",
        "starlette",
        "truststore",
        "typing-inspection",
        "uvicorn",
    }
)


def _extras_of(text: str, source: Path) -> set[str]:
    match = _EXTRAS_INSTALL.search(text)
    assert match is not None, f"no editable install with extras found in {source}"
    return {extra.strip() for extra in match.group(1).split(",")}


def _pinned_distributions() -> set[str]:
    names: set[str] = set()
    for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        names.add(canonicalize_name(Requirement(stripped).name))
    return names


def _optional_dependencies() -> dict[str, list[str]]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]


@pytest.mark.unit
def test_the_regenerate_recipe_names_the_extras_the_unit_tests_install():
    """The header's regenerate command and the workflow's install line must
    ask for the same extras.

    This is the drift that let the SDK subtree through: the workflow gained
    ``mcp``, the recipe did not, and the next regeneration would have dropped
    the pins again even once they are added."""
    recipe = _extras_of(CONSTRAINTS.read_text(encoding="utf-8"), CONSTRAINTS)
    workflow = _extras_of(UNIT_TESTS_WORKFLOW.read_text(encoding="utf-8"), UNIT_TESTS_WORKFLOW)

    assert recipe == workflow, (
        "constraints-ci.txt's regenerate recipe and unit-tests.yml install "
        "different extras; the difference installs unpinned in CI: "
        f"only in the workflow {sorted(workflow - recipe)}, "
        f"only in the recipe {sorted(recipe - workflow)}"
    )


@pytest.mark.unit
def test_constraints_pin_every_distribution_the_mcp_extra_installs():
    """A dependency the workflow installs but the file does not name is
    resolved fresh on every run — exactly what the file exists to prevent."""
    missing = sorted(MCP_SUBTREE - _pinned_distributions())

    assert not missing, (
        "constraints-ci.txt does not pin these dependencies of the mcp "
        f"extra, so CI resolves them fresh on every run: {missing}"
    )


@pytest.mark.unit
def test_the_mcp_extra_is_capped_below_the_next_major():
    """``mcp`` is used against ``mcp.server.mcpserver``, an API surface that
    differs from the widely published 1.x layout: the rename happened across a
    major. An uncapped requirement means the next major installs cleanly, type
    checks cleanly, and fails at runtime when the server starts. Same argument
    as the ``sqlglot`` cap in ``[project].dependencies``."""
    requirements = _optional_dependencies()["mcp"]
    specifiers = Requirement(requirements[0]).specifier

    assert any(
        spec.operator in {"<", "<=", "==", "~="} for spec in specifiers
    ), f"the mcp extra has no upper bound: {requirements[0]!r}"


@pytest.mark.unit
def test_the_dev_extra_carries_the_mcp_sdk():
    """Without the SDK, ``pytest.importorskip("mcp")`` removes every test that
    speaks the protocol — the server, the tool registration and the stdio
    smoke test — and the suite still reports success. A contributor installing
    ``.[dev]`` to run the tests has to get the tests."""
    dev = {canonicalize_name(Requirement(entry).name) for entry in _optional_dependencies()["dev"]}

    assert "mcp" in dev, "pip install -e '.[dev]' silently skips the MCP protocol tests"

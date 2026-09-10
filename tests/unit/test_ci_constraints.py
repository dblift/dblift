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

# The SDK release MCP_SUBTREE was derived from. Pinned separately so that
# bumping ``mcp`` in constraints-ci.txt by hand — the cheap move, since a real
# regeneration needs a twelve-extra virtualenv — cannot leave the subtree list
# describing the previous release.
MCP_VERSION = "2.2.0"

# Every distribution the workflow's install line adds when the ``mcp`` extra is
# appended to it, on Python 3.11, against mcp 2.2.0. The list is a hand-written
# constant on purpose: it holds with no SDK installed, which is what makes it a
# usable gate. It catches a *dropped* pin on its own; a dependency the SDK
# *adds* is caught by MCP_VERSION above and, when the SDK is importable, by
# ``test_the_subtree_list_still_covers_what_the_sdk_requires`` below.
# Names are canonicalised on both sides.
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


def _pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        requirement = Requirement(stripped)
        pins[canonicalize_name(requirement.name)] = str(requirement.specifier).lstrip("=")
    return pins


def _pinned_distributions() -> set[str]:
    return set(_pins())


def _mcp_requirement(entries: list[str]) -> Requirement:
    matches = [
        Requirement(entry)
        for entry in entries
        if canonicalize_name(Requirement(entry).name) == "mcp"
    ]
    assert len(matches) == 1, f"expected exactly one mcp requirement, found {matches}"
    return matches[0]


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
def test_the_subtree_list_describes_the_pinned_sdk_release():
    """MCP_SUBTREE is a snapshot of one SDK release's dependencies, so the two
    have to move together. Without this, bumping ``mcp`` in constraints-ci.txt
    by hand leaves the list describing the previous release, and a dependency
    the new one added installs unpinned while every test stays green."""
    assert _pins()["mcp"] == MCP_VERSION, (
        f"constraints-ci.txt pins mcp {_pins()['mcp']} but MCP_SUBTREE was "
        f"derived from {MCP_VERSION}: re-derive the list, then update "
        "MCP_VERSION"
    )


@pytest.mark.unit
def test_the_subtree_list_still_covers_what_the_sdk_requires():
    """The reverse direction, available only when the SDK is installed: every
    dependency mcp declares for this environment must be pinned, whether the
    hand-written list anticipated it or not. Direct requirements only — a
    transitive addition is still caught by the release pin above."""
    pytest.importorskip("mcp")
    from importlib.metadata import metadata

    declared = metadata("mcp").get_all("Requires-Dist") or []
    required = {
        canonicalize_name(requirement.name)
        for requirement in map(Requirement, declared)
        # Requirements behind an ``extra`` marker are not installed by a bare
        # ``pip install mcp``; platform markers are evaluated for this run.
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""})
    }
    unpinned = sorted(required - _pinned_distributions())

    assert not unpinned, (
        f"mcp {MCP_VERSION} requires these and constraints-ci.txt does not " f"pin them: {unpinned}"
    )


@pytest.mark.unit
def test_the_mcp_extra_declares_an_upper_bound():
    """``mcp`` is used against ``mcp.server.mcpserver``, an API surface that
    differs from the widely published 1.x layout: the rename happened across a
    major. An uncapped requirement means the next major installs cleanly, type
    checks cleanly, and fails at runtime when the server starts. Same argument
    as the ``sqlglot`` cap in ``[project].dependencies``. This asserts only
    that a bound exists — which release to cap at is a judgement call, and the
    cap in the file today is ``<3``."""
    requirement = _mcp_requirement(_optional_dependencies()["mcp"])

    assert any(
        spec.operator in {"<", "<=", "==", "~="} for spec in requirement.specifier
    ), f"the mcp extra has no upper bound: {str(requirement)!r}"


@pytest.mark.unit
def test_the_dev_extra_carries_the_mcp_sdk_on_the_same_specifier():
    """Without the SDK, ``pytest.importorskip("mcp")`` removes every test that
    speaks the protocol — the server, the tool registration and the stdio
    smoke test — and the suite still reports success. A contributor installing
    ``.[dev]`` to run the tests has to get the tests.

    The specifiers have to match, not merely the name: ``.[dev]`` is installed
    on its own by ``.github/workflows/security.yml``, so a ``dev`` entry that
    drifted off the cap would let that job resolve an SDK major the code does
    not target."""
    dev = _optional_dependencies()["dev"]
    names = {canonicalize_name(Requirement(entry).name) for entry in dev}

    assert "mcp" in names, "pip install -e '.[dev]' silently skips the MCP protocol tests"
    assert (
        _mcp_requirement(dev).specifier
        == _mcp_requirement(_optional_dependencies()["mcp"]).specifier
    ), "the dev entry and the mcp extra ask for different SDK versions"

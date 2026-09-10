"""What CI measures has to exist, and has to reach the upload.

``pytest --cov=<target>`` does not fail on a target it cannot resolve. It
warns, collects nothing, writes no report, and the job stays green. The
Codecov step that follows finds no file and, with ``fail_ci_if_error`` unset,
does not fail either.

That is what happened here between 2026-09-02 and 2026-09-09. The workflow
asked for ``api``, ``cli``, ``config``, ``core``, ``db`` and ``integrations``,
which were top-level directories and correct when they were written; 4.0.0
(#265) moved them under ``dblift/`` and nothing updated the workflow, because
nothing read it. Coverage reporting had worked for the whole life of the
repository before that, so this is a refactor hazard rather than a typo — the
reason to check it mechanically instead of by eye.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

# ``--cov=dblift``, ``--cov dblift``, ``--cov="dblift"``. The sibling options
# are ``--cov-report``, ``--cov-config``, ``--cov-fail-under``, ``--cov-branch``
# and ``--cov-append``: every one takes a hyphen where a target takes ``=`` or a
# space, so requiring that character is what tells them apart. Matching on the
# option names instead would also have swallowed ``--cov=config``. The capture
# is deliberately greedy — a target this cannot resolve must reach a test and
# fail there, not be quietly skipped.
_COV_TARGET = re.compile(r"--cov[= ]([^\s\\]+)")


def _workflows() -> list[Path]:
    # GitHub Actions reads both extensions.
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


def _coverage_targets() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for workflow in _workflows():
        for target in _COV_TARGET.findall(workflow.read_text(encoding="utf-8")):
            found.append((workflow, target.strip("\"'")))
    return found


def _measures_coverage(workflow: Path) -> bool:
    return any(path == workflow for path, _ in _coverage_targets())


def test_every_coverage_target_is_a_literal_this_test_can_resolve():
    """A shell variable or an Actions expression cannot be checked by reading
    the file, so the guard would pass on a target that measures nothing. Fail
    instead, and keep the check honest about what it can see."""
    unresolvable = [
        (workflow.name, target)
        for workflow, target in _coverage_targets()
        if "$" in target or "{{" in target
    ]

    assert not unresolvable, (
        "these coverage targets are computed at run time, so this test cannot "
        f"tell whether they measure anything: {unresolvable}"
    )


def test_every_coverage_target_names_an_importable_package():
    """Existence is not enough. ``--cov=scripts`` names a real directory and
    still collects nothing, because no module under it is imported by the test
    run — the same empty report, one directory over. A package is the thing
    coverage can actually measure."""
    targets = _coverage_targets()
    assert targets, "no --cov targets found; has the workflow layout changed?"

    not_a_package = []
    for workflow, target in targets:
        path = ROOT / target.replace(".", "/")
        # A dotted target may name a module rather than a package.
        if (path / "__init__.py").exists() or path.with_suffix(".py").exists():
            continue
        not_a_package.append((workflow.name, target))

    assert not not_a_package, (
        "these coverage targets are not importable packages or modules in "
        "this repository, so the job collects no data and stays green: "
        f"{not_a_package}"
    )


def test_a_workflow_that_measures_coverage_also_writes_and_uploads_it():
    """The target is only the first of three things that have to agree. With
    no ``--cov-report=xml`` nothing is written; with a Codecov step pointed at
    a different path nothing is uploaded. Both fail the same silent way the
    unresolvable target did."""
    for workflow in _workflows():
        if not _measures_coverage(workflow):
            continue
        text = workflow.read_text(encoding="utf-8")

        assert "--cov-report=xml" in text, (
            f"{workflow.name} measures coverage but writes no XML report, so "
            "the upload has nothing to send"
        )
        if "codecov/codecov-action" in text:
            assert "coverage.xml" in text, (
                f"{workflow.name} uploads to Codecov without naming the "
                "coverage.xml that --cov-report=xml produces"
            )

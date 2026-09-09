"""What CI measures has to exist.

``pytest --cov=<target>`` takes an importable module name or a path. Give it
neither and coverage does not fail: it warns ``Module <x> was never imported``,
writes an empty report, and the job stays green. The upload that follows
succeeds too, so the only symptom is a coverage figure that never moves.

That is what the unit-test workflow did from the first commit of this
repository — it asked for ``api``, ``cli``, ``config``, ``core``, ``db`` and
``integrations``, which are subpackages of ``dblift``, not top-level ones —
and no test noticed, because no test read the workflow.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

# ``--cov=dblift``, ``--cov=dblift/api``, ``--cov dblift``. The sibling options
# are ``--cov-report``, ``--cov-config``, ``--cov-fail-under``, ``--cov-branch``
# and ``--cov-append``: all take a hyphen where a target takes ``=`` or a space,
# so requiring that character is enough to tell them apart. Matching on the
# option names instead would also have swallowed ``--cov=config``.
_COV_TARGET = re.compile(r"--cov[= ]([\w./-]+)")


def _coverage_targets() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for target in _COV_TARGET.findall(workflow.read_text(encoding="utf-8")):
            found.append((workflow, target))
    return found


@pytest.mark.unit
def test_every_coverage_target_names_something_that_exists():
    """A target that resolves to nothing measures nothing, silently."""
    targets = _coverage_targets()
    assert targets, "no --cov targets found; has the workflow layout changed?"

    missing = [
        (workflow.name, target)
        for workflow, target in targets
        if not (ROOT / target.replace(".", "/")).exists()
    ]

    assert not missing, (
        "these coverage targets do not exist in the repository, so the job "
        f"reports no data and stays green: {missing}"
    )

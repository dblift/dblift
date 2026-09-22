"""Every mandatory dependency must be imported by code every install runs."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

pytestmark = [pytest.mark.unit]

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "dblift"

# Distribution name -> top-level import name, where the two differ.
_IMPORT_NAMES = {
    "pyyaml": "yaml",
    "python-dateutil": "dateutil",
    "typing-extensions": "typing_extensions",
}


def test_every_mandatory_dependency_is_imported() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    # Framework integrations are optional and ship their own extras, so an
    # import that only happens there does not justify a mandatory dependency.
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE.rglob("*.py"))
        if "integrations" not in path.relative_to(PACKAGE).parts
    )
    unused = []
    for spec in project["dependencies"]:
        dist = canonicalize_name(Requirement(spec).name)
        module = _IMPORT_NAMES.get(dist, dist.replace("-", "_"))
        if not re.search(rf"^\s*(import|from) {re.escape(module)}\b", source, flags=re.MULTILINE):
            unused.append(dist)
    assert unused == [], (
        f"declared in [project].dependencies but never imported outside integrations: {unused}. "
        "Remove them, or move them to the extra whose integration imports them."
    )

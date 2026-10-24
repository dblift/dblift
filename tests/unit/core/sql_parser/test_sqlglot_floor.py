"""The declared sqlglot floor is a version the statement-facts reader is tested against."""

import re
from importlib.metadata import version
from pathlib import Path

from packaging.version import Version

PYPROJECT = Path(__file__).resolve().parents[4] / "pyproject.toml"


def test_declared_sqlglot_floor_is_not_above_the_installed_version():
    match = re.search(r'"sqlglot>=([0-9][^,"]*),', PYPROJECT.read_text(encoding="utf-8"))
    assert match, "pyproject.toml declares no sqlglot floor"
    assert Version(match.group(1)) <= Version(version("sqlglot"))

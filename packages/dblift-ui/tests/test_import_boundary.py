"""dblift_ui may use the migration engine only through its public API."""

import ast
from pathlib import Path

import dblift_ui

ALLOWED_PREFIXES = ("dblift.api",)


def _dblift_imports(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append(node.module)
    return [name for name in found if name == "dblift" or name.startswith("dblift.")]


def test_only_the_public_api_is_imported():
    package = Path(dblift_ui.__file__).resolve().parent
    offenders = []
    for path in sorted(package.rglob("*.py")):
        for name in _dblift_imports(path.read_text()):
            if not name.startswith(ALLOWED_PREFIXES):
                offenders.append(f"{path.relative_to(package)}: {name}")
    assert offenders == []


def test_the_check_catches_a_forbidden_import():
    assert _dblift_imports("from dblift.core.migration import x\nimport dblift.db\n") == [
        "dblift.core.migration",
        "dblift.db",
    ]

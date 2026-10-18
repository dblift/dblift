"""Guard: no default, fallback or re-export exists only so tests can skip the state layer."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Optional

import dblift

_ROOT = Path(dblift.__file__).parent


def _tree(relative: str) -> ast.Module:
    return ast.parse((_ROOT / relative).read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _defaults(func: ast.FunctionDef) -> Dict[str, Optional[ast.expr]]:
    """Map every parameter name to its default expression (None when it has none)."""
    args = func.args
    positional = args.posonlyargs + args.args
    out: Dict[str, Optional[ast.expr]] = {a.arg: None for a in positional}
    for arg, default in zip(positional[len(positional) - len(args.defaults) :], args.defaults):
        out[arg.arg] = default
    for arg, kw_default in zip(args.kwonlyargs, args.kw_defaults):
        out[arg.arg] = kw_default
    return out


def test_no_test_only_fallbacks():
    checks = [
        ("core/sql_validator/_checksum_validator.py", "check_repeatable_migrations", "runs"),
        ("core/sql_validator/_checksum_validator.py", "validate_checksums", "drift"),
        ("core/sql_validator/migration_validator.py", "_check_repeatable_migrations", "runs"),
        ("core/sql_validator/migration_validator.py", "_validate_checksums", "drift"),
        (
            "core/sql_validator/migration_validator.py",
            "_validate_prepared_migrations",
            "repeatable_runs",
        ),
        (
            "core/sql_validator/migration_validator.py",
            "_validate_prepared_migrations",
            "checksum_drift",
        ),
        ("core/migration/state/migration_state_manager.py", "_is_repeatable_pending", "runs"),
    ]
    for relative, function, parameter in checks:
        defaults = _defaults(_function(_tree(relative), function))
        assert parameter in defaults, f"{function} lost its {parameter} parameter"
        assert defaults[parameter] is None, f"{function}({parameter}=...) must have no default"

    manager = _tree("core/migration/state/migration_state_manager.py")
    for node in ast.walk(manager):
        if isinstance(node, ast.ClassDef):
            assert node.name != "StrictModeError"
        if isinstance(node, ast.ImportFrom):
            assert "StrictModeError" not in [alias.name for alias in node.names]
        if isinstance(node, ast.Name):
            assert node.id != "StrictModeError"

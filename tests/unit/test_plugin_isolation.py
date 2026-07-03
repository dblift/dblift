"""Layering tests — enforce the plugin isolation contract in CI.

The architecture commits to three layering rules (see
``docs/architecture/database-providers.md``):

1. **No hardcoded core → plugin dependencies.** A file in ``core/``
   must not ``from db.plugins.<specific>...`` import anything. Core
   talks to plugins through ``BaseQuirks`` hooks and the
   ``ProviderRegistry`` factories — never by naming a specific
   dialect. Currently strict (PR #370 retired the last violation).

2. **No upward db → core domain leaks.** ``db/introspection/`` must
   not import from ``core/validation/`` or ``core/migration/``.
   The only legal upward references are
   ``core.sql_model``, ``core.logger``, ``core.constants``.

3. **No cross-plugin imports.** A plugin in ``db/plugins/<a>/`` must
   not import from ``db/plugins/<b>/`` (a ≠ b). Plugins are
   siblings; they communicate via the abstract interfaces in ``db/``.

The tests scan every ``.py`` file under the relevant trees with the
``ast`` module and assert the rules. Both top-level and lazy
(function-scope) imports count: an "if TYPE_CHECKING" import that
shows up in the AST is a real violation.

Rule 1 is strict. Rule 2 carries a ``KNOWN_VIOLATIONS`` dict for
imports awaiting follow-up; each entry must reference the PR or
ADR that justifies the exemption. A companion test verifies every
listed violation is still present in source — once a follow-up PR
removes the import, the allow-list entry must go with it (no dead
exemptions).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Rule 1: no hardcoded core → plugin imports ────────────────────────────

# Maps a file path (relative to repo root) → set of forbidden import
# prefixes that file is allow-listed to use. Empty = Rule 1 strict.
# Adding an entry must reference the follow-up PR or ADR that
# justifies the exemption.
KNOWN_CORE_TO_PLUGIN_VIOLATIONS: dict[str, set[str]] = {}


# ── Rule 2: no db/introspection/ → core/{validation,licensing,migration} ──

# Same shape as ``KNOWN_CORE_TO_PLUGIN_VIOLATIONS``. Empty = Rule 2 strict.
KNOWN_DB_TO_CORE_VIOLATIONS: dict[str, set[str]] = {}


# ── Rule 3: no cross-plugin imports ───────────────────────────────────────

# MariaDB inherits from MySQL by design (same native-driver family, same
# SQL dialect for ~95% of cases). CosmosDB SQL is T-SQL-flavoured enough
# that its regex parser inherits the SQL Server parser. Both relations
# are documented in docs/architecture/database-providers.md.
ALLOWED_CROSS_PLUGIN_IMPORTS: dict[str, set[str]] = {
    "db/plugins/mariadb": {"db.plugins.mysql"},
    "db/plugins/cosmosdb": {"db.plugins.sqlserver.parser"},
}


# ── Helpers ───────────────────────────────────────────────────────────────


def _python_files_under(root: Path) -> Iterable[Path]:
    """Yield every .py file under ``root``, skipping caches."""
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def _imported_modules(path: Path) -> set[str]:
    """Return every fully-qualified module name imported by ``path``.

    Captures both top-level and inner-scope imports — the AST does not
    distinguish, which is what we want: lazy imports are still a
    coupling that violates the layering contract.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return set()

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                modules.add(node.module)
    return modules


def _string_literals(path: Path) -> set[str]:
    """Return every string literal in ``path``."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return set()

    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _has_forbidden_import(
    modules: set[str], forbidden_prefixes: tuple[str, ...], allowed_exact: set[str]
) -> set[str]:
    """Return any imported module that matches a forbidden prefix and isn't allow-listed."""
    hits = set()
    for module in modules:
        for prefix in forbidden_prefixes:
            if module == prefix or module.startswith(prefix + "."):
                if module not in allowed_exact:
                    hits.add(module)
                break
    return hits


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


# ── Rule 1 enforcement ────────────────────────────────────────────────────


class TestNoCoreToPluginImports:
    """``core/`` files must never import a specific plugin module."""

    def test_no_hardcoded_plugin_imports_in_core(self):
        violations: dict[str, set[str]] = {}
        core_dir = REPO_ROOT / "core"
        for path in _python_files_under(core_dir):
            modules = _imported_modules(path)
            hits = _has_forbidden_import(modules, ("db.plugins",), allowed_exact=set())
            if hits:
                rel = _relative(path)
                allowed = KNOWN_CORE_TO_PLUGIN_VIOLATIONS.get(rel, set())
                unexpected = hits - allowed
                if unexpected:
                    violations[rel] = unexpected

        assert not violations, (
            "core/ files importing specific plugins (rule #1 violation).\n"
            "Route the call through BaseQuirks/ProviderRegistry, or\n"
            "register the violation in KNOWN_CORE_TO_PLUGIN_VIOLATIONS with\n"
            "a justifying follow-up reference:\n"
            + "\n".join(
                f"  {file}: {sorted(imports)}" for file, imports in sorted(violations.items())
            )
        )

    def test_known_violations_are_still_present(self):
        """Stale entries in KNOWN_CORE_TO_PLUGIN_VIOLATIONS should be removed.

        Once a follow-up PR retires a violation, the entry must be
        deleted from KNOWN_CORE_TO_PLUGIN_VIOLATIONS — otherwise we
        accumulate dead allow-list entries that mask future regressions.
        """
        stale: dict[str, set[str]] = {}
        for rel, expected in KNOWN_CORE_TO_PLUGIN_VIOLATIONS.items():
            path = REPO_ROOT / rel
            if not path.is_file():
                stale[rel] = expected
                continue
            actual = _imported_modules(path)
            missing = expected - actual
            if missing:
                stale[rel] = missing

        assert not stale, (
            "KNOWN_CORE_TO_PLUGIN_VIOLATIONS contains entries no longer "
            "present in the source. Remove them:\n"
            + "\n".join(f"  {file}: {sorted(imports)}" for file, imports in sorted(stale.items()))
        )


# ── Rule 2 enforcement ────────────────────────────────────────────────────


class TestNoDbIntrospectionToCoreLeaks:
    """``db/introspection/`` may not import core.validation / licensing / migration."""

    FORBIDDEN_CORE_PREFIXES = (
        "core.validation",
        "core.migration",
    )

    def test_no_upward_imports(self):
        violations: dict[str, set[str]] = {}
        target = REPO_ROOT / "db" / "introspection"
        for path in _python_files_under(target):
            modules = _imported_modules(path)
            hits = _has_forbidden_import(modules, self.FORBIDDEN_CORE_PREFIXES, allowed_exact=set())
            if hits:
                rel = _relative(path)
                allowed = KNOWN_DB_TO_CORE_VIOLATIONS.get(rel, set())
                unexpected = hits - allowed
                if unexpected:
                    violations[rel] = unexpected

        assert not violations, (
            "db/introspection/ files importing core.{validation,licensing,migration}\n"
            "(rule #2 violation). Either lift the helper up into core/, or\n"
            "register it in KNOWN_DB_TO_CORE_VIOLATIONS with a follow-up reference:\n"
            + "\n".join(
                f"  {file}: {sorted(imports)}" for file, imports in sorted(violations.items())
            )
        )

    def test_known_violations_are_still_present(self):
        stale: dict[str, set[str]] = {}
        for rel, expected in KNOWN_DB_TO_CORE_VIOLATIONS.items():
            path = REPO_ROOT / rel
            if not path.is_file():
                stale[rel] = expected
                continue
            actual = _imported_modules(path)
            missing = expected - actual
            if missing:
                stale[rel] = missing

        assert (
            not stale
        ), "KNOWN_DB_TO_CORE_VIOLATIONS contains entries no longer present:\n" + "\n".join(
            f"  {file}: {sorted(imports)}" for file, imports in sorted(stale.items())
        )


# ── Rule 3 enforcement ────────────────────────────────────────────────────


class TestNoCrossPluginImports:
    """A plugin must not import another plugin (except documented inheritance)."""

    def test_no_unauthorised_cross_plugin_imports(self):
        plugins_dir = REPO_ROOT / "db" / "plugins"
        if not plugins_dir.is_dir():
            pytest.skip("db/plugins/ not present")

        plugin_names = {p.name for p in plugins_dir.iterdir() if p.is_dir()}

        violations: dict[str, set[str]] = {}
        for plugin in plugin_names:
            plugin_dir = plugins_dir / plugin
            allowed_cross = ALLOWED_CROSS_PLUGIN_IMPORTS.get(f"db/plugins/{plugin}", set())

            for path in _python_files_under(plugin_dir):
                modules = _imported_modules(path)
                rel = _relative(path)
                for module in modules:
                    if not module.startswith("db.plugins."):
                        continue
                    parts = module.split(".")
                    if len(parts) < 3:
                        continue
                    other_plugin = parts[2]
                    # ``db.plugins.base_*`` are shared infrastructure
                    # modules (BaseHistoryManager, BaseLockingManager,
                    # BaseQueryExecutor, BaseSchemaOperations) — not a
                    # plugin folder. Plugins are expected to import them.
                    if other_plugin not in plugin_names:
                        continue
                    if other_plugin == plugin:
                        continue
                    # Match a submodule boundary — ``"db.plugins.sqlserver.parser"``
                    # must allow ``db.plugins.sqlserver.parser`` itself and any
                    # ``db.plugins.sqlserver.parser.<x>``, but NOT a sibling like
                    # ``db.plugins.sqlserver.parser_legacy`` (Bugbot review).
                    if any(
                        module == prefix or module.startswith(prefix + ".")
                        for prefix in allowed_cross
                    ):
                        continue
                    violations.setdefault(rel, set()).add(module)

        assert not violations, (
            "Cross-plugin imports detected (rule #3 violation).\n"
            "Plugins must talk only through abstract interfaces in db/.\n"
            "If a new plugin family relation is intentional (e.g., MariaDB ⊃ MySQL),\n"
            "add it to ALLOWED_CROSS_PLUGIN_IMPORTS:\n"
            + "\n".join(
                f"  {file}: {sorted(imports)}" for file, imports in sorted(violations.items())
            )
        )

"""AST-based lint rules for recurring bug patterns.

Runs on every PR via ``.github/workflows/code-quality.yml``. Each rule
targets a bug family that has cost the project multiple releases.

Rules
=====

``cli-print-stdout``
    Direct ``print(...)`` inside ``cli/`` contaminates stdout with
    human-readable text. Subcommands with ``--format json`` (and other
    machine-readable formats) need a clean stdout contract. Use
    ``ctx.log.*`` or pass ``file=sys.stderr``. Intentional direct stdout
    writes (e.g. the JSON payload print in ``_handle_validate_sql``)
    must be annotated with ``# lint: allow-print`` on the same line.

``enum-str-conversion``
    ``str(something.type)`` / ``str(migration_type)`` on a
    ``MigrationType`` enum yields ``"MigrationType.SQL"``, not
    ``"SQL"``. This has caused silent comparison failures in
    ``VERSIONED_SCRIPT_TYPES`` lookups, reapplied-version detection, and
    display-type formatting (PR 160 Bugbot threads). The long-term fix
    is the ``is_versioned(m)`` helper that ships in Phase 2 PR-06; until
    then every existing occurrence is tagged with
    ``# lint: allow-enum-str: PR-06`` so PR-06 has a concrete checklist.

``dialect-string-literal``
    Dialect-name string literals (``"postgresql"``, ``"oracle"``,
    ``"mysql"``, ``"sqlserver"``, ``"db2"``, ``"sqlite"``,
    ``"cosmosdb"``, ``"mariadb"``, …) appearing in ``api/``, ``cli/``,
    ``config/``, ``core/`` or ``db/`` couple framework code to specific
    dialects and prevent the plug-and-play architecture from Epic 26.
    ``db/`` is scanned in full, including the shared base modules
    directly under ``db/plugins/`` (``db/plugins/*.py``, e.g.
    ``base_snapshot_manager.py``) — they are framework code. Only a
    per-dialect plugin *package* ``db/plugins/<X>/**`` may reference its
    own dialect (and is exempt); ``core/introspection/`` is exempt for
    its capability matrices; the rest of the framework should never name
    a dialect. Replace branches like
    ``if dialect.lower() == "oracle":`` with a ``DialectQuirks`` hook
    on the provider. Annotate intentional uses (e.g. registry keys
    that *must* hold a string list of supported dialects) with
    ``# lint: allow-dialect-string: <reason>``.

Running
=======

    python scripts/lint_patterns.py                  # full tree
    python scripts/lint_patterns.py api cli core     # targeted
    python scripts/lint_patterns.py --help

Zero-baseline policy
====================

Project policy is that ``.lint-patterns-baseline.txt`` contains zero
non-comment entries. Every deferred violation lives as an inline
``# lint: allow-*`` annotation next to the offending line, never as a
pre-recorded entry. The script enforces this: a baseline file with
any non-comment line makes the script exit 1 with a policy-violation
message. The ``--write-baseline`` capability has been removed (PR-A4)
to keep that surface closed.

Exit code 1 on any unannotated violation OR a non-empty baseline file.
Exit code 0 otherwise.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

# Roots scanned by default when the user passes no positional argument.
DEFAULT_ROOTS: Tuple[str, ...] = ("api", "cli", "config", "core", "db")

# Annotations a maintainer adds to the offending line (or the line just
# above) to declare the occurrence as intentional / deferred.
ALLOW_PRINT_MARKER = "lint: allow-print"
ALLOW_ENUM_STR_MARKER = "lint: allow-enum-str"
ALLOW_DIALECT_STRING_MARKER = "lint: allow-dialect-string"

# Canonical dialect identifiers. Lowercased on comparison. Includes
# legitimate aliases (``postgres`` for ``postgresql``) and dialects we
# may add later (Snowflake, MariaDB, CockroachDB, MongoDB, H2). Adding
# a new dialect = append here so the framework cannot quietly grow a
# new ``if dialect == "newdb"`` branch.
DIALECT_NAMES: frozenset = frozenset(
    {
        # Canonical names
        "postgresql",
        "oracle",
        "mysql",
        "mariadb",
        "sqlserver",
        "db2",
        "sqlite",
        "cosmosdb",
        "mongodb",
        "snowflake",
        "cockroachdb",
        "h2",
        # Aliases — registered alongside canonical names in plugin
        # PluginInfo.dialects. PR #241 Bugbot:
        # missing aliases let new violations slip through the lint
        # guard.
        "postgres",
        "mssql",
        "sql_server",
        "sqlite3",
        "cosmos_db",
    }
)

# Roots the dialect-string-literal rule scans. ``db/`` shared framework
# code is scanned in full, including the shared base modules directly
# under ``db/plugins/`` (``db/plugins/*.py``). Only per-dialect plugin
# packages ``db/plugins/<X>/**`` (handled positionally in
# ``_is_under_dialect_rule_roots``) and ``core/introspection/`` (see
# DIALECT_RULE_EXEMPT_PREFIXES) are exempt.
DIALECT_RULE_ROOTS: Tuple[str, ...] = ("api", "cli", "config", "core", "db")

# Path prefixes that are otherwise inside ``DIALECT_RULE_ROOTS`` but
# exempted because the dialect-string literal is inherent to the
# module's purpose. Currently empty: ``core/introspection/`` is now
# scanned. The dialect-specific introspection filters that used to
# require the exemption (Oracle's generated ``IS NOT NULL`` check,
# version-detector parsing, and the dead capability/version stores)
# have been moved into plugin quirks or deleted (ADR-26 B/B2), so the
# schema-reading layer no longer names a dialect.
#
# ``db/`` is scanned in full, *including* the shared base modules that
# sit directly under ``db/plugins/`` (``db/plugins/*.py``, e.g.
# ``base_snapshot_manager.py``) — those are framework code. Only the
# per-dialect plugin *packages* ``db/plugins/<X>/**`` are exempt, and
# that exemption is handled positionally in
# ``_is_under_dialect_rule_roots`` (not via a simple prefix), because a
# plugin package legitimately names its own dialect.
#
# ``_is_under_dialect_rule_roots`` still iterates this tuple, so it
# stays defined (empty).
DIALECT_RULE_EXEMPT_PREFIXES: Tuple[str, ...] = ()


class Violation:
    __slots__ = ("path", "line", "col", "rule", "message")

    def __init__(
        self,
        path: Path,
        line: int,
        col: int,
        rule: str,
        message: str,
    ) -> None:
        self.path = path
        self.line = line
        self.col = col
        self.rule = rule
        self.message = message

    def render(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: {self.rule}: {self.message}"


# ---------------------------------------------------------------------------
# Rule 1: cli-print-stdout
# ---------------------------------------------------------------------------


def _print_writes_to_stderr(call: ast.Call) -> bool:
    """True when the call is ``print(..., file=sys.stderr)``."""
    for kw in call.keywords:
        if kw.arg != "file":
            continue
        val = kw.value
        if isinstance(val, ast.Attribute) and val.attr == "stderr":
            return True
        if isinstance(val, ast.Name) and val.id == "stderr":
            return True
    return False


# Files whose stdout is a machine-readable contract. Direct print()
# inside these modules is almost always wrong — the JSON/SARIF/etc
# payload is the contract, and any extra line breaks it.
#
# Other cli/ modules (db_utils, license_commands, _config_helpers,
# _parser_setup) are interactive user-facing utilities where print()
# is the expected medium. Keeping the rule narrow avoids 100+
# annotations on legitimate diagnostic output.
STDOUT_CONTRACT_FILES: Tuple[str, ...] = (
    "cli/main.py",
    "cli/_command_handlers.py",
)


def _in_stdout_contract_file(path: Path) -> bool:
    posix = path.as_posix()
    return any(posix.endswith(f) for f in STDOUT_CONTRACT_FILES)


def _check_cli_print_stdout(path: Path, tree: ast.AST, source: List[str]) -> Iterator[Violation]:
    if not _in_stdout_contract_file(path):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "print"):
            continue
        if _print_writes_to_stderr(node):
            continue
        # Same-line or previous-line allow marker
        line_text = source[node.lineno - 1] if 0 < node.lineno <= len(source) else ""
        prev_text = source[node.lineno - 2] if 1 < node.lineno <= len(source) else ""
        if ALLOW_PRINT_MARKER in line_text or ALLOW_PRINT_MARKER in prev_text:
            continue
        yield Violation(
            path,
            node.lineno,
            node.col_offset + 1,
            "cli-print-stdout",
            "print() in cli/ contaminates stdout; use ctx.log.* or "
            "file=sys.stderr, or annotate with '# lint: allow-print' "
            "if this is an intentional machine-readable payload write.",
        )


# ---------------------------------------------------------------------------
# Rule 2: enum-str-conversion
# ---------------------------------------------------------------------------


def _is_str_call(call: ast.Call) -> bool:
    return isinstance(call.func, ast.Name) and call.func.id == "str" and len(call.args) == 1


def _argument_looks_like_enum(arg: ast.expr) -> bool:
    """Heuristic: attribute access ``X.type`` or variable named ``*_type*``.

    Over-flags on purpose — every false positive can be annotated with
    ``# lint: allow-enum-str`` (cheap), but an unflagged real case is a
    silent bug (expensive). See PR 160 Bugbot threads.
    """
    if isinstance(arg, ast.Attribute) and arg.attr == "type":
        return True
    if isinstance(arg, ast.Name):
        name = arg.id.lower()
        if name == "migration_type" or name.endswith("_type") or name == "type_":
            return True
    return False


def _check_enum_str_conversion(path: Path, tree: ast.AST, source: List[str]) -> Iterator[Violation]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_str_call(node):
            continue
        if not _argument_looks_like_enum(node.args[0]):
            continue
        line_text = source[node.lineno - 1] if 0 < node.lineno <= len(source) else ""
        prev_text = source[node.lineno - 2] if 1 < node.lineno <= len(source) else ""
        if ALLOW_ENUM_STR_MARKER in line_text or ALLOW_ENUM_STR_MARKER in prev_text:
            continue
        yield Violation(
            path,
            node.lineno,
            node.col_offset + 1,
            "enum-str-conversion",
            "str(<enum>) produces 'EnumClass.MEMBER', not 'MEMBER'. "
            "Use .value / .name, or the shared is_versioned() helper "
            "(Phase 2 PR-06). Annotate intentional uses with "
            "'# lint: allow-enum-str' if the argument is not an enum.",
        )


# ---------------------------------------------------------------------------
# Rule 3: dialect-string-literal
# ---------------------------------------------------------------------------


def _is_under_dialect_rule_roots(path: Path) -> bool:
    """True when the file lives under api/, cli/, config/, core/, or db/
    *and* is not under a documented exempt prefix.

    ``db/`` is scanned in full, including the shared base modules that sit
    directly under ``db/plugins/`` (``db/plugins/*.py``, e.g.
    ``base_snapshot_manager.py``) — those are framework code. The
    exemption is deliberately narrow: a per-dialect plugin *package*
    ``db/plugins/<X>/**`` legitimately references its own dialect.
    ``core/introspection/`` is no longer exempt — its dialect-specific
    filters were moved to plugin quirks (ADR-26 B2), so the schema-reading
    layer is now scanned like the rest of ``core/``. scripts/ and docs/
    ship one-off tools and are out of scope entirely.
    """
    parts = path.parts
    if not parts:
        return False
    if parts[0] not in DIALECT_RULE_ROOTS:
        return False
    posix = path.as_posix()
    for prefix in DIALECT_RULE_EXEMPT_PREFIXES:
        if posix.startswith(prefix + "/") or posix == prefix:
            return False
    # db/plugins/<X>/** is a per-dialect plugin package (it may name its own
    # dialect — that is its identity). Shared base modules directly under
    # db/plugins/ (db/plugins/*.py, e.g. base_snapshot_manager.py) are framework
    # code and ARE scanned.
    if parts[:2] == ("db", "plugins") and len(parts) >= 4:
        return False
    return True


def _check_dialect_string_literal(
    path: Path, tree: ast.AST, source: List[str]
) -> Iterator[Violation]:
    if not _is_under_dialect_rule_roots(path):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if not isinstance(node.value, str):
            continue
        # Cheap pre-filter: dialect names are short. Skip long literals.
        if len(node.value) > 32:
            continue
        value_lower = node.value.lower()
        if value_lower not in DIALECT_NAMES:
            continue
        line_text = source[node.lineno - 1] if 0 < node.lineno <= len(source) else ""
        prev_text = source[node.lineno - 2] if 1 < node.lineno <= len(source) else ""
        if ALLOW_DIALECT_STRING_MARKER in line_text or ALLOW_DIALECT_STRING_MARKER in prev_text:
            continue
        yield Violation(
            path,
            node.lineno,
            node.col_offset + 1,
            "dialect-string-literal",
            f"Dialect name {node.value!r} hardcoded in framework code. "
            "Replace with a DialectQuirks hook on the provider (Epic 26). "
            "Annotate intentional uses with "
            "'# lint: allow-dialect-string: <reason>'.",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _iter_py_files(roots: List[Path]) -> Iterator[Path]:
    skip = {"__pycache__", ".git", "build", "dist", ".venv", "venv", "antlr"}
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            yield root
            continue
        for p in root.rglob("*.py"):
            if any(part in skip for part in p.parts):
                continue
            yield p


def _lint_file(path: Path) -> List[Violation]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        # Not our concern — syntax errors are caught by mypy/black/flake8.
        return []
    lines = source.splitlines()
    out: List[Violation] = []
    out.extend(_check_cli_print_stdout(path, tree, lines))
    out.extend(_check_enum_str_conversion(path, tree, lines))
    out.extend(_check_dialect_string_literal(path, tree, lines))
    return out


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO_ROOT / ".lint-patterns-baseline.txt"


def _check_baseline_is_empty(path: Path) -> Optional[str]:
    """Return an error message if the baseline file has any non-comment entries.

    The lint-patterns gate is a zero-baseline policy: any deferred
    violation must be expressed as an inline ``# lint: allow-*``
    annotation (which carries the reason next to the code), never as a
    pre-recorded entry here. Re-grandfathering a violation through this
    file would erode the gate.
    """
    if not path.is_file():
        return None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        return (
            f"{path.name} contains a grandfathered entry: {line!r}. The "
            "project's lint-patterns policy is zero baseline — annotate "
            "the offending line with '# lint: allow-print' / "
            "'# lint: allow-enum-str' / '# lint: allow-dialect-string' "
            "instead."
        )
    return None


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "roots",
        nargs="*",
        default=list(DEFAULT_ROOTS),
        help=f"Files or directories to scan (default: {' '.join(DEFAULT_ROOTS)}).",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help=f"Baseline file to consult (default: {DEFAULT_BASELINE.name}).",
    )
    args = parser.parse_args(argv)

    # Zero-baseline policy: the file may only contain comment / blank
    # lines. Re-grandfathering a violation by hand-editing this file
    # is rejected. Use an inline ``# lint: allow-*`` annotation
    # instead, so the reason lives next to the code.
    policy_error = _check_baseline_is_empty(args.baseline)
    if policy_error:
        print(policy_error, file=sys.stderr)
        return 1

    root_paths = [Path(r) for r in args.roots]
    violations: List[Violation] = []
    for py in _iter_py_files(root_paths):
        violations.extend(_lint_file(py))
    violations.sort(key=lambda v: (str(v.path), v.line, v.col))

    # Zero-baseline policy (PR-A4): every reported violation must either
    # be fixed or annotated inline. Nothing is grandfathered through the
    # baseline file — that's enforced above by ``_check_baseline_is_empty``.
    for v in violations:
        print(v.render())
    if violations:
        print(
            f"\n{len(violations)} unannotated violation(s). "
            "Either fix the code or, if the pattern is intentional, "
            "annotate the line with '# lint: allow-print' / "
            "'# lint: allow-enum-str' / "
            "'# lint: allow-dialect-string'.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

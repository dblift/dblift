"""``validate-sql``: a verdict for each migration script, from its findings.

Scripts are linted alone, or as a delta: scripts applied together, in order, where a table
an earlier script created is new for every later one (see ``lint_rules``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from functools import cmp_to_key
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    AbstractSet,
    Any,
    Dict,
    FrozenSet,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from dblift.core.migration.migration_types import MigrationType
from dblift.core.migration.placeholders.placeholder_service import PlaceholderService
from dblift.core.migration.scripting.filename_parser import (
    is_migration_sql_file,
    parse_migration_filename,
)
from dblift.core.migration.sql.script_analysis import (
    DISABLED_ANALYSIS,
    ScriptAnalysis,
    analyse_script,
)
from dblift.core.migration.version_utils import compare_versions

# ``lint_rules`` needs sqlglot, so it is imported where a rule runs: ``info`` and ``migrate``
# import this module and must load without sqlglot.
if TYPE_CHECKING:
    from dblift.core.migration.sql.lint_rules import Finding

SAFE = "SAFE"
REVIEW = "REVIEW"
UNSAFE = "UNSAFE"

_ANALYSED_TYPES = (MigrationType.SQL, MigrationType.REPEATABLE)
# Undo, baseline and callback scripts are not linted unless named explicitly:
# an undo script destroys what its migration created by design.
_LINTED_PREFIXES = ("V", "R")
_ALLOW = re.compile(
    r"--\s*dblift:allow\s+([A-Za-z0-9_.-]+(?:\s*,\s*[A-Za-z0-9_.-]+)*)", re.IGNORECASE
)


@dataclass(frozen=True)
class ScriptLint:
    """The verdict for one script, with the findings and parse errors behind it."""

    script: str
    verdict: str
    findings: Tuple[Finding, ...]
    errors: Tuple[str, ...]
    # Tables the script creates (lower-cased, unqualified), to carry to the next script
    # of a delta; not part of the JSON payload.
    created_tables: FrozenSet[str] = field(default=frozenset(), compare=False)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready form of the script's verdict."""
        return {
            "script": self.script,
            "verdict": self.verdict,
            "findings": [f.to_dict() for f in self.findings],
            "errors": list(self.errors),
        }


def allowed_codes(text: str) -> FrozenSet[str]:
    """Codes a script accepts with ``-- dblift:allow code[, code...]`` anywhere in it."""
    codes: Set[str] = set()
    for match in _ALLOW.finditer(text):
        codes.update(part.strip().lower() for part in match.group(1).split(","))
    return frozenset(codes)


def verdict_of(findings: Sequence[Finding], errors: Sequence[str]) -> str:
    """UNSAFE on an error finding not allowed, REVIEW on any other finding or a parse
    error, SAFE otherwise."""
    from dblift.core.migration.sql.lint_rules import ERROR

    counted = [f for f in findings if not f.allowed]
    if any(f.severity == ERROR for f in counted):
        return UNSAFE
    if counted or errors:
        return REVIEW
    return SAFE


def lint_analysis(
    analysis: ScriptAnalysis,
    text: str,
    dialect: str,
    script: str = "",
    *,
    created_before: Optional[AbstractSet[str]] = None,
) -> ScriptLint:
    """Verdict for a script already analysed, honouring its ``dblift:allow`` comments.

    *created_before* names the tables earlier scripts of the delta created, lower-cased
    and unqualified (the union of their ``created_tables``).
    """
    from dblift.core.migration.sql.lint_rules import issues_and_created_tables

    allowed = allowed_codes(text)
    issues, created = issues_and_created_tables(analysis, dialect, created_before or frozenset())
    findings = tuple(replace(f, allowed=f.code in allowed) for f in issues)
    return ScriptLint(
        script, verdict_of(findings, analysis.errors), findings, analysis.errors, created
    )


def lint_script(
    text: str,
    dialect: str,
    script: str = "",
    *,
    created_before: Optional[AbstractSet[str]] = None,
) -> ScriptLint:
    """Analyse *text* and return its verdict; *created_before* as for ``lint_analysis``."""
    return lint_analysis(
        analyse_script(text, dialect), text, dialect, script, created_before=created_before
    )


def lint_targets(
    directories: Sequence[Path],
    *,
    recursive: bool,
    recursive_by_dir: Optional[Mapping[Path, bool]] = None,
) -> List[Path]:
    """The V and R migration SQL files of *directories* that validate-sql reads by default.

    Each directory is searched recursively per ``recursive_by_dir`` (default *recursive*);
    its files come sorted, directory after directory.
    """
    overrides = recursive_by_dir or {}
    files: List[Path] = []
    for directory in directories:
        pattern = "**/*.sql" if overrides.get(directory, recursive) else "*.sql"
        files.extend(
            sorted(
                path
                for path in directory.glob(pattern)
                if is_migration_sql_file(path) and path.name[:1].upper() in _LINTED_PREFIXES
            )
        )
    return files


def _apply_order(paths: Sequence[Path]) -> List[Path]:
    """Versioned scripts by version, then repeatable scripts by name, then the rest as given."""
    versioned: List[Tuple[Optional[str], Path]] = []
    repeatable: List[Path] = []
    other: List[Path] = []
    for path in paths:
        name = parse_migration_filename(path.name)
        if name.migration_type is MigrationType.SQL:
            versioned.append((name.version, path))
        elif name.migration_type is MigrationType.REPEATABLE:
            repeatable.append(path)
        else:
            other.append(path)

    def by_version(left: Tuple[Optional[str], Path], right: Tuple[Optional[str], Path]) -> int:
        return compare_versions(left[0], right[0])

    versioned.sort(key=cmp_to_key(by_version))
    repeatable.sort(key=lambda path: path.name.lower())
    return [path for _, path in versioned] + repeatable + other


def lint_files(
    paths: Sequence[Path],
    dialect: str,
    placeholders: Dict[str, Any],
    log: Any,
    *,
    as_delta: bool = False,
) -> List[ScriptLint]:
    """Lint each file after substituting the configured placeholders.

    By default each file is linted alone, in the order given. With ``as_delta`` the files
    are one delta, linted and returned in apply order: versioned scripts by version, then
    repeatable scripts by name, then any other file in the order given.
    """
    substitution = PlaceholderService(placeholders, log)
    created: Set[str] = set()
    results = []
    for path in _apply_order(paths) if as_delta else paths:
        text = substitution.replace_placeholders(path.read_text(encoding="utf-8"))
        result = lint_script(text, dialect, path.name, created_before=created)
        if as_delta:
            created |= result.created_tables
        results.append(result)
    return results


def lint_pending_scripts(
    migrations: Iterable[Any],
    dialect: str,
    log: Any,
    *,
    enabled: bool = True,
    as_delta: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """``{script_name: analysis}`` for the SQL and repeatable scripts of *migrations*
    that have text, each analysis carrying the script's ``verdict`` and ``findings``.

    With ``as_delta`` (the default) *migrations*, in the order given, are one delta;
    otherwise each script is linted alone. With ``enabled=False`` (execution-only
    analysis mode) each script gets ``DISABLED_ANALYSIS`` and nothing is read.
    """
    analysed: Dict[str, Dict[str, Any]] = {}
    created: Set[str] = set()
    for migration in migrations:
        if getattr(migration, "type", None) not in _ANALYSED_TYPES:
            continue
        name = getattr(migration, "script_name", None)
        if not name:
            continue
        if not enabled:
            analysed[name] = dict(DISABLED_ANALYSIS)
            continue
        content = getattr(migration, "content", None)
        if not content and hasattr(migration, "load_content"):
            try:
                migration.load_content()
            except Exception as error:
                log.debug(f"Could not read {name} for analysis: {error}")
            content = getattr(migration, "content", None)
        if not content:
            continue
        try:
            analysis = analyse_script(content, dialect)
            verdict = lint_analysis(analysis, content, dialect, name, created_before=created)
            if as_delta:
                created |= verdict.created_tables
            analysed[name] = {
                **analysis.to_dict(),
                "verdict": verdict.verdict,
                "findings": [f.to_dict() for f in verdict.findings],
            }
        except Exception as error:
            log.debug(f"Could not analyse {name}: {error}")
    return analysed

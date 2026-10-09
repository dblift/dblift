"""``validate-sql``: a verdict for each migration script, from its findings."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, FrozenSet, Iterable, List, Sequence, Set, Tuple

from dblift.core.migration.migration_types import MigrationType
from dblift.core.migration.placeholders.placeholder_service import PlaceholderService
from dblift.core.migration.sql.script_analysis import ScriptAnalysis, analyse_script

# ``lint_rules`` needs sqlglot, so it is imported where a rule runs: ``info`` and ``migrate``
# import this module and must load without sqlglot.
if TYPE_CHECKING:
    from dblift.core.migration.sql.lint_rules import Finding

SAFE = "SAFE"
REVIEW = "REVIEW"
UNSAFE = "UNSAFE"

_ANALYSED_TYPES = (MigrationType.SQL, MigrationType.REPEATABLE)
_ALLOW = re.compile(r"--\s*dblift:allow\s+([A-Za-z0-9-]+(?:\s*,\s*[A-Za-z0-9-]+)*)", re.IGNORECASE)


@dataclass(frozen=True)
class ScriptLint:
    """The verdict for one script, with the findings and parse errors behind it."""

    script: str
    verdict: str
    findings: Tuple[Finding, ...]
    errors: Tuple[str, ...]

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
    analysis: ScriptAnalysis, text: str, dialect: str, script: str = ""
) -> ScriptLint:
    """Verdict for a script already analysed, honouring its ``dblift:allow`` comments."""
    from dblift.core.migration.sql.lint_rules import find_issues

    allowed = allowed_codes(text)
    findings = tuple(replace(f, allowed=f.code in allowed) for f in find_issues(analysis, dialect))
    return ScriptLint(script, verdict_of(findings, analysis.errors), findings, analysis.errors)


def lint_script(text: str, dialect: str, script: str = "") -> ScriptLint:
    """Analyse *text* and return its verdict."""
    return lint_analysis(analyse_script(text, dialect), text, dialect, script)


def lint_files(
    paths: Sequence[Path], dialect: str, placeholders: Dict[str, Any], log: Any
) -> List[ScriptLint]:
    """Lint each file after substituting the configured placeholders."""
    substitution = PlaceholderService(placeholders, log)
    results = []
    for path in paths:
        text = substitution.replace_placeholders(path.read_text(encoding="utf-8"))
        results.append(lint_script(text, dialect, path.name))
    return results


def lint_pending_scripts(
    migrations: Iterable[Any], dialect: str, log: Any
) -> Dict[str, Dict[str, Any]]:
    """``{script_name: analysis}`` for the SQL and repeatable scripts of *migrations*
    that have text, each analysis carrying the script's ``verdict`` and ``findings``.
    """
    analysed: Dict[str, Dict[str, Any]] = {}
    for migration in migrations:
        if getattr(migration, "type", None) not in _ANALYSED_TYPES:
            continue
        name = getattr(migration, "script_name", None)
        if not name:
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
            verdict = lint_analysis(analysis, content, dialect, name)
            analysed[name] = {
                **analysis.to_dict(),
                "verdict": verdict.verdict,
                "findings": [f.to_dict() for f in verdict.findings],
            }
        except Exception as error:
            log.debug(f"Could not analyse {name}: {error}")
    return analysed

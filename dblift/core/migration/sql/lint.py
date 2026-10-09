"""``validate-sql``: a verdict for each migration script, from its findings."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Sequence, Set, Tuple

from dblift.core.migration.placeholders.placeholder_service import PlaceholderService
from dblift.core.migration.sql.lint_rules import ERROR, Finding, find_issues
from dblift.core.migration.sql.script_analysis import ScriptAnalysis, analyse_script

SAFE = "SAFE"
REVIEW = "REVIEW"
UNSAFE = "UNSAFE"

_ALLOW = re.compile(r"--\s*dblift:allow\s+([A-Za-z0-9-]+(?:\s*,\s*[A-Za-z0-9-]+)*)", re.IGNORECASE)


@dataclass(frozen=True)
class ScriptLint:
    script: str
    verdict: str
    findings: Tuple[Finding, ...]
    errors: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
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
    counted = [f for f in findings if not f.allowed]
    if any(f.severity == ERROR for f in counted):
        return UNSAFE
    if counted or errors:
        return REVIEW
    return SAFE


def lint_analysis(
    analysis: ScriptAnalysis, text: str, dialect: str, script: str = ""
) -> ScriptLint:
    allowed = allowed_codes(text)
    findings = tuple(replace(f, allowed=f.code in allowed) for f in find_issues(analysis, dialect))
    return ScriptLint(script, verdict_of(findings, analysis.errors), findings, analysis.errors)


def lint_script(text: str, dialect: str, script: str = "") -> ScriptLint:
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

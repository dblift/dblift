"""Run a script through the production splitting entry point and compare outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Iterable, Optional

if TYPE_CHECKING:  # pragma: no cover
    from tests.support.splitter_spec.spec_tables import Expectation

ANY_ERROR = "error"


def normalize(statements: Iterable[str]) -> tuple[str, ...]:
    """Strip each statement, remove one trailing ``;``, strip again. Nothing else."""
    out = []
    for statement in statements:
        text = statement.strip()
        if text.endswith(";"):
            text = text[:-1].strip()
        out.append(text)
    return tuple(out)


@dataclass(frozen=True)
class SplitOutcome:
    statements: tuple[str, ...]
    error: Optional[str] = None
    detail: Optional[str] = None

    def matches(self, expectation: "Expectation") -> bool:
        if expectation.error is not None:
            if self.error is None:
                return False
            return expectation.error == ANY_ERROR or self.error == expectation.error
        if self.error is not None or expectation.statements is None:
            return False
        return normalize(self.statements) == normalize(expectation.statements)


@lru_cache(maxsize=None)
def _analyzer(dialect: str):  # type: ignore[no-untyped-def]
    from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer

    return SqlAnalyzer(dialect)


def split_script(dialect: str, script: str) -> SplitOutcome:
    """Split ``script`` as ``migrate`` would for ``dialect``; never raises."""
    try:
        statements = _analyzer(dialect).split_statements(script)
    except Exception as exc:  # noqa: BLE001 - the harness records every exception class
        return SplitOutcome(statements=(), error=type(exc).__name__, detail=str(exc))
    return SplitOutcome(statements=tuple(statements))

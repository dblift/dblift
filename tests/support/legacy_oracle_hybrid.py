"""Parsers bound to Oracle, which the plugin no longer serves.

Oracle reads statement facts, so ``HybridParser("oracle")`` and ``SqlGlotParser("oracle")`` refuse to
construct. Their regex and sqlglot helpers are dialect-neutral and keep their own tests; they build the
instances with the facts reader switched off.
"""

from contextlib import contextmanager
from typing import Iterator
from unittest.mock import patch

from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.db.plugins.oracle.quirks import OracleQuirks
from tests.support.legacy_sqlserver_parsers import legacy_sqlserver_hybrid


@contextmanager
def oracle_facts_off() -> Iterator[None]:
    """Build Oracle parsers as the plugin served them before statement facts."""
    with patch.object(OracleQuirks, "statement_facts_class", None):
        yield


def legacy_oracle_hybrid() -> HybridParser:
    """Return a ``HybridParser`` for Oracle, as the plugin served it before statement facts."""
    with oracle_facts_off():
        return HybridParser("oracle")


def hybrid_for(dialect: str) -> HybridParser:
    """``HybridParser(dialect)``, with Oracle and SQL Server served as they were before statement
    facts."""
    if dialect == "oracle":
        return legacy_oracle_hybrid()
    if dialect == "sqlserver":
        return legacy_sqlserver_hybrid()
    return HybridParser(dialect)

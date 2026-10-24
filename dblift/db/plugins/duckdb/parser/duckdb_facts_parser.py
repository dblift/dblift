"""DuckDB statement facts projected through the shared lexical engine."""

import re
from typing import Optional

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement_facts import (
    NamedObject,
    SqlglotStatementFactsReader,
    StatementFacts,
)
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC

_IDENTIFIER = r'(?:"(?:[^"]|"")+"|[A-Za-z_][\w$]*)'
# ``CREATE FUNCTION`` is DuckDB's alias of ``CREATE MACRO``: both define a macro named by the
# (optionally catalog- and schema-qualified) identifier before the parameter list.
_CREATE_MACRO_HEAD = re.compile(
    r"\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?(MACRO|FUNCTION)\s+"
    rf"(?:IF\s+NOT\s+EXISTS\s+)?({_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER}){{0,2}})\s*\(",
    re.IGNORECASE,
)
_QUALIFIER_PART = re.compile(_IDENTIFIER)
# What the shared reader reports for a macro it parses as a function but does not name. A macro it
# cannot parse at all (``b := 2`` in the parameter list) carries some other diagnostic.
_MACRO_OPAQUE = "duckdb macro identity and body are opaque to statement facts"


def _unquoted(identifier: str) -> str:
    return identifier[1:-1].replace('""', '"') if identifier.startswith('"') else identifier


def _created_macro(text: str, diagnostic: Optional[str]) -> Optional[NamedObject]:
    """The function a ``CREATE MACRO`` defines, or None when its head cannot be read."""
    head = _CREATE_MACRO_HEAD.match(text)
    if head is None:
        return None
    if diagnostic != _MACRO_OPAQUE and head.group(1).upper() != "MACRO":
        return None
    parts = [_unquoted(part) for part in _QUALIFIER_PART.findall(head.group(2))]
    schema = parts[-2] if len(parts) > 1 else None
    return NamedObject(parts[-1], SqlObjectType.FUNCTION, "created", schema)


class DuckDBStatementFactsReader(SqlglotStatementFactsReader):
    """Keep DuckDB comment semantics authoritative before reading the AST."""

    def read(self, sql: str) -> StatementFacts:
        """Read engine-selected SQL with nested comments removed."""
        text = LexicalEngine(DUCKDB_SPEC).blank_comments(sql)
        if not text.strip():
            return StatementFacts("UNKNOWN", "UNKNOWN")
        facts = super().read(text)
        if facts.operation == "CREATE" and facts.diagnostic is not None:
            macro = _created_macro(text, facts.diagnostic)
            if macro is not None:
                return StatementFacts("CREATE", "DDL", (macro,))
        return facts

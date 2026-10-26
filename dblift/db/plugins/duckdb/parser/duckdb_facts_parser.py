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
_SCHEMA_NAME = r"[A-Za-z_][A-Za-z0-9_$]*"
_SET_SCHEMA = re.compile(
    rf"\s*SET\s+(?:schema|search_path)\s*(?:=\s*|\s+)"
    rf"(?:'(?P<quoted>{_SCHEMA_NAME})'|(?P<bare>{_SCHEMA_NAME}))\s*;?\s*\Z",
    re.IGNORECASE,
)
_USE_SCHEMA = re.compile(rf"\s*USE\s+({_SCHEMA_NAME})\s*;?\s*\Z", re.IGNORECASE)
_RESET_SCHEMA = re.compile(r"\s*RESET\s+(?:schema|search_path)\s*;?\s*\Z", re.IGNORECASE)
_NULL_TABLE_COMMENT = re.compile(
    rf"\s*COMMENT\s+ON\s+TABLE\s+({_IDENTIFIER}(?:\s*\.\s*{_IDENTIFIER})?)\s+IS\s+NULL\s*;?\s*\Z",
    re.IGNORECASE,
)
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


def _schema_selection(text: str) -> Optional[StatementFacts]:
    """Expose a raw namespace selector, never a resolved table schema or catalog."""
    selected = _SET_SCHEMA.fullmatch(text)
    if selected is not None:
        return StatementFacts(
            "SET",
            "SESSION",
            target=selected.group("quoted") or selected.group("bare"),
            action="SELECT_NAMESPACE",
        )
    selected = _USE_SCHEMA.fullmatch(text)
    if selected is not None:
        return StatementFacts("USE", "SESSION", target=selected.group(1), action="SELECT_NAMESPACE")
    if _RESET_SCHEMA.fullmatch(text):
        return StatementFacts("RESET", "SESSION", action="RESET_NAMESPACE")
    return None


def _null_table_comment(text: str) -> Optional[StatementFacts]:
    """DuckDB removes a table comment with IS NULL, which SQLGlot does not parse strictly."""
    match = _NULL_TABLE_COMMENT.fullmatch(text)
    if match is None:
        return None
    parts = _QUALIFIER_PART.findall(match.group(1))
    name, schema = _unquoted(parts[-1]), _unquoted(parts[0]) if len(parts) == 2 else None
    return StatementFacts(
        "COMMENT",
        "DDL",
        (
            NamedObject(
                name,
                SqlObjectType.TABLE,
                "altered",
                schema,
                name_quoted=parts[-1].startswith('"'),
                schema_quoted=parts[0].startswith('"') if schema else None,
            ),
        ),
    )


class DuckDBStatementFactsReader(SqlglotStatementFactsReader):
    """Keep DuckDB comment semantics authoritative before reading the AST."""

    def read(self, sql: str) -> StatementFacts:
        """Read engine-selected SQL with nested comments removed."""
        text = LexicalEngine(DUCKDB_SPEC).blank_comments(sql)
        if not text.strip():
            return StatementFacts("UNKNOWN", "UNKNOWN")
        facts = super().read(text)
        if facts.opaque:
            if facts.operation in {"SET", "USE", "RESET"}:
                selected = _schema_selection(text)
                if selected is not None:
                    return selected
            if (
                facts.operation == "COMMENT"
                and facts.diagnostic == "duckdb grammar is not modelled for this statement"
            ):
                removed = _null_table_comment(text)
                if removed is not None:
                    return removed
        if facts.operation == "CREATE" and facts.diagnostic is not None:
            macro = _created_macro(text, facts.diagnostic)
            if macro is not None:
                return StatementFacts("CREATE", "DDL", (macro,))
        return facts

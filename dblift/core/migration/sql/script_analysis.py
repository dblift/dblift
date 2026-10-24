"""What a SQL script does, read from its text alone.

Built on the dialect's statement facts: the plugin's parser splits the script (procedural bodies,
dollar quotes, ``GO`` batches) and its facts reader classifies each statement.
Nothing here connects to a database or runs a statement, and nothing here raises into a command:
a script the parser cannot read yields ``errors`` and no cautions.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterator, List, Optional, Tuple

from dblift.core.exceptions import (
    ParserError,
    UnsafeStatementSplitError,
    UnsupportedMetaCommandError,
)
from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.common.comment_stripping import strip_comments_preserving_quotes
from dblift.core.sql_parser.statement_facts import DmlEffect, StatementFacts
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser
from dblift.db.dml_analysis import strip_leading_sql_comments
from dblift.db.provider_registry import ProviderRegistry

DESTROYS = "destroys"
CHANGES_ROWS = "changes_rows"
SNIPPET = 120
_FIRST_WORD = re.compile(r"^([A-Za-z]+)")
_DROP_COLUMN = re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE)
_DROP_KEYWORD = re.compile(
    r"^\s*DROP\s+(TABLE|MATERIALIZED\s+VIEW(?!\s+LOG\b)|VIEW|SCHEMA|DATABASE(?!\s+LINK\b))\b",
    re.IGNORECASE,
)
# Objects whose DROP removes a definition, never rows, even when the statement's name could not be
# read (each is documented so by its vendor; see the lint-rule tests). CASCADE or FORCE can drop or
# disable dependent columns, so a statement holding either is not row-free. An extension owns
# tables (pg_cron, postgis) and an event table holds rows, so neither is listed.
_ROW_FREE_DROP = re.compile(
    r"^\s*DROP\s+(?:PUBLIC\s+)?(?:INDEX|SEQUENCE|FUNCTION|PROCEDURE|ROUTINE|TRIGGER|TYPE|DOMAIN"
    r"|ROLE|USER|POLICY|RULE|PUBLICATION|SERVER|COLLATION|CAST|AGGREGATE|LANGUAGE|EVENT(?!\s+TABLE)"
    r"|SYNONYM|PACKAGE|DIRECTORY|PROFILE|LOGIN|DEFAULT|ASSEMBLY|MACRO|NICKNAME|LIBRARY|GROUP"
    r"|DATABASE\s+LINK|MATERIALIZED\s+VIEW\s+LOG)\b",
    re.IGNORECASE,
)
_DROP_DEPENDENTS = re.compile(r"\b(?:CASCADE|FORCE)\b", re.IGNORECASE)
# Objects whose DROP discards rows; dropping an index, a sequence or a routine does not.
_DATA_HOLDERS = frozenset(
    {
        SqlObjectType.TABLE.value,
        SqlObjectType.VIRTUAL_TABLE.value,
        SqlObjectType.VIEW.value,
        SqlObjectType.MATERIALIZED_VIEW.value,
        SqlObjectType.SCHEMA.value,
        SqlObjectType.DATABASE.value,
    }
)
# The statements the facts reader may leave unread and ``statement-not-analysed`` still passes,
# recognised by their head keyword. Each changes no row and no object definition:
#   SET / USE / SAVEPOINT / RELEASE / ROLLBACK / COMMIT / START TRANSACTION, and a bare BEGIN or
#     END carrying only transaction modes: session and transaction state. SET stops at what
#     changes the server or an account (MySQL SET GLOBAL / PERSIST / PERSIST_ONLY / PASSWORD, in
#     the keyword form, as @@GLOBAL.x, or after a comma). BEGIN ... END,
#     BEGIN ATOMIC and DECLARE are procedural blocks and never match.
#   SHOW / DESCRIBE / DESC: metadata listings.
#   PRAGMA: SQLite connection and database settings, read or set.
#   GRANT / REVOKE / DENY: privileges, not data or definitions.
#   COMMENT ON: documentation text.
#   ANALYZE / ANALYSE: refreshes optimiser statistics.
#   EXPLAIN: shows a plan, except EXPLAIN ANALYZE, which runs the statement.
#   VACUUM: reclaims space, except VACUUM FULL (FULL not switched off), which rewrites the table.
#   LOCK / UNLOCK: take or release locks and change nothing; the PostgreSQL lock rules judge them.
# The head is matched on the statement without its comments, and a MySQL or MariaDB executable
# comment (/*! ... */, /*M! ... */, which the server runs) disables the list altogether.
# REINDEX, CALL, EXEC, anything else unrecognised: not listed, so reported.
_NON_DATA_HEAD = re.compile(
    r"^(?:"
    r"SET\b(?!\s+(?:GLOBAL|PERSIST|PERSIST_ONLY|PASSWORD)\b)"
    r"(?!.*(?:@@\s*(?:GLOBAL|PERSIST|PERSIST_ONLY)\s*\.|,\s*(?:GLOBAL|PERSIST|PERSIST_ONLY)\b))"
    r"|USE\b|SHOW\b|DESC(?:RIBE)?\b|PRAGMA\b|GRANT\b|REVOKE\b|DENY\b|COMMENT\s+ON\b"
    r"|ANALY[SZ]E\b"
    r"|EXPLAIN\b(?!\s*(?:\(.*?\b)?ANALY[SZ]E\b)"
    r"|VACUUM\b(?!\s*(?:\([^)]*?\b|(?:(?:FREEZE|VERBOSE|ANALY[SZ]E)\s+)*)"
    r"FULL\b(?!\s+(?:FALSE|OFF|0)\b))"
    r"|LOCK\b|UNLOCK\b"
    r"|SAVEPOINT\b|RELEASE\b|ROLLBACK\b|COMMIT\b|START\s+TRANSACTION\b"
    r"|(?:BEGIN|END)(?:\s+(?:TRAN(?:SACTION)?(?:\s+[\w@#$]+)?|WORK|DEFERRED|IMMEDIATE|EXCLUSIVE"
    r"|ISOLATION\s+LEVEL\s+[A-Za-z ]+?|READ\s+(?:ONLY|WRITE)|(?:NOT\s+)?DEFERRABLE))*"
    r"(?:\s|;|--[^\n]*|/\*.*?\*/)*$"
    r")",
    re.IGNORECASE | re.DOTALL,
)
# MySQL (/*! ... */) and MariaDB (/*M! ... */) run the text of these comments.
_EXECUTABLE_COMMENTS = ("/*!", "/*M!")
_PROCEDURAL_OPERATIONS = frozenset({"BEGIN", "DECLARE", "DO"})
_SCHEMA_HOLDERS = frozenset({SqlObjectType.SCHEMA.value, SqlObjectType.DATABASE.value})
_ROW_HOLDERS = frozenset(
    {
        SqlObjectType.TABLE.value,
        SqlObjectType.VIRTUAL_TABLE.value,
        SqlObjectType.MATERIALIZED_VIEW.value,
    }
)
DISABLED_ANALYSIS = {
    "status": "disabled",
    "reason": "Object analysis disabled in execution mode",
}
_SQLGLOT_LOG = logging.getLogger("sqlglot")


@dataclass(frozen=True)
class AnalysedObject:
    """An object a statement names: its type (a ``SqlObjectType`` value), name and schema."""

    type: str
    name: str
    schema: Optional[str]


@dataclass(frozen=True)
class AnalysedStatement:
    """One statement of a script: its leading keyword, kind, objects and full-table DML flag."""

    index: int
    operation: str
    kind: str
    objects: Tuple[AnalysedObject, ...]
    full_table: bool
    snippet: str
    # The whole statement, for rules that parse it; not part of the JSON payload.
    sql: str = field(default="", repr=False, compare=False)
    # True when the statement names no object because its names could not be trusted (facts:
    # opaque with no affected object; otherwise the legacy unreadable-name check); not part of
    # the JSON payload.
    names_unread: bool = field(default=False, repr=False, compare=False)
    # Why the facts reader left the statement unread (``statement-not-analysed``), or None when
    # it read it or it is a session or transaction envelope; not part of the JSON payload.
    unread: Optional[str] = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class Caution:
    """Why a statement deserves a second look: ``destroys`` or ``changes_rows``, and the reason."""

    level: str
    statement: int
    reason: str
    # The ``validate-sql`` rule this caution stands for, or None when it only describes.
    code: Optional[str] = None


@dataclass(frozen=True)
class ScriptAnalysis:
    """What a script does: its statements, the cautions among them, and the parser's errors."""

    statements: Tuple[AnalysedStatement, ...]
    cautions: Tuple[Caution, ...]
    errors: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        """The analysis as plain lists and dicts, ready for ``--format json``."""
        return {
            "statements": [
                {
                    "index": s.index,
                    "operation": s.operation,
                    "kind": s.kind,
                    "objects": [
                        {"type": o.type, "name": o.name, "schema": o.schema} for o in s.objects
                    ],
                    "full_table": s.full_table,
                    "snippet": s.snippet,
                }
                for s in self.statements
            ],
            "cautions": [
                {"level": c.level, "statement": c.statement, "reason": c.reason, "code": c.code}
                for c in self.cautions
            ],
            "errors": list(self.errors),
        }


def operation_of(statement: str) -> str:
    """The statement's leading keyword, upper-cased, after any leading comments."""
    text = strip_leading_sql_comments(statement).lstrip()
    match = _FIRST_WORD.match(text)
    return match.group(1).upper() if match else "UNKNOWN"


def dialect_of(config: Any) -> Optional[str]:
    """The configured database type, lower-cased, or ``None``."""
    database = getattr(config, "database", None)
    kind = getattr(database, "type", None)
    return str(kind).lower() if kind else None


@contextmanager
def quiet_sqlglot() -> Iterator[None]:
    """Keep sqlglot's warnings (one per statement it falls back on) off the caller's log.

    The analysis reports what it could not read; it needs no sqlglot import to do this.
    """
    previous = _SQLGLOT_LOG.level
    _SQLGLOT_LOG.setLevel(logging.ERROR)
    try:
        yield
    finally:
        _SQLGLOT_LOG.setLevel(previous)


def analyse_script(text: str, dialect: str) -> ScriptAnalysis:
    """Analyse one script's text in *dialect*.

    A script the parser refuses, or a plugin whose facts parser cannot be built
    (``ParserError``, ``ValueError`` or ``TypeError``), comes back as ``errors``;
    any other failure, such as a reader raising while reading a statement, propagates.
    """
    with quiet_sqlglot():
        return _analyse(text, dialect)


def _analyse(text: str, dialect: str) -> ScriptAnalysis:
    quirks = ProviderRegistry.get_quirks(dialect)
    if not quirks.supports_statement_facts:
        return ScriptAnalysis((), (), (f"statement facts unavailable for dialect '{dialect}'",))
    spec = quirks.lexical_spec()
    script_rules = spec.delimiter_script if spec else None
    hash_comment = script_rules.hash_comment if script_rules else None
    fact_statements: List[AnalysedStatement] = []
    fact_cautions: List[Caution] = []
    errors: List[str] = []
    try:
        bodies = StatementFactsParser(quirks).split_for_analysis(text)
    except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as error:
        return ScriptAnalysis((), (), (f"Error splitting SQL: {error}",))
    except (ParserError, ValueError, TypeError) as error:
        # No parser could be built from the plugin's facts reader and spec.
        return ScriptAnalysis((), (), (f"parser error: {error}",))
    for body in bodies:
        facts = quirks.statement_facts(body)
        objects = tuple(
            AnalysedObject(obj.type.value, obj.name, obj.schema) for obj in facts.affected_objects
        )
        operation = facts.operation
        outer_full_table = facts.kind == "DML" and (
            facts.operation in ("UPDATE", "DELETE") and (not facts.predicate)
        )
        full_table = outer_full_table or any(_rewrites_every_row(w) for w in facts.cte_writes)
        analysed = AnalysedStatement(
            len(fact_statements),
            operation,
            facts.kind,
            objects,
            full_table,
            _snippet(body),
            sql=body,
            names_unread=facts.opaque and not facts.affected_objects,
            unread=_unread_reason(facts, body, hash_comment),
        )
        fact_statements.append(analysed)
        caution = _caution_for(
            replace(
                analysed,
                full_table=outer_full_table,
                # a writing CTE's table is named by its own caution, not by the outer one
                objects=analysed.objects[:1] if facts.cte_writes and facts.target else objects,
            ),
            body,
            _opaque_dialect(dialect) if facts.opaque else None,
            # a plugin without a sqlglot dialect has no second reader to name an unread target
            name_target=not (analysed.names_unread and quirks.sqlglot_dialect is None),
        )
        if caution is None and facts.opaque and facts.kind == "DML" and facts.target is None:
            # A data-changing CTE leaves no readable target; its outer table still changes.
            altered = tuple(
                AnalysedObject(o.type.value, o.name, o.schema)
                for o in facts.affected_objects
                if o.type == SqlObjectType.TABLE and o.role == "altered"
            )
            if altered:
                caution = Caution(
                    CHANGES_ROWS,
                    analysed.index,
                    f"{operation} changes rows of {_names(altered)}",
                )
        if caution is not None:
            fact_cautions.append(caution)
        fact_cautions.extend(_cte_write_cautions(analysed.index, facts.cte_writes))
        if facts.action in _SERVER_SIDE_COPY:
            fact_cautions.append(
                Caution(
                    CHANGES_ROWS,
                    analysed.index,
                    _SERVER_SIDE_COPY[facts.action],
                    "copy-server-side",
                )
            )
        if facts.error:
            errors.append(facts.error)
    return ScriptAnalysis(tuple(fact_statements), tuple(fact_cautions), tuple(errors))


def without_comments(body: str, hash_comment: Optional[str] = None) -> str:
    """*body* without its comments (quoted text kept), the way the lock rules read a statement.

    *hash_comment* is the dialect's extra line-comment prefix (``#`` for MySQL), if it has one.
    """
    return strip_comments_preserving_quotes(
        body,
        line_prefixes=["--", hash_comment] if hash_comment else ["--"],
        has_block_comments=True,
        nested_block_comments=True,
        supports_dollar_quoting=True,
        block_comment_replacement=" ",
    )


def _unread_reason(
    facts: StatementFacts, body: str, hash_comment: Optional[str] = None
) -> Optional[str]:
    """Why a statement the facts reader did not read needs a look, or None.

    Unread is a statement of unknown kind or one that is opaque and names no object.
    The ``_NON_DATA_HEAD`` statements are exempt (the splitter drops comment-only text) and a
    DROP is judged by its keyword. A definition (``CREATE PROCEDURE``) that names its object is
    read as one.
    """
    if not (facts.kind == "UNKNOWN" or (facts.opaque and not facts.affected_objects)):
        return None
    if facts.operation == "DROP":
        return None  # judged by its keyword (``_unnamed_drop_caution``): row-free kinds stay safe
    text = without_comments(body, hash_comment)
    if not any(opener in body for opener in _EXECUTABLE_COMMENTS) and _NON_DATA_HEAD.match(text):
        return None
    detail = f" ({facts.diagnostic})" if facts.diagnostic else ""
    if facts.operation in _PROCEDURAL_OPERATIONS or re.match(
        r"EXECUTE\s+IMMEDIATE\b", text, re.IGNORECASE
    ):
        return f"procedural block: effects not modelled{detail}; review it by hand"
    return f"{facts.operation} statement not analysed{detail}; review it by hand"


_SERVER_SIDE_COPY = {
    "copy-to-program": "COPY TO PROGRAM runs a shell command on the database server",
    "copy-from-program": "COPY FROM PROGRAM runs a shell command on the database server",
    "copy-to-file": "COPY TO a file writes a file on the database server",
}


def _rewrites_every_row(write: DmlEffect) -> bool:
    return write.operation in ("UPDATE", "DELETE") and not write.predicate


def _cte_write_cautions(index: int, writes: Tuple[DmlEffect, ...]) -> List[Caution]:
    """One caution per UPDATE or DELETE a CTE performs, as for the statement written alone."""
    return [
        (
            Caution(
                DESTROYS,
                index,
                f"{write.operation} without WHERE rewrites every row of {write.target}",
                "dml-no-where",
            )
            if _rewrites_every_row(write)
            else Caution(CHANGES_ROWS, index, f"{write.operation} changes rows of {write.target}")
        )
        for write in writes
        if write.operation in ("UPDATE", "DELETE")
    ]


def _opaque_dialect(dialect: str) -> str:
    """The sqlglot dialect an unreadable statement is cautioned in (Db2 declares none)."""
    mapping = ProviderRegistry.get_quirks(dialect).sqlglot_dialect
    if mapping:
        return mapping
    for name in sorted(plugin.name for plugin in ProviderRegistry.list_plugins()):
        quirks = ProviderRegistry.get_quirks(name)
        if quirks.is_default_sqlglot_read_fallback:
            return quirks.sqlglot_dialect or ""
    return ""


def _snippet(body: str) -> str:
    # Some splitters keep the statement's ``;`` and some drop it; the snippet never shows it.
    flat = " ".join(body.rstrip().rstrip(";").split())
    return flat if len(flat) <= SNIPPET else flat[: SNIPPET - 1] + "…"


def _names(objects: Tuple[AnalysedObject, ...]) -> str:
    names = [f"{o.schema}.{o.name}" if o.schema else o.name for o in objects if o.name]
    return ", ".join(names) if names else "its target"


def _unnamed_drop_caution(stmt: AnalysedStatement, body: str) -> Optional[Caution]:
    """The caution of a DROP whose object could not be named, from its keyword alone."""
    match = _DROP_KEYWORD.match(strip_leading_sql_comments(body))
    if match is None:
        unread = strip_leading_sql_comments(body)
        if _ROW_FREE_DROP.match(unread) and not _DROP_DEPENDENTS.search(unread):
            return None
        return Caution(
            DESTROYS,
            stmt.index,
            "DROP discards an object whose kind or name could not be read",
            "drop-unread-object",
        )
    kind = " ".join(match.group(1).upper().split())
    code = {"SCHEMA": "drop-schema", "DATABASE": "drop-schema", "VIEW": None}.get(
        kind, "drop-table"
    )
    return Caution(
        DESTROYS,
        stmt.index,
        f"DROP {kind} discards a {kind.lower()} whose name could not be read, and its rows",
        code,
    )


def _caution_for(
    stmt: AnalysedStatement,
    body: str,
    opaque_dialect: Optional[str] = None,
    name_target: bool = True,
) -> Optional[Caution]:
    op = stmt.operation
    if op == "TRUNCATE":
        return Caution(DESTROYS, stmt.index, f"TRUNCATE empties {_names(stmt.objects)}", "truncate")
    if op == "DROP":
        held = tuple(o for o in stmt.objects if o.type in _DATA_HOLDERS)
        if not held:
            return _unnamed_drop_caution(stmt, body) if opaque_dialect else None
        if any(o.type in _SCHEMA_HOLDERS for o in held):
            code: Optional[str] = "drop-schema"
        elif any(o.type in _ROW_HOLDERS for o in held):
            code = "drop-table"
        else:
            code = None
        return Caution(
            DESTROYS,
            stmt.index,
            f"DROP {held[0].type.replace('_', ' ')} discards {_names(held)} and its rows",
            code,
        )
    if op == "ALTER" and _DROP_COLUMN.search(body):
        return Caution(
            DESTROYS,
            stmt.index,
            f"DROP COLUMN discards a column of {_names(stmt.objects)}",
            "drop-column",
        )
    if op in ("UPDATE", "DELETE") or (op == "WITH" and stmt.kind == "DML"):
        if stmt.full_table and opaque_dialect:
            from dblift.core.sql_parser.sqlglot_statement_facts import readable_dml_target

            target = readable_dml_target(body, dialect=opaque_dialect) if name_target else None
            return Caution(
                DESTROYS,
                stmt.index,
                f"{op}: the predicate could not be read; treated as changing every row"
                + (f" of {target}" if target else ""),
                "dml-no-where",
            )
        if stmt.full_table:
            return Caution(
                DESTROYS,
                stmt.index,
                f"{op} without WHERE rewrites every row of {_names(stmt.objects)}",
                "dml-no-where",
            )
        return Caution(CHANGES_ROWS, stmt.index, f"{op} changes rows of {_names(stmt.objects)}")
    if op == "MERGE":
        return Caution(CHANGES_ROWS, stmt.index, f"MERGE changes rows of {_names(stmt.objects)}")
    return None

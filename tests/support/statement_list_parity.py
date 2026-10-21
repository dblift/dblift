"""One script, one list of statements: the shapes, the reference and the consumer views.

The reference is built from the splitter's own records; the few shapes whose execution list
carries client text (a directive rendered with its terminator, a COPY payload, a repeated batch)
state that list literally, so the reference never reads the function a consumer is changed to
read. Every view runs the production code path a consumer takes, so a consumer that re-classifies
what the splitter returned shows up as a cell whose view differs from the reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Type
from unittest.mock import MagicMock, patch

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.logger import NullLog
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.placeholders.placeholder_service import PlaceholderService
from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql import lint_rules
from dblift.core.migration.sql.execution_statement import _statements_of
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
from dblift.core.sql_model.base import ParseResult
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement import Statement
from dblift.db.provider_registry import ProviderRegistry
from tests.unit._migration_factory import make_migration

DIALECTS: Tuple[str, ...] = (
    "postgresql",
    "cockroachdb",
    "yugabytedb",
    "redshift",
    "oracle",
    "sqlserver",
    "mysql",
    "mariadb",
    "db2",
    "sqlite",
    "duckdb",
    "snowflake",
)
PSQL_WIRE = ("postgresql", "cockroachdb", "yugabytedb", "redshift")
REFUSALS = (UnsafeStatementSplitError, UnsupportedMetaCommandError)

S1 = "SELECT 1"
S2 = "SELECT 2"


@dataclass(frozen=True)
class Shape:
    """A script and the dialects it has a meaning on (``None``: all twelve).

    ``execution`` is set for the shapes whose execution list is not the records' text (a client
    directive rendered with its terminator, a COPY payload, a repeated batch): the literal list
    execution sends, the same on every dialect the shape applies to. ``exact`` keeps the trailing
    ``;`` of a statement when comparing (a routine body ends in the ``;`` of its ``END;``).
    """

    name: str
    script: str
    dialects: Optional[Tuple[str, ...]] = None
    execution: Optional[Tuple[str, ...]] = None
    sent: Optional[Tuple[str, ...]] = None
    exact: bool = False

    def applies_to(self, dialect: str) -> bool:
        return self.dialects is None or dialect in self.dialects


def _middle(name: str, piece: str) -> Shape:
    return Shape(name, f"{S1};\n{piece}\n{S2};")


def _tail(name: str, piece: str) -> Shape:
    return Shape(name, f"{S1};\n{piece}")


_MIDDLE = (
    ("empty_term", ";"),
    ("blank_term", " \t ;"),
    ("kept_nbsp_term", "\xa0;"),
    ("kept_ideo_term", "　;"),
    ("kept_c0_term", "\x1c;"),
    ("line_cmt_term", "-- c\n;"),
    ("block_cmt_term", "/* c */;"),
    ("nested_cmt_term", "/* a /* b */ c */;"),
    ("hash_cmt_term", "# c\n;"),
    ("ctrl_hash_term", "\x1c # c\n;"),
    ("kept_cmt_term", "\xa0 -- c\n;"),
    ("execcmt_term", "/*!40101 SET @a=1 */;"),
)
_TAIL = (
    ("tail_nbsp", "\xa0"),
    ("tail_ideo", "　"),
    ("tail_c0", "\x1c"),
    ("tail_line_cmt", "-- tail"),
    ("tail_block_cmt", "/* tail */"),
    ("tail_hash_cmt", "# tail"),
    ("tail_nested_cmt", "/* a /* b */ c */"),
)

SHAPES: Tuple[Shape, ...] = (
    *(_middle(name, piece) for name, piece in _MIDDLE),
    Shape("cmt_then_sql", "-- see /* x\nCREATE TABLE t (a int);"),
    Shape("unclosed_block", f"{S1};\n/* never closed"),
    Shape("unclosed_only", "/* never closed"),
    Shape("tail_blank", f"{S1};\n  \n"),
    *(_tail(name, piece) for name, piece in _TAIL),
    Shape("only_cmt", "-- only a comment\n"),
    Shape("only_empty", ""),
    Shape("only_blank", " \n\t\n"),
    Shape("batch_only_semi", f"{S1}\nGO\n;\nGO\n{S2}", ("sqlserver",)),
    Shape("batch_only_cmt", f"{S1}\nGO\n-- c\nGO\n{S2}", ("sqlserver",)),
    _middle("slash_cmt_term", "// c\n;"),
    Shape("go_go", f"{S1}\nGO\nGO\n{S2}\nGO", ("sqlserver",)),
    # What the projections carry besides plain statements.
    Shape(
        "directive_psql",
        f"{S1};\n\\restrict k\n{S2};\n\\unrestrict k",
        PSQL_WIRE,
        execution=("SELECT 1;", "SELECT 2;"),
    ),
    Shape(
        "directive_oracle",
        f"{S1};\nWHENEVER SQLERROR CONTINUE;\n{S2};",
        ("oracle",),
        execution=("SELECT 1;", "WHENEVER SQLERROR CONTINUE;", "SELECT 2;"),
        sent=("SELECT 1;", "SELECT 2;"),
    ),
    Shape(
        "directive_delimiter",
        f"DELIMITER //\n{S1}//\nDELIMITER ;\n{S2};",
        ("mysql", "mariadb"),
        execution=("SELECT 1", "SELECT 2"),
    ),
    Shape(
        "copy_stdin",
        f"COPY t FROM STDIN;\n1\t2\n\\.\n{S2};",
        # Redshift rejects COPY ... FROM STDIN (docs/sql-parsing/redshift.md): no data block.
        tuple(d for d in PSQL_WIRE if d != "redshift"),
        execution=("COPY t FROM STDIN;\n1\t2\n", "SELECT 2;"),
    ),
    Shape(
        "go_n",
        f"{S1}\nGO 3\n{S2}",
        ("sqlserver",),
        execution=("SELECT 1", "SELECT 1", "SELECT 1", "SELECT 2"),
    ),
    Shape(
        "directive_oracle_exit",
        f"{S1};\nWHENEVER SQLERROR EXIT\n{S2};",
        ("oracle",),
        execution=("SELECT 1;", "WHENEVER SQLERROR EXIT;", "SELECT 2;"),
        sent=("SELECT 1;", "SELECT 2;"),
    ),
    Shape(
        "directive_oracle_prompt",
        f"{S1};\nPROMPT hi\n{S2};",
        ("oracle",),
        execution=("SELECT 1;", "SELECT 2;"),
    ),
    Shape(
        "directive_oracle_set",
        f"{S1};\nSET SERVEROUTPUT ON\n{S2};",
        ("oracle",),
        execution=("SELECT 1;", "SELECT 2;"),
    ),
    Shape(
        "exec_oracle",
        'EXEC dbms_output.put_line("x")\nSELECT 1 FROM dual;',
        ("oracle",),
        execution=('BEGIN dbms_output.put_line("x"); END;', "SELECT 1 FROM dual;"),
    ),
    # A routine body holds a ``;`` that is not a terminator, and may end in one.
    Shape("body_oracle", "BEGIN NULL; END;\n/", ("oracle",), exact=True),
    Shape(
        "body_mysql",
        f"DELIMITER //\nCREATE PROCEDURE p() BEGIN SELECT 1; END//\nDELIMITER ;\n{S2};",
        ("mysql", "mariadb"),
    ),
    Shape(
        "delimiter_two",
        f"DELIMITER //\n{S1}; {S2}//\nDELIMITER ;\nSELECT 3;",
        ("mysql", "mariadb"),
    ),
    Shape(
        "body_postgres",
        "CREATE FUNCTION f() RETURNS int AS $$ BEGIN RETURN 1; END; $$ LANGUAGE plpgsql;\n"
        f"{S2};",
        PSQL_WIRE,
    ),
)

#: Every (dialect, shape) pair that has a meaning, in a stable order.
CELLS: Tuple[Tuple[str, Shape], ...] = tuple(
    (dialect, shape) for dialect in DIALECTS for shape in SHAPES if shape.applies_to(dialect)
)

_BLANKS = " \t\r\n"


def normalise(sql: str, exact: bool = False) -> str:
    """Outer ASCII blanks and (unless *exact*) one trailing ``;`` removed, nothing else."""
    text = sql.strip(_BLANKS)
    if text.endswith(";") and not exact:
        text = text[:-1].rstrip(_BLANKS)
    return text


@dataclass(frozen=True)
class Outcome:
    """What a view produced for a cell: statements, or the class and message of its refusal."""

    statements: Optional[Tuple[str, ...]] = None
    raised: Optional[Type[BaseException]] = None
    message: str = ""

    @classmethod
    def of(cls, produce: Callable[[], Sequence[str]], exact: bool = False) -> "Outcome":
        try:
            return cls(statements=tuple(normalise(sql, exact) for sql in produce()))
        except Exception as exc:  # a crash is a different outcome, never a silent pass
            return cls(raised=type(exc), message=str(exc))


def records(dialect: str, script: str) -> List[Statement]:
    """The splitter's default records for *script*."""
    spec = ProviderRegistry.get_quirks(dialect).lexical_spec()
    assert spec is not None
    return LexicalEngine(spec).split(script)


def _constituents(record: Statement) -> Tuple[str, ...]:
    if record.analysis_statements is not None:
        return tuple(record.analysis_statements)
    return (record.text,)


@dataclass(frozen=True)
class Reference:
    """What every consumer must see for one cell, derived from the records alone."""

    executed: Outcome  # what execution is handed: ``repeat`` copies of each statement
    sent: Outcome  # what the provider receives (``executed`` less the policy directives)
    units: Outcome  # one entry per executable record (what lint classifies)
    analysis: Outcome  # the constituents, once per record (what analysis reads)
    constituents: Outcome  # the constituents of what execution sends (``repeat`` copies)


def reference(dialect: str, shape: Shape) -> Reference:
    try:
        recs = records(dialect, shape.script)
    except REFUSALS as exc:
        refused = Outcome(raised=type(exc), message=str(exc))
        return Reference(refused, refused, refused, refused, refused)
    runnable = [r for r in recs if r.kind in ("sql", "copy_stdin") and r.repeat > 0]
    if shape.execution is not None:
        executed = list(shape.execution)
    else:
        executed = [r.text for r in runnable for _ in range(r.repeat)]
    exact = shape.exact
    sent = list(shape.sent) if shape.sent is not None else executed
    return Reference(
        executed=Outcome.of(lambda: executed, exact),
        sent=Outcome.of(lambda: sent, exact),
        units=Outcome.of(lambda: [r.text for r in runnable], exact),
        analysis=Outcome.of(lambda: [c for r in runnable for c in _constituents(r)], exact),
        constituents=Outcome.of(
            lambda: [c for r in runnable for _ in range(r.repeat) for c in _constituents(r)], exact
        ),
    )


# --- views: each runs the code a consumer runs -------------------------------------------------


class _RecordingProvider:
    """A provider that records what reaches it."""

    connection = None

    def __init__(self) -> None:
        self.sent: List[str] = []

    def execute_statement(self, statement: str, schema: Any = None, params: Any = None) -> int:
        self.sent.append(statement)
        return 0

    def execute_query(self, statement: str, params: Any = None) -> List[Dict[str, Any]]:
        self.sent.append(statement)
        return []


def _engine(dialect: str) -> Tuple[ExecutionEngine, _RecordingProvider]:
    provider = _RecordingProvider()
    analyzer = SqlAnalyzer(dialect=dialect)
    service = SqlExecutionService(
        provider, analyzer, quirks=ProviderRegistry.get_quirks(dialect), logger=NullLog()
    )
    engine = ExecutionEngine(
        provider=provider,
        sql_analyzer=analyzer,
        log=NullLog(),
        sql_execution_service=service,
        placeholder_service=PlaceholderService(logger=NullLog()),
    )
    return engine, provider


def _migration(dialect: str, script: str) -> Any:
    return make_migration(
        script_name="V1__t.sql", content=script, version="1", description="t", dialect=dialect
    )


def _prepared(engine: ExecutionEngine, dialect: str, script: str) -> List[str]:
    """What the engine hands execution: its real ``_prepare_sql_statements`` (placeholders,
    dialect, ``parse_migration_sql`` and the transaction-envelope check)."""
    return engine._prepare_sql_statements(
        _migration(dialect, script), placeholder_service=engine.placeholder_service
    )


def view_classified(dialect: str, script: str) -> List[str]:
    """The statements the transaction-mode policy classifies."""
    engine, _ = _engine(dialect)
    return [
        c.sql for c in engine._classify_execution_statements(_prepared(engine, dialect, script))
    ]


def view_executable(dialect: str, script: str) -> List[str]:
    """The list ``get_executable_sql_statements`` returns (dry-run, mixed-mode check).

    The engine turns a refusal into a result error; the view re-raises what the real
    ``_prepare_sql_statements`` raised.
    """
    engine, _ = _engine(dialect)
    real = engine._prepare_sql_statements
    refusal: List[BaseException] = []

    def prepare(*args: Any, **kwargs: Any) -> List[str]:
        try:
            return real(*args, **kwargs)
        except Exception as exc:
            refusal.append(exc)
            raise

    engine._prepare_sql_statements = prepare  # type: ignore[method-assign]
    statements = engine.get_executable_sql_statements(_migration(dialect, script), MagicMock())
    if refusal:
        raise refusal[0]
    return statements


def view_executed(dialect: str, script: str) -> List[str]:
    """What reaches the provider through ``_execute_statements`` and ``execute_statement``."""
    engine, provider = _engine(dialect)
    result = MagicMock()
    result.has_error.return_value = False
    engine._execute_statements(_prepared(engine, dialect, script), MagicMock(), result, 0.0)
    return provider.sent


def view_callback(dialect: str, script: str) -> List[str]:
    """What reaches the provider when the script runs as a callback."""
    engine, provider = _engine(dialect)
    engine.execute_callback(_migration(dialect, script))
    return provider.sent


def view_migrate_constituents(dialect: str, script: str) -> List[str]:
    """The constituents of the statements execution sends (a T-SQL batch divided).

    Only SQL Server runs a unit that holds several statements; for the others a unit is its own
    constituent and splitting it again would re-judge a lone piece out of its script.
    """
    return [
        part for unit in view_classified(dialect, script) for part in _statements_of(unit, dialect)
    ]


def view_analysis(dialect: str, script: str) -> List[str]:
    """``analyse_script(...).statements[].sql``; a refusal is its only error."""
    analysis = analyse_script(script, dialect)
    if not analysis.statements and analysis.errors:
        raise UnsafeStatementSplitError("; ".join(analysis.errors))
    return [statement.sql for statement in analysis.statements]


def _undo_input(dialect: str, script: str, *, parse_fails: bool) -> List[str]:
    generator = UndoScriptGenerator(dialect, logger=NullLog())
    migration = make_migration(
        script_name="V1__t.sql", content=script, version="1", description="t", dialect=dialect
    )
    seen: List[str] = []

    def facts(sql: str, _facts: Any) -> None:
        seen.append(sql)

    def parsed(stmt: Any) -> None:
        seen.append(getattr(stmt, "sql_text", ""))

    def text(sql: str, _source: Any = "") -> None:
        seen.append(sql)

    with (
        patch.object(generator, "_reverse_statement_facts", facts),
        patch.object(generator, "_review_statement_facts", facts),
        patch.object(generator, "_reverse_statement_from_parsed", parsed),
        patch.object(generator, "_reverse_statement", text),
    ):
        if parse_fails:
            failed = ParseResult(success=False, statements=[], errors=["forced"])
            with patch.object(generator.parser, "parse_sql", return_value=failed):
                generator._generate_undo_statements(migration)
        else:
            generator._generate_undo_statements(migration)
    return list(reversed(seen))


def view_undo(dialect: str, script: str) -> List[str]:
    """The undo input along the branch the dialect takes (facts, or ``parse_sql``)."""
    return _undo_input(dialect, script, parse_fails=False)


def view_undo_fallback(dialect: str, script: str) -> List[str]:
    """The undo input when ``parse_sql`` fails and the splitter's list is used instead."""
    return _undo_input(dialect, script, parse_fails=True)


def _lint_units(dialect: str, script: str, *, from_script: bool) -> List[str]:
    analysis = analyse_script(script, dialect)
    if not from_script and not analysis.statements and analysis.errors:
        raise UnsafeStatementSplitError("; ".join(analysis.errors))
    seen: List[str] = []
    real = lint_rules.classify_execution_statement

    def record(unit: str, **kwargs: Any) -> Any:
        seen.append(unit)
        return real(unit, **kwargs)

    with patch.object(lint_rules, "classify_execution_statement", record):
        lint_rules._mixed_transaction_modes(
            analysis.statements, dialect, script if from_script else None
        )
    return seen


def view_lint(dialect: str, script: str) -> List[str]:
    """The units ``mixed-transaction-modes`` classifies: the scanner's, as the script is given."""
    return _lint_units(dialect, script, from_script=True)


def view_lint_analysis(dialect: str, script: str) -> List[str]:
    """The same rule fed only ``analysis.statements`` (what it falls back to without a script)."""
    return _lint_units(dialect, script, from_script=False)


@dataclass(frozen=True)
class View:
    name: str
    run: Callable[[str, str], Sequence[str]]
    compares_with: str  # a field of Reference
    dialects: Tuple[str, ...] = DIALECTS


_FACTS = ("sqlite", "duckdb")
_PARSED = tuple(d for d in DIALECTS if d not in _FACTS)

VIEWS: Tuple[View, ...] = (
    View("migrate_classified", view_classified, "executed"),
    View("migrate_executable", view_executable, "sent"),
    View("migrate_executed", view_executed, "sent"),
    View("migrate_callback", view_callback, "sent"),
    View("migrate_constituents", view_migrate_constituents, "constituents", ("sqlserver",)),
    View("analysis", view_analysis, "analysis"),
    View("undo_facts", view_undo, "analysis", _FACTS),
    View("undo_parse", view_undo, "analysis", _PARSED),
    View("undo_fallback", view_undo_fallback, "analysis", _PARSED),
    View("lint", view_lint, "units"),
    View("lint_analysis", view_lint_analysis, "analysis"),
)

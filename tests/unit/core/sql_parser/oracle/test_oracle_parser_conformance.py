"""Oracle parser conformance harness — Phase Oracle scoping (ADR-0012).

This harness pins the *current* behaviour of ``OracleParser`` across
the five sub-responsibilities that will be extracted in Phase Oracle:

    1. Statement boundary detection (simple DDL, multi-statement scripts).
    2. PL/SQL block handling (procedures, functions, anonymous blocks).
    3. SQL*Plus directive recognition (SET, SPOOL).
    4. Comment stripping (line + block comments).
    5. Object extraction (quoted identifiers, sequences, DROP CASCADE).

Every case asserts the observable contract the public API delivers
today — statement count, success flag, and extracted object set. When
each sub-responsibility moves to its own module in the follow-up PRs
listed in ADR-0012, this harness is the contract that the split must
preserve. A failing case here blocks the split.

Some assertions codify quirks (e.g. ``CREATE ... NOFORCE VIEW`` is
parsed but the view name is **not** currently extracted by the object
regex). Those quirks are pinned deliberately: the scoping PR captures
today's behaviour, not an aspirational one. Fixing the quirks is out
of scope for the split — they ride as separate, post-split patches
with their own regression tests.

Run:

    python -m pytest tests/unit/core/sql_parser/oracle/test_oracle_parser_conformance.py -v
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet

import pytest

from db.plugins.oracle.parser.oracle_parser import OracleParser


@dataclass(frozen=True)
class ConformanceCase:
    """A single conformance input + expected public-surface output.

    ``expected_objects`` uses ``"NAME:OBJECT_TYPE"`` strings so the
    assertion is dialect-agnostic and independent of the internal
    ``SqlObject`` class layout. Oracle-specific case rules (unquoted
    upper-cased, quoted preserved) are baked into the expected values.
    """

    id: str
    sql: str
    expected_statement_count: int
    expected_success: bool = True
    expected_objects: FrozenSet[str] = field(default_factory=frozenset)


CASES: list[ConformanceCase] = [
    ConformanceCase(
        id="simple_ddl",
        sql="CREATE TABLE employees (id NUMBER, name VARCHAR2(100));",
        expected_statement_count=1,
        expected_objects=frozenset({"EMPLOYEES:TABLE"}),
    ),
    ConformanceCase(
        id="multi_ddl",
        sql=(
            "CREATE TABLE t1 (id NUMBER);\n"
            "CREATE TABLE t2 (id NUMBER);\n"
            "CREATE INDEX idx_t1 ON t1(id);\n"
        ),
        expected_statement_count=3,
        expected_objects=frozenset({"T1:TABLE", "T2:TABLE", "IDX_T1:INDEX"}),
    ),
    ConformanceCase(
        id="drop_cascade",
        sql="DROP TABLE employees CASCADE CONSTRAINTS;",
        expected_statement_count=1,
        expected_objects=frozenset({"EMPLOYEES:TABLE"}),
    ),
    ConformanceCase(
        # Previously pinned as a quirk; fixed in the PR-A follow-up
        # (ADR-0012 §Follow-ups): the object extractor now recognises
        # `CREATE [GLOBAL|PRIVATE] TEMPORARY TABLE`.
        id="global_temporary_table",
        sql=("CREATE GLOBAL TEMPORARY TABLE temp_t (id NUMBER, name VARCHAR2(100));"),
        expected_statement_count=1,
        expected_objects=frozenset({"TEMP_T:TABLE"}),
    ),
    ConformanceCase(
        # Previously pinned as a quirk; fixed in the PR-A follow-up
        # (ADR-0012 §Follow-ups): the view regex now allows the
        # optional `[NO]FORCE` and `[NON]EDITIONABLE` modifiers.
        id="noforce_view",
        sql=("CREATE OR REPLACE NOFORCE VIEW vw_test AS\n" "SELECT * FROM employees;"),
        expected_statement_count=1,
        expected_objects=frozenset({"VW_TEST:VIEW"}),
    ),
    ConformanceCase(
        id="plsql_procedure_then_table",
        sql=(
            "CREATE OR REPLACE PROCEDURE test_proc AS\n"
            "BEGIN\n"
            "    NULL;\n"
            "END;\n"
            "/\n\n"
            "CREATE TABLE after_proc (id NUMBER);\n"
        ),
        expected_statement_count=2,
        expected_objects=frozenset({"TEST_PROC:PROCEDURE", "AFTER_PROC:TABLE"}),
    ),
    ConformanceCase(
        # Previously pinned as a quirk; fixed in PR-B
        # (ADR-0012 §Follow-ups): FUNCTION now reports object_type
        # FUNCTION instead of PROCEDURE.
        id="plsql_function",
        sql=(
            "CREATE OR REPLACE FUNCTION test_func RETURN NUMBER AS\n"
            "BEGIN\n"
            "    RETURN 1;\n"
            "END;\n"
            "/\n"
        ),
        expected_statement_count=1,
        expected_objects=frozenset({"TEST_FUNC:FUNCTION"}),
    ),
    ConformanceCase(
        id="anonymous_plsql_block",
        sql=("BEGIN\n" "    NULL;\n" "END;\n" "/\n"),
        expected_statement_count=1,
        expected_objects=frozenset(),
    ),
    ConformanceCase(
        # SQL*Plus directives (SET, SPOOL) are recognised and dropped;
        # only the CREATE TABLE remains as an executable statement.
        id="sqlplus_directives_stripped",
        sql=("SET SERVEROUTPUT ON;\n" "SPOOL output.log;\n" "CREATE TABLE t (id NUMBER);\n"),
        expected_statement_count=1,
        expected_objects=frozenset({"T:TABLE"}),
    ),
    ConformanceCase(
        id="inline_and_block_comments",
        sql=(
            "-- leading comment\n"
            "CREATE TABLE t (id NUMBER); /* trailing */\n"
            "/* block\n"
            "   comment */\n"
            "CREATE INDEX idx_t ON t(id);\n"
        ),
        expected_statement_count=2,
        expected_objects=frozenset({"T:TABLE", "IDX_T:INDEX"}),
    ),
    ConformanceCase(
        # Quoted identifiers preserve exact case; unquoted are
        # upper-cased. Both halves appear in the same case to verify
        # neither rule leaks into the other.
        id="quoted_identifiers_preserve_case",
        sql=(
            'CREATE TABLE "Quoted_Schema"."Quoted_Table" (id NUMBER);\n'
            'CREATE INDEX "idx_Quoted" ON "Quoted_Schema"."Quoted_Table"(id);\n'
        ),
        expected_statement_count=2,
        expected_objects=frozenset({"Quoted_Table:TABLE", "idx_Quoted:INDEX"}),
    ),
    ConformanceCase(
        id="sequence",
        sql="CREATE SEQUENCE seq_test START WITH 1 INCREMENT BY 1;",
        expected_statement_count=1,
        expected_objects=frozenset({"SEQ_TEST:SEQUENCE"}),
    ),
]


@pytest.fixture(scope="module")
def parser() -> OracleParser:
    """One parser for the module — stateless across calls in practice."""
    return OracleParser()


@pytest.mark.unit
class TestOracleParserConformance:
    """Contract assertions for the public OracleParser surface."""

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
    def test_statement_count_and_success(self, parser: OracleParser, case: ConformanceCase) -> None:
        result = parser.parse_sql(case.sql)
        assert (
            result.success is case.expected_success
        ), f"{case.id}: success={result.success} (expected {case.expected_success})"
        assert len(result.statements) == case.expected_statement_count, (
            f"{case.id}: got {len(result.statements)} statements "
            f"(expected {case.expected_statement_count})\n"
            f"Statements:\n  " + "\n  ".join(s.sql_text[:80] for s in result.statements)
        )

    @pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
    def test_extracted_objects_match(self, parser: OracleParser, case: ConformanceCase) -> None:
        objects = parser.get_affected_objects(case.sql)
        actual = frozenset(f"{o.name}:{o.object_type.value}" for o in objects)
        assert actual == case.expected_objects, (
            f"{case.id}: extracted objects drifted.\n"
            f"  got:      {sorted(actual)}\n"
            f"  expected: {sorted(case.expected_objects)}"
        )

    def test_split_statements_strips_spool_absolute_path(self, parser: OracleParser) -> None:
        statements = parser.split_statements(
            "SPOOL /tmp/dblift_test.log;\nCREATE TABLE t (id NUMBER);"
        )

        assert statements == ["CREATE TABLE t(id NUMBER);"]


@pytest.mark.unit
class TestOracleParserSubResponsibilitiesPresent:
    """Structural guards: the five sub-responsibility modules exist.

    These pass today only because the skeleton modules have been
    committed (see ADR-0012). They stay green through the follow-up
    PRs that move logic into each skeleton. They fail if a skeleton
    is deleted prematurely — i.e. before its logic has been extracted.
    """

    @pytest.mark.parametrize(
        "module_name",
        [
            "db.plugins.oracle.parser._comments",
            "db.plugins.oracle.parser._sqlplus",
            "db.plugins.oracle.parser._object_extractor",
            "db.plugins.oracle.parser._statement_splitter",
            "db.plugins.oracle.parser._plsql_block",
        ],
    )
    def test_module_importable(self, module_name: str) -> None:
        import importlib

        mod = importlib.import_module(module_name)
        assert mod is not None, f"{module_name} must exist as a skeleton"
        assert mod.__doc__, (
            f"{module_name} must ship a docstring declaring its scope " f"(see ADR-0012)."
        )

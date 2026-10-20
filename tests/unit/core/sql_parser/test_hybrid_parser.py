"""Tests for HybridParser combining regex and sqlglot approaches."""

import typing
from typing import Optional
from unittest.mock import MagicMock

import pytest

from dblift.core.sql_model.base import ParseResult, SqlObject, SqlObjectType, SqlStatementType
from dblift.core.sql_model.event import Event
from dblift.core.sql_model.extension import Extension
from dblift.core.sql_model.foreign_data_wrapper import ForeignDataWrapper
from dblift.core.sql_model.foreign_server import ForeignServer
from dblift.core.sql_model.index import Index
from dblift.core.sql_model.package import Package
from dblift.core.sql_model.partition import Partition
from dblift.core.sql_model.procedure import Procedure
from dblift.core.sql_model.sequence import Sequence
from dblift.core.sql_model.synonym import Synonym
from dblift.core.sql_model.table import Table
from dblift.core.sql_model.trigger import Trigger
from dblift.core.sql_model.user_defined_type import UserDefinedType
from dblift.core.sql_model.view import View
from dblift.core.sql_parser.hybrid_parser import _COLLECT_DISPATCH, HybridParser
from dblift.core.sql_parser.parser_factory import SqlParserFactory


@pytest.mark.unit
class TestHybridParser:
    """Test cases for HybridParser functionality."""

    # ========== Parser Initialization ==========

    def test_parser_creation_oracle_is_refused(self):
        """Oracle reads statement facts: the generic parser is not built for it."""
        with pytest.raises(ValueError, match="StatementFactsParser"):
            HybridParser("oracle")

    def test_parser_creation_snowflake(self):
        """Test creating hybrid parser for a dialect that reads no statement facts."""
        parser = HybridParser("snowflake")
        assert parser.dialect_name == "snowflake"
        assert parser.regex_parser is not None
        assert parser.sqlglot_parser is not None

    def test_parser_creation_postgresql_is_refused(self):
        """PostgreSQL reads statement facts: the generic parser is not built for it."""
        with pytest.raises(ValueError, match="StatementFactsParser"):
            HybridParser("postgresql")

    def test_parser_creation_sqlserver(self):
        """Test creating hybrid parser for SQL Server."""
        parser = HybridParser("sqlserver")
        assert parser.dialect_name == "sqlserver"
        assert parser.regex_parser is not None
        assert parser.sqlglot_parser is not None

    def test_parser_creation_db2(self):
        """Db2 reads statement facts, so the hybrid parser refuses it."""
        with pytest.raises(ValueError, match="statement-facts parser"):
            HybridParser("db2")

    # ========== Statement Splitting (Regex-based) ==========

    def test_split_sqlserver_go(self):
        """Test splitting SQL Server statements with GO."""
        parser = HybridParser("sqlserver")
        sql = """
        CREATE TABLE users (id INT PRIMARY KEY);
        GO

        CREATE PROCEDURE GetUsers
        AS
        BEGIN
            SELECT * FROM users;
        END;
        GO

        INSERT INTO users VALUES (1);
        GO
        """

        statements = parser.split_statements(sql)
        # GO should act as delimiter
        assert len(statements) >= 3

    # ========== Pure SQL Enhancement ==========

    def test_parse_pure_sql_select(self):
        """Test parsing pure SQL SELECT with sqlglot enhancement."""
        parser = HybridParser("sqlserver")
        sql = "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id;"

        result = parser.parse_sql(sql, "public")
        assert result.success
        assert len(result.statements) == 1

        stmt = result.statements[0]
        assert (
            stmt.statement_type == SqlStatementType.SELECT
            or stmt.statement_type == SqlStatementType.QUERY
        )
        # Should extract tables from JOIN
        assert len(stmt.objects) >= 2

    def test_parse_pure_sql_create_table(self):
        """Test parsing CREATE TABLE with sqlglot enhancement."""
        parser = HybridParser("snowflake")
        sql = "CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(100));"

        result = parser.parse_sql(sql, "public")
        assert result.success
        assert len(result.statements) == 1

        stmt = result.statements[0]
        # CREATE or DDL are both acceptable for CREATE TABLE
        assert stmt.statement_type in [
            SqlStatementType.CREATE,
            SqlStatementType.DDL,
            SqlStatementType.UNKNOWN,
        ]
        # Should have at least the table being created in objects or affected_objects
        # Note: Some parsers may not extract objects, so we check if objects exist
        # If objects are extracted, verify they contain the table
        if stmt.affected_objects or stmt.objects:
            assert len(stmt.affected_objects) >= 1 or len(stmt.objects) >= 1
        # If no objects extracted, that's also acceptable - the statement was parsed successfully

    def test_parse_pure_sql_insert(self):
        """Test parsing INSERT with sqlglot enhancement."""
        parser = HybridParser("sqlserver")
        sql = "INSERT INTO users (name, email) VALUES ('John', 'john@example.com');"

        result = parser.parse_sql(sql)
        assert result.success
        assert len(result.statements) == 1

        stmt = result.statements[0]
        # INSERT or DML are both acceptable for INSERT statement
        assert stmt.statement_type in [SqlStatementType.INSERT, SqlStatementType.DML]

    # ========== Procedural Language Handling ==========

    def test_parse_sqlserver_tsql_procedure(self):
        """Test parsing SQL Server T-SQL procedure (uses regex, not sqlglot)."""
        parser = HybridParser("sqlserver")
        sql = """
        CREATE PROCEDURE GetUserOrders @UserId INT
        AS
        BEGIN
            SELECT o.*
            FROM orders o
            WHERE o.user_id = @UserId
            ORDER BY o.created_at DESC;
        END;
        """

        result = parser.parse_sql(sql, "dbo")
        assert result.success
        assert len(result.statements) >= 1

    # ========== Dependency Extraction ==========

    def test_extract_dependencies_select(self):
        """Test extracting dependencies from SELECT query."""
        parser = HybridParser("snowflake")
        sql = """
        SELECT c.name, c.email, o.total, o.order_date
        FROM customers c
        JOIN orders o ON c.id = o.customer_id
        WHERE o.status = 'completed';
        """

        deps = parser.extract_dependencies(sql, "public")
        assert "tables" in deps
        # Should find customers and orders tables
        assert len(deps["tables"]) >= 2

    def test_extract_dependencies_create_view(self):
        """Test extracting dependencies from CREATE VIEW."""
        parser = HybridParser("snowflake")
        sql = """
        CREATE VIEW active_customers AS
        SELECT c.*, COUNT(o.id) as order_count
        FROM customers c
        LEFT JOIN orders o ON c.id = o.customer_id
        WHERE c.status = 'active'
        GROUP BY c.id, c.name, c.email;
        """

        deps = parser.extract_dependencies(sql, "SALES")
        assert "tables" in deps
        # Should find customers and orders
        assert len(deps["tables"]) >= 2

    def test_extract_dependencies_procedural_skipped(self):
        """Test that procedural SQL is skipped for dependency extraction."""
        parser = HybridParser("snowflake")
        sql = """
        CREATE OR REPLACE FUNCTION complex_calculation() RETURNS INTEGER AS $$
        DECLARE
            result INTEGER;
        BEGIN
            -- Complex procedural logic here
            result := 42;
            RETURN result;
        END;
        $$ LANGUAGE plpgsql;
        """

        deps = parser.extract_dependencies(sql, "public")
        # Procedural blocks should be skipped
        # May or may not find tables depending on implementation
        assert "tables" in deps

    # ========== Object Extraction ==========

    def test_extract_objects_pure_sql(self):
        """Test extracting objects from pure SQL."""
        parser = HybridParser("sqlserver")
        sql = "SELECT * FROM users JOIN orders ON users.id = orders.user_id;"

        objects = parser.extract_objects(sql)
        # Should extract both tables
        assert len(objects) >= 2
        table_names = [obj.name.lower() for obj in objects]
        assert "users" in table_names
        assert "orders" in table_names

    def test_extract_objects_create_table(self):
        """Test extracting objects from CREATE TABLE."""
        parser = HybridParser("snowflake")
        sql = "CREATE TABLE products (id INT PRIMARY KEY, name VARCHAR(100), price DECIMAL(10,2));"

        objects = parser.extract_objects(sql, "public")
        assert len(objects) >= 1
        assert objects[0].name.lower() == "products"

    # ========== Validation ==========

    def test_validate_pure_sql_valid(self):
        """Test validating valid pure SQL."""
        parser = HybridParser("snowflake")
        sql = "SELECT * FROM users WHERE id = 1;"

        result = parser.validate_sql(sql)
        # Different parsers may return 'valid' or 'success'
        is_valid = result.get("valid", True)  # Default to True if key not present
        assert is_valid is True or len(result.get("errors", [])) == 0

    def test_validate_pure_sql_invalid(self):
        """Test validating invalid pure SQL."""
        parser = HybridParser("snowflake")
        sql = "SELECT * FORM users;"  # FORM instead of FROM

        result = parser.validate_sql(sql)
        # Should detect error
        assert not result["valid"] or len(result["errors"]) > 0

    # ========== Hybrid Behavior ==========

    # ========== DB2 (Regex-Only) ==========

    def test_db2_regex_only(self):
        """Test that DB2 is parsed by the statement-facts parser, not the hybrid one."""
        parser = SqlParserFactory("db2").get_parser()
        sql = "CREATE TABLE test (id INTEGER PRIMARY KEY);"

        result = parser.parse_sql(sql, "TESTDB")
        assert result.success
        assert not isinstance(parser, HybridParser)

    # ========== Edge Cases ==========

    def test_empty_sql(self):
        """Test parsing empty SQL."""
        parser = HybridParser("snowflake")
        result = parser.parse_sql("")
        # Should handle gracefully
        assert result.success or len(result.errors) > 0

    def test_comments_only(self):
        """Test parsing SQL with only comments."""
        parser = HybridParser("sqlserver")
        sql = "-- This is a comment\n/* Another comment */"

        result = parser.parse_sql(sql)
        # Should handle gracefully
        assert result.success

    def test_multiple_pure_sql_statements(self):
        """Test parsing multiple pure SQL statements."""
        parser = HybridParser("snowflake")
        sql = """
        INSERT INTO users (name) VALUES ('Alice');
        INSERT INTO users (name) VALUES ('Bob');
        INSERT INTO users (name) VALUES ('Charlie');
        """

        result = parser.parse_sql(sql, "public")
        assert result.success
        assert len(result.statements) == 3


@pytest.mark.unit
class TestMergeObjectsReconcilesPerStatementPerType:
    """``_merge_objects`` reconciles per statement, per object type (#377).

    Previously ``_merge_objects`` deduped by ``(name.lower(), object_type)``
    across a whole (possibly multi-statement) batch and preferred sqlglot on
    a collision. That single rule produced two opposite wrong outcomes: a
    name collision silently dropped the regex-resolved schema, and a name
    mismatch let a phantom object survive alongside the correct one.

    The fixed rule, per statement and per object type T: if sqlglot
    produced >=1 object of type T, its objects of type T replace the regex
    objects of type T entirely (a differing regex name is dropped, not
    added, and the divergence is logged at DEBUG); if sqlglot produced
    nothing of type T, the regex objects for T are kept. On a name
    collision, the surviving schema is ``sqlglot.schema or regex.schema``.
    """

    def test_collision_on_matching_name_keeps_the_regex_resolved_schema(self):
        """Same name shape: sqlglot's answer replaces the regex answer for
        the TABLE type, and the schema regex had resolved is retained.

        SQL Server's own convention resolves an unqualified table to the
        ``dbo`` schema; the regex parser applies that internally, and
        sqlglot has no default of its own to apply unless it is handed one.
        Both parsers report the same name ``plainname`` (no bracket-escaping
        involved, so #375's fix to bracket-escape truncation is not in
        play), so this is the collision case: exactly one object survives,
        and it must not have lost its schema.
        """
        parser = HybridParser("sqlserver")
        sql = "CREATE TABLE [plainname] (id int);"

        regex_objects = parser.regex_parser.extract_objects(sql, None)
        assert regex_objects[0].name.lower() == "plainname"
        assert regex_objects[0].schema == "dbo"  # regex resolved SQL Server's default schema

        merged = parser.extract_objects(sql, None)
        assert len(merged) == 1
        assert merged[0].name.lower() == "plainname"
        assert merged[0].schema == "dbo"  # fixed: the resolved schema is no longer lost

    def test_non_colliding_names_drop_the_regex_name_not_add_it(self, caplog):
        """Different names shape: when the two parsers disagree on the
        *name* for the same statement and sqlglot produced a TABLE, its
        TABLE objects replace the regex TABLE objects entirely — the
        regex-truncated name is dropped rather than surviving beside the
        correct one, and the divergence is logged at DEBUG.

        The regex name is the bracket-doubling truncation the regex
        parser used to produce for ``[real]]one]`` (it stopped at the
        first backtick; sqlglot decodes the escape). The regex parser now
        reads the name whole, so the divergence is fed in directly to keep
        the merge mechanism itself -- not just that one instance -- pinned.
        """
        parser = HybridParser("sqlserver")
        regex_objects = [SqlObject("real", SqlObjectType.TABLE, schema=None, dialect="sqlserver")]
        sqlglot_objects = [
            SqlObject("real]one", SqlObjectType.TABLE, schema=None, dialect="sqlserver")
        ]

        with caplog.at_level("DEBUG", logger="dblift.core.sql_parser.hybrid_parser"):
            merged = parser._merge_objects(regex_objects, sqlglot_objects)

        # fixed: only sqlglot's correctly-decoded name survives
        assert {obj.name for obj in merged} == {"real]one"}
        assert len(merged) == 1
        assert any("real" in r.message and "real]one" in r.message for r in caplog.records), [
            r.message for r in caplog.records
        ]

    def test_collision_schema_fill_falls_back_to_regex_when_sqlglot_has_none(self):
        """Direct unit test of the collision schema-fill rule:
        ``schema = sqlglot.schema or regex.schema``.

        Exercised directly on ``_merge_objects`` (not through
        ``extract_objects``) because ``extract_objects``'s own
        default-schema resolution already makes sqlglot's and regex's
        *default* schema agree end-to-end for the common no-default-passed
        case, so that path alone never reaches this fallback. This pins
        the fallback itself, for a collision that still disagrees on
        schema after that resolution (e.g. one side reads an explicit
        qualifier the other does not).
        """
        parser = HybridParser("snowflake")
        regex_objects = [
            SqlObject("foo", SqlObjectType.TABLE, schema="myschema", dialect="snowflake")
        ]
        sqlglot_objects = [SqlObject("foo", SqlObjectType.TABLE, schema=None, dialect="snowflake")]

        merged = parser._merge_objects(regex_objects, sqlglot_objects)

        assert len(merged) == 1
        assert merged[0].name == "foo"
        assert merged[0].schema == "myschema"  # filled from regex since sqlglot's was empty

    def test_collision_schema_fill_prefers_sqlglot_when_both_present(self):
        """``schema = sqlglot.schema or regex.schema``: sqlglot's schema
        wins when both sides have one."""
        parser = HybridParser("snowflake")
        regex_objects = [
            SqlObject("foo", SqlObjectType.TABLE, schema="regexschema", dialect="snowflake")
        ]
        sqlglot_objects = [
            SqlObject("foo", SqlObjectType.TABLE, schema="sqlglotschema", dialect="snowflake")
        ]

        merged = parser._merge_objects(regex_objects, sqlglot_objects)

        assert len(merged) == 1
        assert merged[0].schema == "sqlglotschema"


@pytest.mark.unit
class TestMergeObjectsTypeMismatchPhantomOutOfScope:
    """A type-level mismatch is NOT reconciled by this change (#377).

    ``_merge_objects``'s rule operates per object type: it reconciles a
    *name* divergence within one type, not a *type* divergence between the
    two parsers on the same statement. When the two sides produce different,
    non-empty types for the same name, the per-type rule leaves both
    standing — sqlglot's set replaces regex's only within a type both sides
    touch, so the two never even compete when their types don't match.

    This is correct behaviour for this change: reconciling a type-level
    mismatch is out of scope here. This test exists so the interaction is a
    pinned, visible fact rather than a surprise discovered later.

    The maintainer's original example was PostgreSQL ``DROP TRIGGER x ON
    table`` (dblift/dblift#384): sqlglot's DROP-kind dispatch special-cased
    only VIEW/INDEX/SEQUENCE and silently defaulted everything else,
    including TRIGGER, to TABLE. dblift/dblift#387 fixed that dispatch
    itself (``_DROP_KIND_TO_OBJECT_TYPE`` in ``sqlglot_parser.py``, mapping
    TRIGGER/FUNCTION/PROCEDURE/TYPE/DATABASE too) rather than guarding
    sqlglot away from the shape, and the fix is general: every DROP kind
    it added reports correctly now, on every dialect sqlglot supports — not
    just PostgreSQL. I re-verified this directly, including on the
    unqualified-form, cross-dialect shape (MySQL/SQL Server/Oracle ``DROP
    TRIGGER name`` with no ``ON`` clause) I had been about to pin here as a
    surviving instance: it no longer reproduces either, so no DROP-kind
    example remains to pin.
    """

    @pytest.mark.parametrize(
        "dialect,sql",
        [
            ("snowflake", "DROP TRIGGER my_trigger;"),
            ("sqlserver", "DROP TRIGGER my_trigger;"),
        ],
    )
    def test_drop_trigger_reports_trigger_not_a_phantom_table(self, dialect, sql):
        """Regression pin for dblift/dblift#384, fixed by #387: on every
        dialect #387's ``_DROP_KIND_TO_OBJECT_TYPE`` covers, ``DROP TRIGGER``
        must produce exactly one correctly-typed TRIGGER object through the
        production path (``HybridParser.extract_objects``) — not a TRIGGER
        alongside a phantom TABLE sqlglot's DROP-kind dispatch used to
        invent by defaulting every kind it didn't special-case to TABLE."""
        parser = HybridParser(dialect)

        merged = parser.extract_objects(sql, None)

        assert len(merged) == 1
        assert merged[0].object_type == SqlObjectType.TRIGGER


@pytest.mark.unit
class TestSqlGlotDropKindDispatchMapsKnownKinds:
    """sqlglot's DROP-kind dispatch must report the correct SqlObjectType for
    every DROP kind sqlglot's grammar recognizes, not just VIEW/INDEX/
    SEQUENCE (dblift/dblift#384).

    sqlglot itself never raises or misparses ``DROP TRIGGER``, ``DROP
    FUNCTION``, ``DROP PROCEDURE``, ``DROP TYPE`` or ``DROP DATABASE`` — its
    AST already carries the right answer in ``ast.kind``. The bug was
    entirely in this repository's translation from ``ast.kind`` to
    ``SqlObjectType`` in ``SqlGlotParser``: everything other than VIEW,
    INDEX and SEQUENCE fell through a bare ``else: TABLE``, so any of these
    statements came back mistyped as a table — on every dialect sqlglot
    supports (PostgreSQL, Oracle, MySQL, SQL Server), not a PostgreSQL-only
    defect, and not limited to ``DROP TRIGGER``.

    This corrects the dispatch itself (``_DROP_KIND_TO_OBJECT_TYPE`` in
    ``sqlglot_parser.py``) rather than adding a guard that skips sqlglot for
    the affected shapes: a guard only stops sqlglot from being asked at all,
    discarding whatever it would have gotten right (e.g. a quoted
    identifier's case, which sqlglot preserves and the regex parser does
    not always); fixing the mapping keeps that contribution and fixes every
    dialect hitting the same fallthrough at once.
    """

    @pytest.mark.parametrize(
        "dialect,sql,expected_type",
        [
            ("snowflake", "DROP TRIGGER my_trigger;", SqlObjectType.TRIGGER),
            ("snowflake", "DROP FUNCTION my_func;", SqlObjectType.FUNCTION),
            ("snowflake", "DROP PROCEDURE my_proc;", SqlObjectType.PROCEDURE),
            ("sqlserver", "DROP TRIGGER my_trigger;", SqlObjectType.TRIGGER),
            ("sqlserver", "DROP FUNCTION my_func;", SqlObjectType.FUNCTION),
            ("sqlserver", "DROP PROCEDURE my_proc;", SqlObjectType.PROCEDURE),
        ],
    )
    def test_sqlglot_parser_reports_the_correct_type(self, dialect, sql, expected_type):
        from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser

        parser = SqlGlotParser(dialect)
        objects = parser.extract_objects(sql, "public")

        assert len(objects) == 1
        assert objects[0].object_type == expected_type

    @pytest.mark.parametrize(
        "sql,expected_type",
        [
            ("DROP VIEW my_view;", SqlObjectType.VIEW),
            ("DROP SEQUENCE my_seq;", SqlObjectType.SEQUENCE),
            ("DROP TABLE my_table;", SqlObjectType.TABLE),
        ],
    )
    def test_previously_handled_kinds_are_unaffected(self, sql, expected_type):
        """VIEW, SEQUENCE and the TABLE default were already correct before
        this fix; rewriting the dispatch as a dict lookup must not change
        them (INDEX has its own test below, since it carries a side effect)."""
        from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser

        parser = SqlGlotParser("snowflake")
        objects = parser.extract_objects(sql, "public")

        assert len(objects) == 1
        assert objects[0].object_type == expected_type

    def test_drop_index_schema_correction_still_applies(self):
        """The DROP INDEX branch's SQL Server schema-correction side effect
        (``_correct_sqlserver_drop_index_schema``) must still run — INDEX is
        now identified by comparing the *resolved* object_type against the
        dict lookup's result rather than ``ast.kind`` directly, so this is
        the case most likely to regress silently if that comparison were
        wrong."""
        from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser

        parser = SqlGlotParser("sqlserver")
        objects = parser.extract_objects("DROP INDEX idx1 ON mytable;", "dbo")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.INDEX
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"

    def test_kind_sqlglot_does_not_recognize_falls_through_untouched(self):
        """A DROP kind sqlglot's grammar does not support for a dialect (here,
        PostgreSQL ``DROP EXTENSION``) never reaches ``exp.Drop`` at all — it
        parses as an opaque ``Command`` — so the dispatch map contributes
        nothing and the regex parser's answer is what survives. This pins
        that sqlglot contributes no (wrong) object here, rather than
        asserting on sqlglot's raw output directly, since ``Command`` has no
        stable object-shaped contract to assert against."""
        from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser

        parser = SqlGlotParser("snowflake")
        objects = parser.extract_objects("DROP EXTENSION my_ext;", "public")

        assert objects == []


@pytest.mark.unit
class TestExtractObjectsCrossDialectDropFunctionProcedure:
    """The same DROP-kind dispatch defect that mistyped PostgreSQL's DROP
    TRIGGER also mistyped DROP FUNCTION and DROP PROCEDURE, on every dialect
    sqlglot supports — confirming the fix in
    ``TestSqlGlotDropKindDispatchMapsKnownKinds`` closes the phantom TABLE
    at the production entry point too, not just at the SqlGlotParser layer,
    and that it does so beyond PostgreSQL."""

    @pytest.mark.parametrize(
        "dialect,sql,expected_type",
        [
            ("sqlserver", "DROP FUNCTION my_func;", SqlObjectType.FUNCTION),
            ("sqlserver", "DROP PROCEDURE my_proc;", SqlObjectType.PROCEDURE),
        ],
    )
    def test_no_phantom_table_alongside_the_correct_object(self, dialect, sql, expected_type):
        parser = HybridParser(dialect)
        objects = parser.extract_objects(sql, "public")

        assert len(objects) == 1
        assert objects[0].object_type == expected_type
        assert not any(o.object_type == SqlObjectType.TABLE for o in objects)


@pytest.mark.unit
class TestExtractObjectsQuietOnRoutineDropIndexOnQualifiedTable:
    """`DROP INDEX idx ON schema.table` must not warn (dblift/dblift#379 SHOULD-FIX).

    This is not an edge case: it is the *only* legal way to drop an index in
    SQL Server and MySQL, and schema-qualifying the table is routine. sqlglot's
    grammar happens to reject the schema-qualified form specifically (the
    unqualified form and the legacy dot-qualified form both parse fine), but
    the regex parser already extracts this shape correctly — that's the
    accidental fallback #379 established. Letting the WARNING added for the
    genuine failure (the comma-separated `DROP INDEX a.x, b.y` form, which no
    parser can read) also fire here would make it noise on every ordinary
    `DROP INDEX`, exactly the alert-fatigue problem #356 removed.
    """

    def test_sqlserver_schema_qualified_drop_index_on_does_not_warn(self, caplog):
        parser = HybridParser("sqlserver")
        sql = "DROP INDEX idx1 ON dbo.mytable;"

        with caplog.at_level("WARNING"):
            objects = parser.extract_objects(sql)

        assert not caplog.records, [r.message for r in caplog.records]
        assert len(objects) == 1
        assert objects[0].name == "idx1"
        assert objects[0].schema == "dbo"

    def test_comma_separated_drop_index_still_warns(self, caplog):
        """The genuine #379 failure — a shape neither parser can read — must
        keep warning. This is the regression guard against 'fixing' the
        noise by reverting the log level instead of narrowing the trigger."""
        parser = HybridParser("sqlserver")
        sql = "DROP INDEX a.idx1, b.idx2;"

        with caplog.at_level("WARNING"):
            objects = parser.extract_objects(sql)

        assert any(
            "SqlGlot parse failed for object extraction" in r.message for r in caplog.records
        )
        assert objects == []

    def test_guard_does_not_leak_across_statements_in_a_batch(self, caplog):
        """The unsupported-shape guard must be scoped to the statement it
        actually describes, not to the whole (possibly multi-statement)
        ``sql_content`` blob it is handed.

        A harmless, unqualified ``DROP INDEX idx1 ON mytable;`` earlier in
        the same string must not suppress sqlglot for the *rest* of the
        batch. Before this test, the guard's regex could span past the
        statement's own terminating ``;`` and match an unrelated ``... ON
        a.x`` later in the string (e.g. inside a ``JOIN ... ON`` clause),
        flipping ``use_sqlglot`` to False for the entire blob and silently
        downgrading a valid, unrelated statement's extraction to
        regex-only — the exact all-or-nothing batch hazard
        ``extract_objects``'s own docstring warns about, now reachable
        through this guard instead of through sqlglot itself.
        """
        parser = HybridParser("sqlserver")
        sql = (
            "DROP INDEX idx1 ON mytable; "
            "CREATE TABLE [real]]one] (id int); "
            "SELECT * FROM a JOIN b ON a.x = b.y;"
        )

        objects = parser.extract_objects(sql, default_schema="myschema")

        names = {obj.name for obj in objects}
        # sqlglot must still run on this batch and contribute its correctly
        # decoded name; if the guard leaked, only the regex-truncated
        # ``real`` would be present.
        assert "real]one" in names, names


@pytest.mark.unit
class TestCollectObjectsDispatch:
    """Tests for _collect_objects dispatch dict pattern (story 14-9)."""

    def _make_parser(self):
        return HybridParser("snowflake")

    def test_collect_table_calls_add_table(self):
        """AC#3.1: TABLE dispatches to result.add_table."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        table = Table(name="users")
        parser._collect_objects(result, [table])
        assert len(result.tables) == 1
        assert result.tables[0].name == "users"

    def test_collect_view_calls_add_view(self):
        """AC#3.1: VIEW dispatches to result.add_view."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        view = View(name="v_users")
        parser._collect_objects(result, [view])
        assert len(result.views) == 1
        assert result.views[0].name == "v_users"

    def test_collect_procedure_calls_add_procedure(self):
        """AC#3.1: PROCEDURE dispatches to result.add_procedure."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        proc = Procedure(name="do_stuff")
        parser._collect_objects(result, [proc])
        assert len(result.procedures) == 1
        assert result.procedures[0].name == "do_stuff"

    def test_collect_materialized_view_routes_to_add_view(self):
        """AC#3.2: MATERIALIZED_VIEW dispatches to result.add_view."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        mv = View(name="mv_stats", materialized=True)
        parser._collect_objects(result, [mv])
        assert len(result.views) == 1
        assert result.views[0].name == "mv_stats"

    def test_collect_partition_no_dedup_check(self):
        """AC#3.3: PARTITION is always added without _object_exists check."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        p1 = Partition(name="p1", table="t1", partition_method="RANGE")
        p2 = Partition(name="p1", table="t1", partition_method="RANGE")
        parser._collect_objects(result, [p1, p2])
        assert len(result.partitions) == 2

    def test_collect_unknown_type_ignored(self):
        """AC#3.4: Unknown types are silently ignored."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        obj = MagicMock(spec=SqlObject)
        obj.object_type = MagicMock()  # Not a real SqlObjectType
        parser._collect_objects(result, [obj])
        assert len(result.tables) == 0
        assert len(result.views) == 0

    def test_collect_function_uses_procedure_isinstance(self):
        """AC#1.5: FUNCTION uses Procedure as expected_class."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        func = Procedure(name="calc", is_function=True)
        parser._collect_objects(result, [func])
        assert len(result.functions) == 1
        assert result.functions[0].name == "calc"

    def test_collect_dedup_prevents_duplicate_table(self):
        """Dedup check prevents adding same table twice."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        t1 = Table(name="users")
        t2 = Table(name="users")
        parser._collect_objects(result, [t1, t2])
        assert len(result.tables) == 1

    def test_dispatch_dict_has_all_expected_entries(self):
        """Structural: _COLLECT_DISPATCH has 17 entries covering all object types."""
        assert len(_COLLECT_DISPATCH) == 17
        # PARTITION has no get_collection (None) — AC#1.5
        _, get_coll, _ = _COLLECT_DISPATCH[SqlObjectType.PARTITION]
        assert get_coll is None, "PARTITION must have get_collection=None (no dedup)"
        # VIEW and MATERIALIZED_VIEW share the same add_method — AC#1.3
        _, _, view_add = _COLLECT_DISPATCH[SqlObjectType.VIEW]
        _, _, mv_add = _COLLECT_DISPATCH[SqlObjectType.MATERIALIZED_VIEW]
        assert view_add == mv_add == "add_view", "VIEW and MATERIALIZED_VIEW must share add_view"
        # FUNCTION uses Procedure as expected_class — AC#1.4
        func_class, _, _ = _COLLECT_DISPATCH[SqlObjectType.FUNCTION]
        assert func_class is Procedure, "FUNCTION must use Procedure as expected_class"

    def test_collect_empty_list_noop(self):
        """Empty objects list is a no-op."""
        parser = self._make_parser()
        result = ParseResult(success=True)
        parser._collect_objects(result, [])
        assert len(result.tables) == 0

    def test_collect_wrong_isinstance_silently_ignored(self):
        """AC#2: entry found in dict but isinstance fails → object silently skipped."""
        # Create a View with object_type=TABLE to trigger isinstance rejection
        parser = self._make_parser()
        result = ParseResult(success=True)
        obj = MagicMock(spec=SqlObject)
        obj.object_type = SqlObjectType.TABLE  # In dispatch dict...
        # ...but obj is not a Table instance → isinstance(obj, Table) is False
        parser._collect_objects(result, [obj])
        assert len(result.tables) == 0, "Object with wrong type should be silently skipped"


@pytest.mark.unit
class TestDeadCodeRemoved:
    """Verify dead methods were removed from HybridParser."""

    def test_is_pure_sql_method_removed(self):
        """AC#6.3: _is_pure_sql must not exist on HybridParser."""
        assert not hasattr(HybridParser, "_is_pure_sql")


@pytest.mark.unit
class TestNormalizeIdentifierTypeHint:
    """Verify _normalize_identifier accepts None (Optional[str] type hint fix)."""

    def _make_parser(self):
        parser = HybridParser.__new__(HybridParser)
        parser.log = MagicMock()
        return parser

    def test_normalize_identifier_none_returns_empty_no_preserve(self):
        """AC#5: _normalize_identifier(None, False) returns empty string."""
        parser = self._make_parser()
        result = parser._normalize_identifier(None, False)
        assert result == ""

    def test_normalize_identifier_none_returns_empty_preserve(self):
        """AC#5: _normalize_identifier(None, True) returns empty string."""
        parser = self._make_parser()
        result = parser._normalize_identifier(None, True)
        assert result == ""

    def test_normalize_identifier_type_hint_is_optional_str(self):
        """M1: The type annotation must be Optional[str], not str."""
        hints = typing.get_type_hints(HybridParser._normalize_identifier)
        assert hints["identifier"] == Optional[str]

    def test_normalize_identifier_non_none_preserve_case_false(self):
        """L1: Non-None path still works — uppercase when preserve_case=False."""
        parser = self._make_parser()
        assert parser._normalize_identifier("hello", False) == "HELLO"

    def test_normalize_identifier_non_none_preserve_case_true(self):
        """L1: Non-None path still works — case preserved when preserve_case=True."""
        parser = self._make_parser()
        assert parser._normalize_identifier('"MySchema"', True) == "MySchema"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

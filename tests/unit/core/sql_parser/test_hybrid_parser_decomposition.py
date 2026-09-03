"""Tests for HybridParser decomposition helpers (story 19-11)."""

import inspect
from unittest.mock import MagicMock, patch

import pytest
from sqlglot import exp, parse_one

from dblift.core.sql_model.base import (
    ConstraintType,
    ParseResult,
    SqlConstraint,
    SqlStatement,
    SqlStatementType,
)
from dblift.core.sql_model.table import Table
from dblift.core.sql_parser.hybrid_parser import HybridParser


def _make_parser(dialect: str = "mysql") -> HybridParser:
    return HybridParser(dialect)


# ────────────────────────────────────────────────────────────
# AC#1 — _extract_table_constraints_from_sqlglot dispatcher
# ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestExtractTableConstraintsFromSqlglot:
    """Tests for the constraint dispatcher (AC#6.2)."""

    def test_dispatches_check_constraint(self):
        parser = _make_parser("postgresql")
        sql = "CREATE TABLE t (id INT, CONSTRAINT chk CHECK (id > 0))"
        ast = parse_one(sql, read="postgres")
        schema_expr = ast.this  # Schema node
        constraints = parser._extract_table_constraints_from_sqlglot(schema_expr)
        check_constraints = [c for c in constraints if c.constraint_type == ConstraintType.CHECK]
        assert len(check_constraints) >= 1

    def test_dispatches_primary_key(self):
        parser = _make_parser("postgresql")
        sql = "CREATE TABLE t (id INT, CONSTRAINT pk PRIMARY KEY (id))"
        ast = parse_one(sql, read="postgres")
        schema_expr = ast.this
        constraints = parser._extract_table_constraints_from_sqlglot(schema_expr)
        pk_constraints = [c for c in constraints if c.constraint_type == ConstraintType.PRIMARY_KEY]
        assert len(pk_constraints) >= 1

    def test_dispatches_foreign_key(self):
        parser = _make_parser("postgresql")
        sql = "CREATE TABLE t (id INT, parent_id INT, CONSTRAINT fk FOREIGN KEY (parent_id) REFERENCES parent(id))"
        ast = parse_one(sql, read="postgres")
        schema_expr = ast.this
        constraints = parser._extract_table_constraints_from_sqlglot(schema_expr)
        fk_constraints = [c for c in constraints if c.constraint_type == ConstraintType.FOREIGN_KEY]
        assert len(fk_constraints) >= 1

    def test_dispatches_unique_constraint(self):
        parser = _make_parser("postgresql")
        sql = "CREATE TABLE t (id INT, email TEXT, CONSTRAINT uq UNIQUE (email))"
        ast = parse_one(sql, read="postgres")
        schema_expr = ast.this
        constraints = parser._extract_table_constraints_from_sqlglot(schema_expr)
        uq_constraints = [c for c in constraints if c.constraint_type == ConstraintType.UNIQUE]
        assert len(uq_constraints) >= 1

    def test_unknown_expression_skipped(self):
        parser = _make_parser("postgresql")
        # A bare column definition is not a constraint type → no constraint emitted
        col_expr = exp.ColumnDef(this=exp.to_identifier("col1"))
        constraints = parser._extract_table_constraints_from_sqlglot(col_expr)
        constraint_types = {c.constraint_type for c in constraints}
        # Should not produce CHECK/PK/FK/UNIQUE
        assert ConstraintType.CHECK not in constraint_types
        assert ConstraintType.PRIMARY_KEY not in constraint_types
        assert ConstraintType.FOREIGN_KEY not in constraint_types
        assert ConstraintType.UNIQUE not in constraint_types


# ────────────────────────────────────────────────────────────
# AC#1 — individual constraint helpers
# ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestExtractCheckConstraintFromSqlglot:
    """Tests for _extract_check_constraint_from_sqlglot (AC#6.3)."""

    def test_extracts_check_constraint_name_and_expression(self):
        parser = _make_parser("postgresql")
        sql = "CREATE TABLE t (id INT, CONSTRAINT chk_positive CHECK (id > 0))"
        ast = parse_one(sql, read="postgres")
        schema_expr = ast.this
        constraints = parser._extract_table_constraints_from_sqlglot(schema_expr)
        checks = [c for c in constraints if c.constraint_type == ConstraintType.CHECK]
        assert len(checks) == 1
        assert checks[0].name == "chk_positive"
        assert checks[0].check_expression is not None

    def test_check_constraint_without_name_uses_default(self):
        parser = _make_parser("postgresql")
        sql = "CREATE TABLE t (id INT, CHECK (id > 0))"
        ast = parse_one(sql, read="postgres")
        schema_expr = ast.this
        constraints = parser._extract_table_constraints_from_sqlglot(schema_expr)
        checks = [c for c in constraints if c.constraint_type == ConstraintType.CHECK]
        assert len(checks) == 1
        # No explicit name → constraint_name is None
        assert checks[0].name is None
        assert checks[0].check_expression is not None


@pytest.mark.unit
class TestExtractPkFromSqlglot:
    """Tests for _extract_pk_from_sqlglot (AC#6.4)."""

    def test_extracts_pk_columns(self):
        parser = _make_parser("postgresql")
        sql = "CREATE TABLE t (id INT, name TEXT, PRIMARY KEY (id))"
        ast = parse_one(sql, read="postgres")
        schema_expr = ast.this
        constraints = parser._extract_table_constraints_from_sqlglot(schema_expr)
        pks = [c for c in constraints if c.constraint_type == ConstraintType.PRIMARY_KEY]
        assert len(pks) == 1
        assert "id" in [col.lower() for col in pks[0].column_names]

    def test_pk_with_constraint_name(self):
        parser = _make_parser("postgresql")
        sql = "CREATE TABLE t (id INT, CONSTRAINT pk_t PRIMARY KEY (id))"
        ast = parse_one(sql, read="postgres")
        schema_expr = ast.this
        constraints = parser._extract_table_constraints_from_sqlglot(schema_expr)
        pks = [c for c in constraints if c.constraint_type == ConstraintType.PRIMARY_KEY]
        assert len(pks) == 1
        assert pks[0].name == "pk_t"


# ────────────────────────────────────────────────────────────
# AC#2 — extract_dependencies helpers
# ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestShouldSkipDependencyStatement:
    """Tests for _should_skip_dependency_statement (AC#6.5)."""

    def test_skip_procedural(self):
        parser = _make_parser("postgresql")
        stmt = "BEGIN\n  INSERT INTO t VALUES (1);\nEND;"
        assert parser._should_skip_dependency_statement(stmt) is True

    def test_skip_oracle_unsupported(self):
        parser = _make_parser("oracle")
        stmt = "CREATE OR REPLACE PACKAGE BODY my_pkg AS BEGIN NULL; END;"
        assert parser._should_skip_dependency_statement(stmt) is True

    def test_no_skip_pure_sql_select(self):
        parser = _make_parser("postgresql")
        stmt = "SELECT * FROM users WHERE id = 1"
        assert parser._should_skip_dependency_statement(stmt) is False

    def test_no_skip_create_table(self):
        parser = _make_parser("postgresql")
        stmt = "CREATE TABLE users (id INT PRIMARY KEY)"
        assert parser._should_skip_dependency_statement(stmt) is False


@pytest.mark.unit
class TestExtractTableDepsFromAst:
    """Tests for _extract_table_deps_from_ast (AC#6.6)."""

    def test_extracts_table_and_schema(self):
        parser = _make_parser("postgresql")
        sql = "SELECT * FROM myschema.orders"
        ast = parse_one(sql, read="postgres")
        deps = {"tables": [], "views": [], "schemas": []}
        parser._extract_table_deps_from_ast(ast, deps)
        assert any("orders" == t.lower() for t in deps["tables"])
        assert "myschema" in deps["schemas"]

    def test_skips_created_table(self):
        parser = _make_parser("postgresql")
        sql = "CREATE TABLE new_table AS SELECT * FROM source_table"
        ast = parse_one(sql, read="postgres")
        deps = {"tables": [], "views": [], "schemas": []}
        parser._extract_table_deps_from_ast(ast, deps)
        # new_table should NOT appear in deps (it's being created)
        table_names_lower = [t.lower() for t in deps["tables"]]
        assert "new_table" not in table_names_lower
        assert "source_table" in table_names_lower


@pytest.mark.unit
class TestExtractViewDepsFromObjects:
    """Tests for _extract_view_deps_from_objects (AC#2 helper, L3 coverage)."""

    def test_adds_view_name_to_deps(self):
        parser = _make_parser("postgresql")
        sql = "CREATE VIEW my_view AS SELECT 1"
        deps = {"tables": [], "views": [], "schemas": []}
        parser._extract_view_deps_from_objects(sql, None, deps)
        assert "my_view" in deps["views"]

    def test_adds_schema_to_deps(self):
        parser = _make_parser("postgresql")
        sql = "CREATE VIEW myschema.v AS SELECT 1"
        deps = {"tables": [], "views": [], "schemas": []}
        parser._extract_view_deps_from_objects(sql, None, deps)
        assert "myschema" in deps["schemas"]


# ────────────────────────────────────────────────────────────
# AC#3 — trigger helpers
# ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestParseTriggerHeader:
    """Tests for _parse_trigger_header (AC#6.7)."""

    def test_valid_mysql_trigger_matches(self):
        parser = _make_parser("mysql")
        sql = "CREATE TRIGGER trg_users_ai AFTER INSERT ON test_schema.users FOR EACH ROW SET NEW.created = NOW()"
        match = parser._parse_trigger_header(sql)
        assert match is not None
        assert match.group(2) == "trg_users_ai"
        assert match.group(3).upper() == "AFTER"
        assert match.group(4).upper() == "INSERT"
        assert match.group(5) == "test_schema"
        assert match.group(6) == "users"

    def test_invalid_sql_returns_none(self):
        parser = _make_parser("mysql")
        sql = "SELECT * FROM users"
        match = parser._parse_trigger_header(sql)
        assert match is None


@pytest.mark.unit
class TestExtractTriggerDefiner:
    """Tests for _extract_trigger_definer (AC#6.8)."""

    def test_extracts_definer_from_sql(self):
        parser = _make_parser("mysql")
        sql = "CREATE DEFINER=root@localhost TRIGGER trg AFTER INSERT ON s.t FOR EACH ROW SET NEW.x = 1"
        definer = parser._extract_trigger_definer(sql)
        assert definer is not None
        assert "root" in definer
        assert "localhost" in definer

    def test_returns_none_when_no_definer(self):
        parser = _make_parser("mysql")
        sql = "CREATE TRIGGER trg AFTER INSERT ON s.t FOR EACH ROW SET NEW.x = 1"
        definer = parser._extract_trigger_definer(sql)
        assert definer is None

    def test_returns_none_for_non_mysql_dialect(self):
        parser = _make_parser("postgresql")
        sql = "CREATE DEFINER=root@localhost TRIGGER trg AFTER INSERT ON s.t FOR EACH ROW SET NEW.x = 1"
        definer = parser._extract_trigger_definer(sql)
        assert definer is None


# ────────────────────────────────────────────────────────────
# AC#7 — structural verification
# ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestOrchestratorsAreShort:
    """Verify orchestrators are short via inspect.getsource (AC#7)."""

    def test_extract_table_constraints_from_sqlglot_is_short(self):
        src = inspect.getsource(HybridParser._extract_table_constraints_from_sqlglot)
        line_count = len(src.strip().splitlines())
        assert (
            line_count < 35
        ), f"_extract_table_constraints_from_sqlglot has {line_count} lines (expected < 35)"

    def test_extract_dependencies_is_short(self):
        src = inspect.getsource(HybridParser.extract_dependencies)
        line_count = len(src.strip().splitlines())
        assert line_count < 35, f"extract_dependencies has {line_count} lines (expected < 35)"

    def test_ensure_trigger_metadata_is_short(self):
        src = inspect.getsource(HybridParser._ensure_trigger_metadata)
        line_count = len(src.strip().splitlines())
        assert line_count < 30, f"_ensure_trigger_metadata has {line_count} lines (expected < 30)"

    def test_ensure_alter_table_metadata_is_short(self):
        src = inspect.getsource(HybridParser._ensure_alter_table_metadata)
        line_count = len(src.strip().splitlines())
        assert (
            line_count < 35
        ), f"_ensure_alter_table_metadata has {line_count} lines (expected < 35)"

    def test_all_helpers_in_class_dict(self):
        expected_helpers = [
            # AC#1 — constraint helpers (includes 2 extra unwrapping helpers extracted by implementation)
            "_resolve_constraint_expressions",
            "_unwrap_constraint_expression",
            "_extract_check_constraint_from_sqlglot",
            "_extract_pk_from_sqlglot",
            "_extract_fk_from_sqlglot",
            "_extract_unique_from_sqlglot",
            # AC#2 — dependency helpers
            "_should_skip_dependency_statement",
            "_extract_table_deps_from_ast",
            "_extract_view_deps_from_objects",
            # AC#3 — trigger helpers
            "_parse_trigger_header",
            "_extract_trigger_definer",
            "_build_or_update_trigger",
            # AC#4 — alter table helpers
            "_parse_alter_table_via_sqlglot",
            "_apply_alter_constraints_to_table",
        ]
        for helper in expected_helpers:
            assert hasattr(
                HybridParser, helper
            ), f"{helper} not found on HybridParser (may be in a mixin)"

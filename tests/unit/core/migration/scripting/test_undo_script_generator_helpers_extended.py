"""Extended unit tests for _UndoHelpersMixin (_helpers.py) targeting uncovered
branches: sqlglot-based insert table/where-clause extraction, value-to-string
conversion, and the various ``return None`` fallthrough paths in the
``_extract_*`` helpers."""

from unittest.mock import MagicMock

import pytest
from sqlglot import exp, parse_one

from core.migration.scripting.undo_script_generator._helpers import _UndoHelpersMixin

pytestmark = [pytest.mark.unit]


class _Stub(_UndoHelpersMixin):
    def __init__(self, dialect="postgresql"):
        self.dialect = dialect
        self.logger = None


class TestGenerateDropStatementNoSchema:
    def test_no_schema_uses_unqualified_name(self):
        stub = _Stub()
        sql = stub._generate_drop_statement("TABLE", "orders", None)
        assert sql == 'DROP TABLE IF EXISTS "orders" CASCADE;'

    def test_with_schema_uses_qualified_name(self):
        stub = _Stub()
        sql = stub._generate_drop_statement("TABLE", "orders", "sales")
        assert sql == 'DROP TABLE IF EXISTS "sales"."orders" CASCADE;'


class TestExtractVersionFromFilenameNoMatch:
    def test_non_versioned_filename_returns_none(self):
        stub = _Stub()
        assert stub._extract_version_from_filename("not_a_migration.txt") is None


class TestExtractTableNameFromDropNoMatch:
    def test_non_drop_table_sql_returns_none(self):
        stub = _Stub()
        assert stub._extract_table_name_from_drop("SELECT 1") is None


class TestExtractTableNameFromCommentNoMatch:
    def test_non_comment_sql_returns_none(self):
        stub = _Stub()
        assert stub._extract_table_name_from_comment("SELECT 1") is None


class TestExtractTableNameFromInsert:
    def test_sqlglot_schema_wrapped_insert(self):
        stub = _Stub()
        result = stub._extract_table_name_from_insert(
            "INSERT INTO orders (id, name) VALUES (1, 'a')"
        )
        assert result == "orders"

    def test_sqlglot_table_direct_insert(self):
        stub = _Stub()
        result = stub._extract_table_name_from_insert("INSERT INTO orders VALUES (1, 'a')")
        assert result == "orders"

    def test_sqlglot_exception_falls_back_to_regex(self):
        stub = _Stub()
        sql = 'INSERT INTO "public"."orders" !!!GARBAGE!!!'
        assert stub._extract_table_name_from_insert(sql) == "orders"

    def test_no_match_anywhere_returns_none(self):
        stub = _Stub()
        assert stub._extract_table_name_from_insert("SELECT 1") is None


class TestExtractTableNameFromDeleteNoMatch:
    def test_non_delete_sql_returns_none(self):
        stub = _Stub()
        assert stub._extract_table_name_from_delete("SELECT 1") is None


class TestExtractTableNameFromCreateIndexNoMatch:
    def test_non_create_index_sql_returns_none(self):
        stub = _Stub()
        assert stub._extract_table_name_from_create_index("SELECT 1") is None


class TestExtractTableNameFromIndexIdxSuffixHeuristic:
    def test_idx_suffix_without_on_clause_returns_prefix(self):
        stub = _Stub()
        result = stub._extract_table_name_from_index('DROP INDEX "orders_idx"')
        assert result == "orders"

    def test_no_match_anywhere_returns_none(self):
        stub = _Stub()
        assert stub._extract_table_name_from_index("SELECT 1") is None


class TestExtractCreateObjectIndexBranch:
    def test_index_with_schema(self):
        stub = _Stub()
        result = stub._extract_create_object("CREATE INDEX idx_orders ON sales.orders (id)")
        assert result == ("INDEX", "IDX_ORDERS", "SALES")

    def test_index_without_schema(self):
        stub = _Stub()
        result = stub._extract_create_object("CREATE INDEX idx_orders ON orders (id)")
        assert result == ("INDEX", "IDX_ORDERS", None)

    def test_no_match_returns_none(self):
        stub = _Stub()
        assert stub._extract_create_object("DROP TABLE foo") is None


class TestExtractColumnNameFromAddNoMatch:
    def test_non_add_column_sql_returns_none(self):
        stub = _Stub()
        assert stub._extract_column_name_from_add("ALTER TABLE t DROP COLUMN x") is None


class TestExtractConstraintNameFromAddNoMatch:
    def test_add_column_sql_returns_none(self):
        stub = _Stub()
        assert stub._extract_constraint_name_from_add("ALTER TABLE t ADD COLUMN x INT") is None


class TestExtractInsertWhereClauseFromAst:
    def test_non_insert_ast_returns_none(self):
        stub = _Stub()
        ast = parse_one("SELECT 1", read="postgres")
        assert stub._extract_insert_where_clause_from_ast(ast, "orders") is None

    def test_insert_without_expression_returns_none(self):
        stub = _Stub()
        ast = parse_one("INSERT INTO orders DEFAULT VALUES", read="postgres")
        assert stub._extract_insert_where_clause_from_ast(ast, "orders") is None

    def test_values_with_columns_builds_where_clause(self):
        stub = _Stub()
        ast = parse_one("INSERT INTO orders (id, name) VALUES (1, 'a')", read="postgres")
        result = stub._extract_insert_where_clause_from_ast(ast, "orders")
        assert result == '"id" = 1 AND "name" = \'a\''

    def test_values_without_columns_returns_none(self):
        stub = _Stub()
        ast = parse_one("INSERT INTO orders VALUES (1, 'a')", read="postgres")
        assert stub._extract_insert_where_clause_from_ast(ast, "orders") is None

    def test_insert_select_returns_none(self):
        stub = _Stub()
        ast = parse_one("INSERT INTO orders SELECT * FROM other", read="postgres")
        assert stub._extract_insert_where_clause_from_ast(ast, "orders") is None


class TestValueToString:
    def test_string_literal_escapes_quotes(self):
        stub = _Stub()
        literal = exp.Literal(this="o'brien", is_string=True)
        assert stub._value_to_string(literal) == "'o''brien'"

    def test_numeric_literal(self):
        stub = _Stub()
        literal = exp.Literal(this="42", is_string=False)
        assert stub._value_to_string(literal) == "42"

    def test_column_expression(self):
        stub = _Stub()
        column = exp.Column(this=exp.Identifier(this="id", quoted=False))
        assert stub._value_to_string(column) == "id"

    def test_null_expression(self):
        stub = _Stub()
        assert stub._value_to_string(exp.Null()) == "NULL"

    def test_complex_expression_uses_str(self):
        stub = _Stub()
        expr = exp.Add(
            this=exp.Literal(this="1", is_string=False),
            expression=exp.Literal(this="2", is_string=False),
        )
        assert stub._value_to_string(expr) == str(expr)

    def test_unstringifiable_expression_returns_none(self):
        stub = _Stub()
        value = MagicMock()
        value.__str__.side_effect = Exception("boom")
        assert stub._value_to_string(value) is None


class TestExtractInsertWhereClauseAlwaysNone:
    def test_with_values_and_columns_returns_none(self):
        stub = _Stub()
        assert stub._extract_insert_where_clause("INSERT INTO t (a) VALUES (1)") is None

    def test_without_values_returns_none(self):
        stub = _Stub()
        assert stub._extract_insert_where_clause("INSERT INTO t SELECT 1") is None

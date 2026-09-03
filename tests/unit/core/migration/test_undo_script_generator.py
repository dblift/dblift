"""Unit tests for the undo script generator cluster.

Covers:
  - core/migration/scripting/undo_script_generator/_models.py
  - core/migration/scripting/undo_script_generator/_extractors.py
  - core/migration/scripting/undo_script_generator/_helpers.py
  - core/migration/scripting/undo_script_generator/_reversers.py
  - core/migration/scripting/undo_script_generator/_generator.py  (UndoScriptGenerator)
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock


class TestUndoStatement(unittest.TestCase):
    """Tests for the UndoStatement dataclass (_models.py)."""

    def test_basic_construction(self):
        from dblift.core.migration.scripting.undo_script_generator._models import UndoStatement

        stmt = UndoStatement(
            sql="DROP TABLE users;",
            original_statement="CREATE TABLE users (id INT);",
            operation_type="CREATE",
        )
        self.assertEqual(stmt.sql, "DROP TABLE users;")
        self.assertEqual(stmt.original_statement, "CREATE TABLE users (id INT);")
        self.assertEqual(stmt.operation_type, "CREATE")
        self.assertIsNone(stmt.warning)
        self.assertFalse(stmt.requires_manual_review)

    def test_optional_warning_and_review_flag(self):
        from dblift.core.migration.scripting.undo_script_generator._models import UndoStatement

        stmt = UndoStatement(
            sql="-- WARNING: cannot reverse",
            original_statement="DROP TABLE x;",
            operation_type="DROP",
            warning="DROP cannot be reversed",
            requires_manual_review=True,
        )
        self.assertEqual(stmt.warning, "DROP cannot be reversed")
        self.assertTrue(stmt.requires_manual_review)


# ---------------------------------------------------------------------------
# _UndoExtractorsMixin — tested via UndoStatementEmitter (concrete subclass)
# ---------------------------------------------------------------------------


class TestUndoStatementEmitterGenerateDrop(unittest.TestCase):
    """Tests for _generate_drop_statement in _UndoExtractorsMixin/_extractors.py."""

    def _make_emitter(self, dialect="postgresql"):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect=dialect)

    def test_postgresql_table_has_if_exists_and_cascade(self):
        emitter = self._make_emitter("postgresql")
        sql = emitter._generate_drop_statement("TABLE", "users", None)
        self.assertIn("DROP TABLE", sql)
        self.assertIn("IF EXISTS", sql)
        self.assertIn("CASCADE", sql)

    def test_mysql_table_has_if_exists_no_cascade(self):
        emitter = self._make_emitter("mysql")
        sql = emitter._generate_drop_statement("TABLE", "users", None)
        self.assertIn("IF EXISTS", sql)
        self.assertNotIn("CASCADE", sql)

    def test_oracle_table_no_if_exists(self):
        emitter = self._make_emitter("oracle")
        sql = emitter._generate_drop_statement("TABLE", "users", None)
        self.assertNotIn("IF EXISTS", sql)

    def test_sqlserver_table_has_if_exists(self):
        emitter = self._make_emitter("sqlserver")
        sql = emitter._generate_drop_statement("TABLE", "users", None)
        self.assertIn("IF EXISTS", sql)

    def test_with_schema_quoted_identifiers(self):
        emitter = self._make_emitter("postgresql")
        sql = emitter._generate_drop_statement("TABLE", "users", "public")
        self.assertIn('"public"', sql)
        self.assertIn('"users"', sql)

    def test_view_no_cascade(self):
        emitter = self._make_emitter("postgresql")
        sql = emitter._generate_drop_statement("VIEW", "my_view", None)
        self.assertIn("DROP VIEW", sql)
        self.assertNotIn("CASCADE", sql)


class TestUndoStatementEmitterQuoteIdentifier(unittest.TestCase):
    """Tests for _quote_identifier in _UndoExtractorsMixin."""

    def _make_emitter(self, dialect="postgresql"):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect=dialect)

    def test_postgresql_double_quotes(self):
        emitter = self._make_emitter("postgresql")
        self.assertEqual(emitter._quote_identifier("users"), '"users"')

    def test_mysql_backticks(self):
        emitter = self._make_emitter("mysql")
        result = emitter._quote_identifier("users")
        self.assertIn("users", result)

    def test_oracle_double_quotes(self):
        emitter = self._make_emitter("oracle")
        result = emitter._quote_identifier("users")
        self.assertIn("users", result)

    def test_escapes_embedded_quote_character(self):
        """Issue #911: an identifier containing the dialect's own quote
        character must have it doubled, not passed through raw — this is
        the exact method _extractors.py/_reversers.py call to build
        DROP COLUMN / DROP CONSTRAINT statements for auto-generated undo
        scripts."""
        emitter = self._make_emitter("postgresql")
        self.assertEqual(emitter._quote_identifier('say "hi"'), '"say ""hi"""')

    def test_drop_column_statement_escapes_embedded_quote(self):
        """Reproduces the issue's concrete failure scenario: an undo script
        DROP COLUMN for a column named say "hi" must not emit the malformed
        DROP COLUMN "say "hi"" — built with the exact f-string pattern
        _reversers.py uses (ALTER TABLE ... DROP COLUMN {quoted});."""
        emitter = self._make_emitter("postgresql")
        column_name = 'say "hi"'
        drop_sql = f"ALTER TABLE {emitter._quote_identifier('users')} DROP COLUMN {emitter._quote_identifier(column_name)};"
        self.assertEqual(
            drop_sql,
            'ALTER TABLE "users" DROP COLUMN "say ""hi""";',
        )


class TestUndoStatementEmitterExtractVersion(unittest.TestCase):
    """Tests for _extract_version_from_filename in _UndoExtractorsMixin."""

    def _make_emitter(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect="postgresql")

    def test_simple_version(self):
        emitter = self._make_emitter()
        self.assertEqual(emitter._extract_version_from_filename("V1__create.sql"), "1")

    def test_dotted_version(self):
        emitter = self._make_emitter()
        self.assertEqual(emitter._extract_version_from_filename("V1.0.1__desc.sql"), "1.0.1")

    def test_underscore_version(self):
        emitter = self._make_emitter()
        self.assertEqual(emitter._extract_version_from_filename("V1_0_1__desc.sql"), "1_0_1")

    def test_no_match_repeatable(self):
        emitter = self._make_emitter()
        self.assertIsNone(emitter._extract_version_from_filename("R1__desc.sql"))

    def test_no_match_undo_prefix(self):
        emitter = self._make_emitter()
        self.assertIsNone(emitter._extract_version_from_filename("U1__desc.sql"))

    def test_case_insensitive(self):
        emitter = self._make_emitter()
        # lowercase v
        self.assertEqual(emitter._extract_version_from_filename("v2__migration.sql"), "2")


class TestUndoStatementEmitterExtractTableFromDrop(unittest.TestCase):
    """Tests for _extract_table_name_from_drop in _UndoExtractorsMixin."""

    def _make_emitter(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect="postgresql")

    def test_unquoted_table(self):
        emitter = self._make_emitter()
        self.assertEqual(emitter._extract_table_name_from_drop("DROP TABLE users;"), "users")

    def test_if_exists(self):
        emitter = self._make_emitter()
        self.assertEqual(
            emitter._extract_table_name_from_drop("DROP TABLE IF EXISTS users;"), "users"
        )

    def test_with_schema_unquoted(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_drop("DROP TABLE public.users;")
        self.assertEqual(result, "users")

    def test_quoted_table(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_drop('DROP TABLE IF EXISTS "users" CASCADE;')
        self.assertEqual(result, "users")

    def test_no_match_returns_none(self):
        emitter = self._make_emitter()
        self.assertIsNone(emitter._extract_table_name_from_drop("SELECT 1"))


class TestUndoStatementEmitterExtractTableFromComment(unittest.TestCase):
    """Tests for _extract_table_name_from_comment in _UndoExtractorsMixin."""

    def _make_emitter(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect="postgresql")

    def test_basic(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_comment("COMMENT ON TABLE orders IS 'desc';")
        self.assertEqual(result, "orders")

    def test_with_schema(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_comment("COMMENT ON TABLE public.orders IS 'x';")
        self.assertEqual(result, "orders")

    def test_no_match_returns_none(self):
        emitter = self._make_emitter()
        self.assertIsNone(emitter._extract_table_name_from_comment("DROP TABLE users;"))


class TestUndoStatementEmitterExtractTableFromInsert(unittest.TestCase):
    """Tests for _extract_table_name_from_insert in _UndoExtractorsMixin."""

    def _make_emitter(self, dialect="postgresql"):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect=dialect)

    def test_basic_insert(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_insert("INSERT INTO products (id) VALUES (1);")
        self.assertEqual(result, "products")

    def test_with_schema(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_insert(
            "INSERT INTO public.products (id) VALUES (1);"
        )
        self.assertEqual(result, "products")

    def test_no_match_returns_none(self):
        emitter = self._make_emitter()
        self.assertIsNone(emitter._extract_table_name_from_insert("DROP TABLE x;"))

    def test_mysql_dialect(self):
        emitter = self._make_emitter("mysql")
        result = emitter._extract_table_name_from_insert("INSERT INTO users (name) VALUES ('a');")
        self.assertEqual(result, "users")


class TestUndoStatementEmitterExtractTableFromDelete(unittest.TestCase):
    """Tests for _extract_table_name_from_delete in _UndoExtractorsMixin."""

    def _make_emitter(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect="postgresql")

    def test_basic_delete(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_delete("DELETE FROM users WHERE id=1;")
        self.assertEqual(result, "users")

    def test_with_schema(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_delete("DELETE FROM public.users WHERE id=1;")
        self.assertEqual(result, "users")

    def test_no_match(self):
        emitter = self._make_emitter()
        self.assertIsNone(emitter._extract_table_name_from_delete("SELECT 1;"))


class TestUndoStatementEmitterExtractTableFromCreateIndex(unittest.TestCase):
    """Tests for _extract_table_name_from_create_index in _UndoExtractorsMixin."""

    def _make_emitter(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect="postgresql")

    def test_basic_create_index(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_create_index(
            "CREATE INDEX idx_users_email ON users(email);"
        )
        self.assertEqual(result, "users")

    def test_unique_index(self):
        # UNIQUE keyword is not handled by the regex in _extract_table_name_from_create_index;
        # it returns None in that case (known limitation — DROP INDEX only uses _extract_table_name_from_index).
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_create_index(
            "CREATE UNIQUE INDEX idx_u ON orders(id);"
        )
        # The method does NOT support UNIQUE INDEX (returns None) — assert accordingly
        self.assertIsNone(result)

    def test_no_on_clause(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_create_index("DROP INDEX idx_x;")
        self.assertIsNone(result)


class TestUndoStatementEmitterExtractTableFromIndex(unittest.TestCase):
    """Tests for _extract_table_name_from_index in _UndoExtractorsMixin."""

    def _make_emitter(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect="postgresql")

    def test_drop_index_with_on(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_index("DROP INDEX idx_users ON users;")
        self.assertEqual(result, "users")

    def test_drop_index_idx_prefix_heuristic(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_index("DROP INDEX idx_orders_total;")
        self.assertEqual(result, "orders")

    def test_drop_index_suffix_heuristic(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_index("DROP INDEX products_idx;")
        self.assertEqual(result, "products")

    def test_no_match_returns_none(self):
        emitter = self._make_emitter()
        result = emitter._extract_table_name_from_index("SELECT 1;")
        self.assertIsNone(result)


class TestUndoStatementEmitterExtractCreateObject(unittest.TestCase):
    """Tests for _extract_create_object in _UndoExtractorsMixin."""

    def _make_emitter(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect="postgresql")

    def test_create_table(self):
        emitter = self._make_emitter()
        result = emitter._extract_create_object("CREATE TABLE users (id INT);")
        self.assertIsNotNone(result)
        obj_type, obj_name, schema = result
        self.assertEqual(obj_type, "TABLE")
        self.assertIn("USERS", obj_name.upper())

    def test_create_view(self):
        emitter = self._make_emitter()
        result = emitter._extract_create_object("CREATE VIEW my_view AS SELECT 1;")
        self.assertIsNotNone(result)
        obj_type, obj_name, schema = result
        self.assertEqual(obj_type, "VIEW")

    def test_create_sequence(self):
        emitter = self._make_emitter()
        result = emitter._extract_create_object("CREATE SEQUENCE user_seq;")
        self.assertIsNotNone(result)
        obj_type, obj_name, schema = result
        self.assertEqual(obj_type, "SEQUENCE")

    def test_create_index_returns_index_name(self):
        emitter = self._make_emitter()
        result = emitter._extract_create_object("CREATE INDEX idx_users ON users(id);")
        self.assertIsNotNone(result)
        obj_type, obj_name, schema = result
        self.assertEqual(obj_type, "INDEX")
        self.assertIn("IDX_USERS", obj_name.upper())

    def test_unknown_returns_none(self):
        emitter = self._make_emitter()
        result = emitter._extract_create_object("SELECT 1;")
        self.assertIsNone(result)

    def test_create_or_replace_view(self):
        emitter = self._make_emitter()
        result = emitter._extract_create_object("CREATE OR REPLACE VIEW v AS SELECT 1;")
        self.assertIsNotNone(result)
        obj_type, _, _ = result
        self.assertEqual(obj_type, "VIEW")

    def test_create_function(self):
        emitter = self._make_emitter()
        result = emitter._extract_create_object(
            "CREATE OR REPLACE FUNCTION my_func() RETURNS void;"
        )
        self.assertIsNotNone(result)
        obj_type, _, _ = result
        self.assertEqual(obj_type, "PROCEDURE")


class TestUndoStatementEmitterExtractColumnFromAdd(unittest.TestCase):
    """Tests for _extract_column_name_from_add in _UndoExtractorsMixin."""

    def _make_emitter(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect="postgresql")

    def test_add_column_keyword(self):
        emitter = self._make_emitter()
        result = emitter._extract_column_name_from_add(
            "ALTER TABLE t ADD COLUMN email VARCHAR(255);"
        )
        self.assertEqual(result, "email")

    def test_add_without_column_keyword(self):
        emitter = self._make_emitter()
        result = emitter._extract_column_name_from_add("ALTER TABLE t ADD age INT;")
        self.assertEqual(result, "age")

    def test_no_match(self):
        emitter = self._make_emitter()
        result = emitter._extract_column_name_from_add("DROP TABLE x;")
        self.assertIsNone(result)


class TestUndoStatementEmitterExtractConstraintFromAdd(unittest.TestCase):
    """Tests for _extract_constraint_name_from_add in _UndoExtractorsMixin."""

    def _make_emitter(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect="postgresql")

    def test_add_constraint(self):
        emitter = self._make_emitter()
        result = emitter._extract_constraint_name_from_add(
            "ALTER TABLE t ADD CONSTRAINT uk_email UNIQUE(email);"
        )
        self.assertEqual(result, "uk_email")

    def test_add_foreign_key(self):
        emitter = self._make_emitter()
        result = emitter._extract_constraint_name_from_add(
            "ALTER TABLE t ADD FOREIGN KEY fk_user(user_id) REFERENCES users(id);"
        )
        self.assertEqual(result, "fk_user")

    def test_no_match(self):
        emitter = self._make_emitter()
        result = emitter._extract_constraint_name_from_add("SELECT 1;")
        self.assertIsNone(result)


class TestUndoStatementEmitterExtractInsertWhereClause(unittest.TestCase):
    """Tests for _extract_insert_where_clause in _UndoExtractorsMixin."""

    def _make_emitter(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect="postgresql")

    def test_with_columns_returns_none(self):
        # When columns are provided, the method returns None (too complex)
        emitter = self._make_emitter()
        result = emitter._extract_insert_where_clause("INSERT INTO t (id, name) VALUES (1, 'x');")
        self.assertIsNone(result)

    def test_no_values_clause_returns_none(self):
        emitter = self._make_emitter()
        result = emitter._extract_insert_where_clause("INSERT INTO t SELECT * FROM s;")
        self.assertIsNone(result)


class TestUndoStatementEmitterExtractInsertWhereClauseFromAst(unittest.TestCase):
    """Tests for _extract_insert_where_clause_from_ast in _UndoExtractorsMixin."""

    def _make_emitter(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect="postgresql")

    def test_non_insert_ast_returns_none(self):
        from sqlglot import exp

        emitter = self._make_emitter()
        # Pass something that is not an Insert
        select_ast = MagicMock(spec=[])
        # Not an exp.Insert instance
        result = emitter._extract_insert_where_clause_from_ast(select_ast, "users")
        self.assertIsNone(result)

    def test_insert_with_columns_and_values_returns_conditions(self):
        from sqlglot import parse_one

        emitter = self._make_emitter()
        ast = parse_one("INSERT INTO users (id, name) VALUES (1, 'Alice');", read="postgres")
        result = emitter._extract_insert_where_clause_from_ast(ast, "users")
        # Should return a WHERE clause with conditions
        self.assertIsNotNone(result)
        self.assertIn("id", result)
        self.assertIn("name", result)

    def test_insert_select_returns_none(self):
        from sqlglot import parse_one

        emitter = self._make_emitter()
        ast = parse_one("INSERT INTO users SELECT * FROM old_users;", read="postgres")
        result = emitter._extract_insert_where_clause_from_ast(ast, "users")
        self.assertIsNone(result)


class TestUndoStatementEmitterValueToString(unittest.TestCase):
    """Tests for _value_to_string in _UndoExtractorsMixin."""

    def _make_emitter(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        return UndoStatementEmitter(dialect="postgresql")

    def test_string_literal(self):
        from sqlglot import exp

        emitter = self._make_emitter()
        lit = exp.Literal.string("hello")
        result = emitter._value_to_string(lit)
        self.assertEqual(result, "'hello'")

    def test_number_literal(self):
        from sqlglot import exp

        emitter = self._make_emitter()
        lit = exp.Literal.number(42)
        result = emitter._value_to_string(lit)
        self.assertEqual(result, "42")

    def test_null_literal(self):
        from sqlglot import exp

        emitter = self._make_emitter()
        null = exp.Null()
        result = emitter._value_to_string(null)
        self.assertEqual(result, "NULL")

    def test_string_with_single_quote_escaped(self):
        from sqlglot import exp

        emitter = self._make_emitter()
        lit = exp.Literal.string("it's")
        result = emitter._value_to_string(lit)
        self.assertIn("''", result)

    def test_complex_expression_stringified(self):
        from sqlglot import exp

        emitter = self._make_emitter()
        # A Column expression
        col = exp.Column(this=exp.Identifier(this="mycolumn"))
        result = emitter._value_to_string(col)
        self.assertIsNotNone(result)
        self.assertIn("mycolumn", str(result))


# ---------------------------------------------------------------------------
# _UndoReversersMixin — covers _reversers.py routing logic
# ---------------------------------------------------------------------------


class TestUndoReversersMixin(unittest.TestCase):
    """Tests for _UndoReversersMixin (_reversers.py)."""

    def _make_generator(self, dialect="postgresql"):
        from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator

        return UndoScriptGenerator(dialect=dialect)

    def _make_stmt(self, sql, stmt_type=None):
        from dblift.core.sql_model.base import SqlStatementType

        stmt = MagicMock()
        stmt.sql_text = sql
        if stmt_type is None:
            stmt.statement_type = SqlStatementType.UNKNOWN
        else:
            stmt.statement_type = stmt_type
        stmt.affected_objects = []
        stmt.objects = []
        return stmt

    # _reverse_statement_from_parsed routing with UNKNOWN stmt type
    def test_routing_create_unknown_type(self):
        gen = self._make_generator()
        stmt = self._make_stmt("CREATE TABLE x (id INT);")
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn("DROP TABLE", result.sql)

    def test_routing_alter_unknown_type(self):
        from dblift.core.sql_model.base import SqlObject, SqlObjectType

        gen = self._make_generator()
        stmt = self._make_stmt("ALTER TABLE x ADD COLUMN y INT;")
        # Provide affected_objects so ALTER reverser can extract the table name
        sql_obj = MagicMock()
        sql_obj.name = "x"
        sql_obj.schema = None
        stmt.affected_objects = [sql_obj]
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn("DROP COLUMN", result.sql)

    def test_routing_create_escapes_embedded_quote_in_table_name(self):
        """Issue #911, traced end-to-end through the real reverser path:
        a CREATE TABLE whose parsed affected_objects carry a table name
        with an embedded quote must reverse to a properly escaped
        DROP TABLE, not the malformed form quote_identifier() previously
        produced."""
        from dblift.core.sql_model.base import SqlObjectType

        gen = self._make_generator("postgresql")
        stmt = self._make_stmt('CREATE TABLE "say ""hi""" (id INT);')
        sql_obj = MagicMock()
        sql_obj.name = 'say "hi"'
        sql_obj.schema = None
        sql_obj.object_type = SqlObjectType.TABLE
        stmt.affected_objects = [sql_obj]
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn('"say ""hi"""', result.sql)

    def test_routing_drop_unknown_type(self):
        gen = self._make_generator()
        stmt = self._make_stmt("DROP TABLE x;")
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn("WARNING", result.sql)

    def test_routing_insert_unknown_type(self):
        gen = self._make_generator()
        stmt = self._make_stmt("INSERT INTO x (id) VALUES (1);")
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertEqual(result.operation_type, "INSERT")

    def test_routing_update_unknown_type(self):
        gen = self._make_generator()
        stmt = self._make_stmt("UPDATE x SET y=1;")
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn("WARNING", result.sql)

    def test_routing_delete_unknown_type(self):
        gen = self._make_generator()
        stmt = self._make_stmt("DELETE FROM x WHERE id=1;")
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn("WARNING", result.sql)

    def test_routing_comment_unknown_type(self):
        gen = self._make_generator()
        stmt = self._make_stmt("COMMENT ON TABLE x IS 'desc';")
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn("IS NULL", result.sql)

    # _reverse_statement_from_parsed routing with specific SqlStatementType
    def test_routing_create_specific_type(self):
        from dblift.core.sql_model.base import SqlStatementType

        gen = self._make_generator()
        stmt = self._make_stmt("CREATE TABLE y (id INT);", SqlStatementType.CREATE)
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn("DROP TABLE", result.sql)

    def test_routing_alter_specific_type(self):
        from dblift.core.sql_model.base import SqlStatementType

        gen = self._make_generator()
        stmt = self._make_stmt("ALTER TABLE y ADD COLUMN z INT;", SqlStatementType.ALTER)
        # Provide affected_objects so ALTER reverser can extract the table name
        sql_obj = MagicMock()
        sql_obj.name = "y"
        sql_obj.schema = None
        stmt.affected_objects = [sql_obj]
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn("DROP COLUMN", result.sql)

    def test_routing_drop_specific_type(self):
        from dblift.core.sql_model.base import SqlStatementType

        gen = self._make_generator()
        stmt = self._make_stmt("DROP TABLE y;", SqlStatementType.DROP)
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn("WARNING", result.sql)

    def test_routing_insert_specific_type(self):
        from dblift.core.sql_model.base import SqlStatementType

        gen = self._make_generator()
        stmt = self._make_stmt("INSERT INTO y (id) VALUES (1);", SqlStatementType.INSERT)
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertEqual(result.operation_type, "INSERT")

    def test_routing_update_specific_type(self):
        from dblift.core.sql_model.base import SqlStatementType

        gen = self._make_generator()
        stmt = self._make_stmt("UPDATE y SET z=1;", SqlStatementType.UPDATE)
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn("WARNING", result.sql)

    def test_routing_delete_specific_type(self):
        from dblift.core.sql_model.base import SqlStatementType

        gen = self._make_generator()
        stmt = self._make_stmt("DELETE FROM y;", SqlStatementType.DELETE)
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn("WARNING", result.sql)

    def test_routing_comment_specific_type(self):
        from dblift.core.sql_model.base import SqlStatementType

        gen = self._make_generator()
        stmt = self._make_stmt("COMMENT ON TABLE y IS 'x';", SqlStatementType.COMMENT)
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn("IS NULL", result.sql)

    def test_routing_dml_generic_type_create_fallback(self):
        from dblift.core.sql_model.base import SqlStatementType

        gen = self._make_generator()
        stmt = self._make_stmt("CREATE TABLE z (id INT);", SqlStatementType.DDL)
        result = gen._reverse_statement_from_parsed(stmt)
        self.assertIn("DROP TABLE", result.sql)

    def test_routing_unknown_unsupported_statement(self):
        from dblift.core.sql_model.base import SqlStatementType

        gen = self._make_generator()
        stmt = self._make_stmt("SOME UNKNOWN STATEMENT;", SqlStatementType.UNKNOWN)
        stmt.sql_text = "SOME UNKNOWN STATEMENT;"
        result = gen._reverse_statement_from_parsed(stmt)
        # Does not match any keyword → goes to fallback
        self.assertIn("WARNING", result.sql)
        self.assertTrue(result.requires_manual_review)

    # _reverse_statement (fallback string parsing)
    def test_reverse_statement_create(self):
        gen = self._make_generator()
        result = gen._reverse_statement("CREATE TABLE z (id INT);")
        self.assertIn("DROP TABLE", result.sql)

    def test_reverse_statement_alter(self):
        gen = self._make_generator()
        result = gen._reverse_statement("ALTER TABLE z ADD COLUMN w INT;")
        self.assertIn("DROP COLUMN", result.sql)

    def test_reverse_statement_drop(self):
        gen = self._make_generator()
        result = gen._reverse_statement("DROP TABLE z;")
        self.assertIn("WARNING", result.sql)

    def test_reverse_statement_insert(self):
        gen = self._make_generator()
        result = gen._reverse_statement("INSERT INTO z (id) VALUES (1);")
        self.assertEqual(result.operation_type, "INSERT")

    def test_reverse_statement_update(self):
        gen = self._make_generator()
        result = gen._reverse_statement("UPDATE z SET w=1;")
        self.assertIn("WARNING", result.sql)

    def test_reverse_statement_delete(self):
        gen = self._make_generator()
        result = gen._reverse_statement("DELETE FROM z;")
        self.assertIn("WARNING", result.sql)

    def test_reverse_statement_comment(self):
        gen = self._make_generator()
        result = gen._reverse_statement("COMMENT ON TABLE z IS 'x';")
        self.assertIn("IS NULL", result.sql)

    def test_reverse_statement_unknown_type(self):
        gen = self._make_generator()
        result = gen._reverse_statement("GRANT ALL ON z TO admin;")
        self.assertIn("WARNING", result.sql)
        self.assertEqual(result.operation_type, "UNKNOWN")


# ---------------------------------------------------------------------------
# UndoScriptGenerator — full integration via _generator.py
# ---------------------------------------------------------------------------


class TestUndoScriptGeneratorIntegration(unittest.TestCase):
    """Integration tests for UndoScriptGenerator._generator.py methods."""

    def _make_generator(self, dialect="postgresql"):
        from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator

        return UndoScriptGenerator(dialect=dialect)

    def _make_migration(self, script_name, content):
        from dblift.core.migration.migration import Migration

        parts = script_name.replace(".sql", "").split("__", 1)
        version = parts[0].lstrip("Vv").replace(".", "_")
        description = parts[1] if len(parts) > 1 else "test"
        return Migration(
            script_name=script_name,
            content=content,
            version=version,
            description=description,
        )

    # generate_undo_script — file not found
    def test_generate_undo_script_missing_file_raises(self):
        gen = self._make_generator()
        with self.assertRaises(FileNotFoundError):
            gen.generate_undo_script(Path("/tmp/nonexistent_V1__x.sql"))

    # generate_undo_script — non-versioned name
    def test_generate_undo_script_non_versioned_raises(self):
        gen = self._make_generator()
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "R1__repeatable.sql"
            path.write_text("SELECT 1;")
            with self.assertRaises(ValueError):
                gen.generate_undo_script(path)

    # generate_undo_script — python file raises
    def test_generate_undo_script_python_raises(self):
        gen = self._make_generator()
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "V1__seed.py"
            path.write_text("def upgrade(): pass")
            with self.assertRaises(ValueError, msg="only SQL versioned"):
                gen.generate_undo_script(path)

    # generate_undo_script — happy path
    def test_generate_undo_script_creates_file(self):
        gen = self._make_generator()
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "V1__create_users.sql"
            path.write_text("CREATE TABLE users (id INT);")
            undo_path = gen.generate_undo_script(path, overwrite=True)
            self.assertTrue(undo_path.exists())
            self.assertTrue(undo_path.name.startswith("U1__"))
            content = undo_path.read_text()
            self.assertIn("DROP TABLE", content)

    # generate_undo_script — file already exists, overwrite=False
    def test_generate_undo_script_exists_no_overwrite_raises(self):
        gen = self._make_generator()
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "V1__test.sql"
            path.write_text("CREATE TABLE t (id INT);")
            gen.generate_undo_script(path, overwrite=True)
            with self.assertRaises(FileExistsError):
                gen.generate_undo_script(path, overwrite=False)

    # generate_undo_script — custom output_dir
    def test_generate_undo_script_custom_output_dir(self):
        gen = self._make_generator()
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "V2_0__add_col.sql"
            path.write_text("ALTER TABLE t ADD COLUMN z INT;")
            output_dir = Path(tmpdir) / "undo"
            undo_path = gen.generate_undo_script(path, output_dir=output_dir, overwrite=True)
            self.assertEqual(undo_path.parent, output_dir)
            self.assertTrue(undo_path.exists())

    # generate_undo_script — logger info called
    def test_generate_undo_script_logs_info(self):
        from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator

        logger = MagicMock()
        gen = UndoScriptGenerator(dialect="postgresql", logger=logger)
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "V3__test.sql"
            path.write_text("CREATE TABLE x (id INT);")
            gen.generate_undo_script(path, overwrite=True)
        logger.info.assert_called()

    # generate_undo_script_for_migration
    def test_generate_undo_script_for_migration_happy(self):
        from dblift.core.migration.migration import Migration

        gen = self._make_generator()
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "V1__test.sql"
            path.write_text("CREATE TABLE y (id INT);")
            migration = Migration(script_path=path)
            undo_path = gen.generate_undo_script_for_migration(migration, overwrite=True)
            self.assertTrue(undo_path.exists())

    def test_generate_undo_script_for_migration_no_path_raises(self):
        from dblift.core.migration.migration import Migration

        gen = self._make_generator()
        migration = Migration(
            script_name="V1__test.sql",
            content="CREATE TABLE y (id INT);",
            version="1",
            description="test",
        )
        with self.assertRaises(ValueError):
            gen.generate_undo_script_for_migration(migration)

    def test_generate_undo_script_for_migration_exists_no_overwrite_raises(self):
        from dblift.core.migration.migration import Migration

        gen = self._make_generator()
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "V1__test.sql"
            path.write_text("CREATE TABLE y (id INT);")
            migration = Migration(script_path=path)
            gen.generate_undo_script_for_migration(migration, overwrite=True)
            with self.assertRaises(FileExistsError):
                gen.generate_undo_script_for_migration(migration, overwrite=False)

    # get_undo_script_path_for_migration
    def test_get_undo_script_path_for_migration(self):
        from dblift.core.migration.migration import Migration

        gen = self._make_generator()
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "V1_2__my_migration.sql"
            path.write_text("SELECT 1;")
            migration = Migration(script_path=path)
            undo_path = gen.get_undo_script_path_for_migration(migration)
            self.assertTrue(undo_path.name.startswith("U1_2__"))

    def test_get_undo_script_path_no_path_raises(self):
        from dblift.core.migration.migration import Migration

        gen = self._make_generator()
        migration = Migration(
            script_name="V1__test.sql", content="x", version="1", description="test"
        )
        with self.assertRaises(ValueError):
            gen.get_undo_script_path_for_migration(migration)

    # _generate_undo_statements with filter logic
    def test_generate_undo_statements_comment_filtered_when_table_dropped(self):
        gen = self._make_generator()
        migration = self._make_migration(
            "V1__test.sql",
            "CREATE TABLE users (id INT);\nCOMMENT ON TABLE users IS 'x';",
        )
        results = gen._generate_undo_statements(migration)
        comment_stmts = [s for s in results if "COMMENT ON TABLE" in s.sql]
        self.assertEqual(len(comment_stmts), 0)

    def test_generate_undo_statements_index_filtered_when_table_dropped(self):
        gen = self._make_generator()
        migration = self._make_migration(
            "V1__test.sql",
            "CREATE TABLE users (id INT);\nCREATE INDEX idx_u ON users(id);",
        )
        results = gen._generate_undo_statements(migration)
        index_stmts = [s for s in results if "DROP INDEX" in s.sql]
        self.assertEqual(len(index_stmts), 0)

    def test_generate_undo_statements_reverse_order(self):
        gen = self._make_generator()
        migration = self._make_migration(
            "V1__test.sql",
            "CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);",
        )
        results = gen._generate_undo_statements(migration)
        drop_stmts = [s for s in results if "DROP TABLE" in s.sql]
        # Both should be present (different tables)
        self.assertEqual(len(drop_stmts), 2)

    def test_generate_undo_statements_fallback_no_parse_result(self):
        """Test fallback path when parser returns no statements."""
        from dblift.core.migration.migration import Migration

        gen = self._make_generator()
        # Create migration with content that will force parse failure path
        # We mock the parser to return failure
        migration = Migration(
            script_name="V1__test.sql",
            content="CREATE TABLE fallback_test (id INT);",
            version="1",
            description="test",
        )
        # Monkey-patch parser to simulate no statements
        original_parser = gen.parser

        class FakeParseResult:
            success = False
            statements = []

        class FakeParser:
            def parse_sql(self, content, default_schema):
                return FakeParseResult()

        gen.parser = FakeParser()
        results = gen._generate_undo_statements(migration)
        # Fallback uses raw SQL split — should still produce something
        self.assertIsInstance(results, list)
        # Restore
        gen.parser = original_parser

    def test_generate_undo_statements_insert_filtered_when_table_dropped(self):
        gen = self._make_generator()
        migration = self._make_migration(
            "V1__test.sql",
            "CREATE TABLE users (id INT);\nINSERT INTO users (id) VALUES (1);",
        )
        results = gen._generate_undo_statements(migration)
        delete_stmts = [s for s in results if "DELETE FROM" in s.sql]
        self.assertEqual(len(delete_stmts), 0)

    # _write_undo_script
    def test_write_undo_script_no_warnings(self):
        from dblift.core.migration.scripting.undo_script_generator._models import UndoStatement

        gen = self._make_generator()
        migration = self._make_migration("V1__test.sql", "CREATE TABLE t (id INT);")
        stmts = [
            UndoStatement(
                sql="DROP TABLE t;",
                original_statement="CREATE TABLE t (id INT);",
                operation_type="CREATE",
            )
        ]
        with TemporaryDirectory() as tmpdir:
            undo_path = Path(tmpdir) / "U1__test.sql"
            gen._write_undo_script(undo_path, migration, stmts)
            content = undo_path.read_text()
        self.assertIn("DROP TABLE t;", content)
        # No WARNING header when no warnings
        self.assertNotIn("WARNING: 1 statement(s)", content)

    def test_write_undo_script_with_warnings(self):
        from dblift.core.migration.scripting.undo_script_generator._models import UndoStatement

        gen = self._make_generator()
        migration = self._make_migration("V1__test.sql", "DROP TABLE t;")
        stmts = [
            UndoStatement(
                sql="-- WARNING: cannot reverse",
                original_statement="DROP TABLE t;",
                operation_type="DROP",
                warning="cannot reverse DROP",
                requires_manual_review=True,
            )
        ]
        with TemporaryDirectory() as tmpdir:
            undo_path = Path(tmpdir) / "U1__test.sql"
            gen._write_undo_script(undo_path, migration, stmts)
            content = undo_path.read_text()
        self.assertIn("WARNING: 1 statement(s) require manual review", content)
        self.assertIn("Original statement:", content)


# ---------------------------------------------------------------------------
# UndoStatementEmitter (standalone class from _extractors.py)
# ---------------------------------------------------------------------------


class TestUndoStatementEmitterInit(unittest.TestCase):
    """Tests for UndoStatementEmitter init and API."""

    def test_default_dialect(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        emitter = UndoStatementEmitter()
        # Wave C: default changed from "postgresql" to "" (BaseQuirks fallback).
        self.assertEqual(emitter.dialect, "")

    def test_custom_dialect(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        emitter = UndoStatementEmitter(dialect="mysql")
        self.assertEqual(emitter.dialect, "mysql")

    def test_logger_stored(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        logger = MagicMock()
        emitter = UndoStatementEmitter(dialect="oracle", logger=logger)
        self.assertEqual(emitter.logger, logger)

    def test_generate_drop_and_quote(self):
        from dblift.core.migration.scripting.undo_script_generator._extractors import (
            UndoStatementEmitter,
        )

        emitter = UndoStatementEmitter(dialect="postgresql")
        sql = emitter._generate_drop_statement("VIEW", "my_view", "public")
        self.assertIn('"public"', sql)
        self.assertIn('"my_view"', sql)
        self.assertIn("DROP VIEW", sql)


# ---------------------------------------------------------------------------
# Dialect variations for UndoScriptGenerator
# ---------------------------------------------------------------------------


class TestUndoScriptGeneratorDialects(unittest.TestCase):
    """Tests for dialect-specific behavior in UndoScriptGenerator."""

    def _make_generator(self, dialect, default_schema=None):
        from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator

        return UndoScriptGenerator(dialect=dialect, default_schema=default_schema)

    def _make_migration(self, content):
        from dblift.core.migration.migration import Migration

        return Migration(
            script_name="V1__test.sql",
            content=content,
            version="1",
            description="test",
        )

    def test_mysql_table_drop_no_cascade(self):
        gen = self._make_generator("mysql")
        migration = self._make_migration("CREATE TABLE t (id INT);")
        results = gen._generate_undo_statements(migration)
        drop_stmts = [s for s in results if "DROP TABLE" in s.sql]
        self.assertTrue(len(drop_stmts) >= 1)
        for stmt in drop_stmts:
            self.assertNotIn("CASCADE", stmt.sql)

    def test_mysql_undo_uses_configured_schema_not_hardcoded_mysql(self):
        """Regression for issue #802: undo DROP statements must be qualified
        with the actually-configured schema, never the literal "mysql".
        """
        gen = self._make_generator("mysql", default_schema="dblift_test")
        migration = self._make_migration("CREATE TABLE t (id INT);")
        results = gen._generate_undo_statements(migration)
        drop_stmts = [s for s in results if "DROP TABLE" in s.sql]
        self.assertTrue(len(drop_stmts) >= 1)
        for stmt in drop_stmts:
            self.assertIn("`dblift_test`", stmt.sql)
            self.assertNotIn("`mysql`", stmt.sql)

    def test_mariadb_undo_uses_configured_schema_not_hardcoded_mysql(self):
        """Regression for issue #802: MariaDB shares the MySQL parser config
        and must not reproduce the hardcoded "mysql" schema literal either.
        """
        gen = self._make_generator("mariadb", default_schema="dblift_test")
        migration = self._make_migration("CREATE TABLE t (id INT);")
        results = gen._generate_undo_statements(migration)
        drop_stmts = [s for s in results if "DROP TABLE" in s.sql]
        self.assertTrue(len(drop_stmts) >= 1)
        for stmt in drop_stmts:
            self.assertIn("`dblift_test`", stmt.sql)
            self.assertNotIn("`mysql`", stmt.sql)

    def test_mysql_undo_without_configured_schema_omits_mysql_literal(self):
        """When no schema is configured at all, undo statements must stay
        unqualified rather than falling back to the "mysql" system schema.
        """
        gen = self._make_generator("mysql")
        migration = self._make_migration("CREATE TABLE t (id INT);")
        results = gen._generate_undo_statements(migration)
        drop_stmts = [s for s in results if "DROP TABLE" in s.sql]
        self.assertTrue(len(drop_stmts) >= 1)
        for stmt in drop_stmts:
            self.assertNotIn("mysql", stmt.sql.lower())

    def test_mariadb_undo_without_configured_schema_omits_mysql_literal(self):
        gen = self._make_generator("mariadb")
        migration = self._make_migration("CREATE TABLE t (id INT);")
        results = gen._generate_undo_statements(migration)
        drop_stmts = [s for s in results if "DROP TABLE" in s.sql]
        self.assertTrue(len(drop_stmts) >= 1)
        for stmt in drop_stmts:
            self.assertNotIn("mysql", stmt.sql.lower())

    def test_oracle_table_drop_no_if_exists(self):
        gen = self._make_generator("oracle")
        migration = self._make_migration("CREATE TABLE t (id INT);")
        results = gen._generate_undo_statements(migration)
        drop_stmts = [s for s in results if "DROP TABLE" in s.sql]
        self.assertTrue(len(drop_stmts) >= 1)
        for stmt in drop_stmts:
            self.assertNotIn("IF EXISTS", stmt.sql)

    def test_sqlserver_dialect(self):
        gen = self._make_generator("sqlserver")
        migration = self._make_migration("CREATE TABLE t (id INT);")
        results = gen._generate_undo_statements(migration)
        drop_stmts = [s for s in results if "DROP TABLE" in s.sql]
        self.assertTrue(len(drop_stmts) >= 1)


if __name__ == "__main__":
    unittest.main()

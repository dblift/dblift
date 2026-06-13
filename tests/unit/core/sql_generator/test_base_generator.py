"""Tests for BaseSqlGenerator class."""

import inspect
from unittest.mock import MagicMock, patch

import pytest

from core.sql_generator.base_generator import BaseSqlGenerator
from core.sql_generator.formatter import SqlFormatter
from core.sql_generator.options import ScriptOptions
from core.sql_model import Index, Table
from core.sql_model.base import SqlColumn, SqlObjectType


class ConcreteBaseSqlGenerator(BaseSqlGenerator):
    """Concrete implementation of BaseSqlGenerator for testing."""

    def _get_create_dispatch(self):
        """Return dispatch for testing."""
        return {}

    def _generate_create_fallback(self, obj):
        """Fallback for testing."""
        if hasattr(obj, "create_statement"):
            return obj.create_statement
        return f"CREATE {obj.object_type.value} {obj.name}"

    def _generate_drop_statement(self, obj, dialect):
        """Generate DROP statement."""
        return f"DROP {obj.object_type.value} IF EXISTS {obj.name}"


@pytest.mark.unit
class TestBaseSqlGeneratorInit:
    """Test BaseSqlGenerator initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        generator = ConcreteBaseSqlGenerator()
        assert generator.default_dialect == ""
        assert isinstance(generator.formatter, SqlFormatter)
        assert generator.use_dependency_ordering is True

    def test_init_with_custom_formatter(self):
        """Test initialization with custom formatter."""
        formatter = SqlFormatter(dialect="oracle")
        generator = ConcreteBaseSqlGenerator(formatter=formatter)
        assert generator.formatter == formatter
        assert generator.default_dialect == ""

    def test_init_with_custom_dialect(self):
        """Test initialization with custom dialect."""
        generator = ConcreteBaseSqlGenerator(default_dialect="mysql")
        assert generator.default_dialect == "mysql"
        assert generator.formatter.dialect == "mysql"

    def test_init_with_dependency_ordering_false(self):
        """Test initialization with dependency ordering disabled."""
        generator = ConcreteBaseSqlGenerator(use_dependency_ordering=False)
        assert generator.use_dependency_ordering is False


@pytest.mark.unit
class TestBaseSqlGeneratorGenerateDdl:
    """Test BaseSqlGenerator.generate_ddl method."""

    def test_generate_ddl_empty_list(self):
        """Test generating DDL for empty list."""
        generator = ConcreteBaseSqlGenerator()
        result = generator.generate_ddl([])
        assert result == ""

    def test_generate_ddl_single_table(self):
        """Test generating DDL for a single table."""
        generator = ConcreteBaseSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        result = generator.generate_ddl([table])
        assert "CREATE TABLE" in result
        assert "users" in result

    def test_generate_ddl_with_target_dialect(self):
        """Test generating DDL with target dialect."""
        generator = ConcreteBaseSqlGenerator(default_dialect="postgresql")
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        result = generator.generate_ddl([table], target_dialect="oracle")
        assert generator.formatter.dialect == "oracle"
        assert "CREATE TABLE" in result

    def test_generate_ddl_with_dependency_ordering(self):
        """Test generating DDL with dependency ordering."""
        generator = ConcreteBaseSqlGenerator(use_dependency_ordering=True)
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        result = generator.generate_ddl([table], order_by_dependencies=True)
        assert "CREATE TABLE" in result

    def test_generate_ddl_dependency_ordering_failure(self):
        """Test handling dependency ordering failure."""
        generator = ConcreteBaseSqlGenerator(use_dependency_ordering=True)
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )

        # Mock dependency analyzer to raise exception
        generator.script_organizer.dependency_analyzer.get_create_order = lambda x: (
            _ for _ in ()
        ).throw(Exception("Dependency error"))

        result = generator.generate_ddl([table], order_by_dependencies=True)
        # Should still generate SQL despite error
        assert "CREATE TABLE" in result

    def test_generate_ddl_preserve_definition(self):
        """Test preserving definition when it's a complete DDL statement."""
        generator = ConcreteBaseSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        table.definition = "CREATE TABLE users (id INTEGER);"
        result = generator.generate_ddl([table], format_sql=True)
        assert "CREATE TABLE users" in result

    def test_generate_ddl_skip_formatting(self):
        """Test skipping formatting for certain object types."""
        generator = ConcreteBaseSqlGenerator()
        from core.sql_model import Procedure

        procedure = Procedure(
            name="test_proc",
            definition="BEGIN END",
            dialect="postgresql",
        )
        result = generator.generate_ddl([procedure], format_sql=True)
        # Procedure should generate SQL (may be definition or CREATE statement)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_ddl_exception_handling(self):
        """Test exception handling during DDL generation."""
        generator = ConcreteBaseSqlGenerator()
        obj = MagicMock()
        obj.name = "test_object"
        obj.object_type = SqlObjectType.TABLE
        obj.definition = None
        obj.create_statement = property(lambda self: (_ for _ in ()).throw(Exception("Error")))

        result = generator.generate_ddl([obj])
        # Should handle gracefully
        assert isinstance(result, str)

    def test_generate_ddl_empty_create_statement(self):
        """Test handling empty CREATE statement."""
        generator = ConcreteBaseSqlGenerator()
        obj = MagicMock()
        obj.name = "test_object"
        obj.object_type = SqlObjectType.TABLE
        obj.definition = None
        obj.create_statement = ""

        result = generator.generate_ddl([obj])
        # Should handle gracefully
        assert isinstance(result, str)

    def test_generate_ddl_mysql_wrapping(self):
        """Test MySQL DELIMITER wrapping."""
        generator = ConcreteBaseSqlGenerator(default_dialect="mysql")
        from core.sql_model import Procedure

        procedure = Procedure(
            name="test_proc",
            definition="BEGIN END",
            dialect="mysql",
        )
        result = generator.generate_ddl([procedure], target_dialect="mysql")
        # MySQL procedures should generate SQL (wrapping is handled by _wrap_dialect_specific_block)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_ddl_additional_statements(self):
        """Test generating additional statements."""
        generator = ConcreteBaseSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        result = generator.generate_ddl([table])
        assert "CREATE TABLE" in result


@pytest.mark.unit
class TestBaseSqlGeneratorGenerateDropStatements:
    """Test BaseSqlGenerator.generate_drop_statements method."""

    def test_generate_drop_statements_empty(self):
        """Test generating DROP statements for empty list."""
        generator = ConcreteBaseSqlGenerator()
        result = generator.generate_drop_statements([])
        assert result == ""

    def test_generate_drop_statements_single_table(self):
        """Test generating DROP statements for a single table."""
        generator = ConcreteBaseSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        result = generator.generate_drop_statements([table])
        assert "DROP TABLE" in result
        assert "users" in result

    def test_generate_drop_statements_with_formatting(self):
        """Test generating DROP statements with formatting."""
        generator = ConcreteBaseSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        result = generator.generate_drop_statements([table], format_sql=True)
        assert "DROP TABLE" in result

    def test_generate_drop_statements_dependency_ordering_failure(self):
        """Test handling dependency ordering failure for DROP."""
        generator = ConcreteBaseSqlGenerator(use_dependency_ordering=True)
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )

        # Mock dependency analyzer to raise exception
        generator.script_organizer.dependency_analyzer.get_drop_order = lambda x: (
            _ for _ in ()
        ).throw(Exception("Dependency error"))

        result = generator.generate_drop_statements([table], order_by_dependencies=True)
        # Should still generate SQL despite error
        assert "DROP TABLE" in result

    def test_generate_drop_statements_exception_handling(self):
        """Test exception handling during DROP generation."""
        generator = ConcreteBaseSqlGenerator()
        obj = MagicMock()
        obj.name = "test_object"
        obj.object_type = SqlObjectType.TABLE
        obj.format_identifier = lambda x: (_ for _ in ()).throw(Exception("Error"))

        result = generator.generate_drop_statements([obj])
        # Should handle gracefully
        assert isinstance(result, str)


@pytest.mark.unit
class TestBaseSqlGeneratorGenerateSchemaScript:
    """Test BaseSqlGenerator.generate_schema_script method."""

    def test_generate_schema_script_empty(self):
        """Test generating schema script for empty schema."""
        generator = ConcreteBaseSqlGenerator()
        result = generator.generate_schema_script({})
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_generate_schema_script_single_table(self):
        """Test generating schema script for single table."""
        generator = ConcreteBaseSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        schema = {"tables": [table]}
        result = generator.generate_schema_script(schema)
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_generate_schema_script_with_options(self):
        """Test generating schema script with options."""
        generator = ConcreteBaseSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        schema = {"tables": [table]}
        options = ScriptOptions(include_drops=True, include_comments=True)
        result = generator.generate_schema_script(schema, options=options)
        assert isinstance(result, dict)

    def test_generate_schema_script_with_drops(self):
        """Test generating schema script with DROP statements."""
        generator = ConcreteBaseSqlGenerator()
        table = Table(
            name="users",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        schema = {"tables": [table]}
        options = ScriptOptions(include_drops=True)
        result = generator.generate_schema_script(schema, options=options)
        # Check that result contains SQL
        assert any("DROP" in content or "CREATE" in content for content in result.values())


@pytest.mark.unit
class TestBaseSqlGeneratorHelperMethods:
    """Test BaseSqlGenerator helper methods."""

    def test_should_preserve_definition_none(self):
        """Test _should_preserve_definition with None."""
        generator = ConcreteBaseSqlGenerator()
        result = generator._should_preserve_definition(None)
        assert result is False

    def test_should_preserve_definition_empty(self):
        """Test _should_preserve_definition with empty string."""
        generator = ConcreteBaseSqlGenerator()
        result = generator._should_preserve_definition("")
        assert result is False

    def test_should_preserve_definition_create(self):
        """Test _should_preserve_definition with CREATE."""
        generator = ConcreteBaseSqlGenerator()
        result = generator._should_preserve_definition("CREATE TABLE test")
        assert result is True

    def test_should_preserve_definition_alter(self):
        """Test _should_preserve_definition with ALTER."""
        generator = ConcreteBaseSqlGenerator()
        result = generator._should_preserve_definition("ALTER TABLE test ADD COLUMN x INT")
        assert result is True

    def test_should_preserve_definition_replace(self):
        """Test _should_preserve_definition with REPLACE."""
        generator = ConcreteBaseSqlGenerator()
        result = generator._should_preserve_definition("REPLACE VIEW test AS SELECT 1")
        assert result is True

    def test_should_preserve_definition_lowercase(self):
        """Test _should_preserve_definition with lowercase."""
        generator = ConcreteBaseSqlGenerator()
        result = generator._should_preserve_definition("create table test")
        assert result is True

    def test_should_preserve_definition_other(self):
        """Test _should_preserve_definition with other statement."""
        generator = ConcreteBaseSqlGenerator()
        result = generator._should_preserve_definition("SELECT * FROM test")
        assert result is False

    def test_should_skip_formatting_procedure(self):
        """Test _should_skip_formatting for procedure."""
        generator = ConcreteBaseSqlGenerator()
        from core.sql_model import Procedure

        procedure = Procedure(name="test_proc", definition="BEGIN END", dialect="postgresql")
        result = generator._should_skip_formatting(procedure, "CREATE PROCEDURE test_proc")
        assert result is True

    def test_should_skip_formatting_function(self):
        """Test _should_skip_formatting for function."""
        generator = ConcreteBaseSqlGenerator()
        from core.sql_model import Procedure

        func = Procedure(name="test_func", definition="RETURN 1", dialect="postgresql")
        func.object_type = SqlObjectType.FUNCTION
        result = generator._should_skip_formatting(func, "CREATE FUNCTION test_func")
        assert result is True

    def test_should_skip_formatting_table(self):
        """Test _should_skip_formatting for table."""
        generator = ConcreteBaseSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        result = generator._should_skip_formatting(table, "CREATE TABLE users")
        assert result is False

    def test_requires_dialect_specific_wrapping_mysql_procedure(self):
        """Test _requires_dialect_specific_wrapping for MySQL procedure."""
        generator = ConcreteBaseSqlGenerator()
        from core.sql_model import Procedure

        procedure = Procedure(name="test_proc", definition="BEGIN END", dialect="mysql")
        result = generator._requires_dialect_specific_wrapping(procedure, "mysql")
        assert result is True

    def test_requires_dialect_specific_wrapping_postgresql_procedure(self):
        """Test _requires_dialect_specific_wrapping for PostgreSQL procedure."""
        generator = ConcreteBaseSqlGenerator()
        from core.sql_model import Procedure

        procedure = Procedure(name="test_proc", definition="BEGIN END", dialect="postgresql")
        result = generator._requires_dialect_specific_wrapping(procedure, "postgresql")
        assert result is False

    def test_requires_dialect_specific_wrapping_no_dialect(self):
        """Test _requires_dialect_specific_wrapping with no dialect."""
        generator = ConcreteBaseSqlGenerator()
        from core.sql_model import Procedure

        procedure = Procedure(name="test_proc", definition="BEGIN END", dialect="mysql")
        result = generator._requires_dialect_specific_wrapping(procedure, "")
        assert result is False

    def test_wrap_dialect_specific_block_default(self):
        """Test _wrap_dialect_specific_block default implementation."""
        generator = ConcreteBaseSqlGenerator()
        sql = "CREATE PROCEDURE test BEGIN END"
        result = generator._wrap_dialect_specific_block(sql, "postgresql")
        assert result == sql

    def test_format_statements_empty(self):
        """Test _format_statements with empty list."""
        generator = ConcreteBaseSqlGenerator()
        result = generator._format_statements([], "postgresql")
        assert result == ""

    def test_format_statements_single(self):
        """Test _format_statements with single statement."""
        generator = ConcreteBaseSqlGenerator()
        result = generator._format_statements(["CREATE TABLE test;"], "postgresql")
        assert result == "CREATE TABLE test;"

    def test_format_statements_multiple(self):
        """Test _format_statements with multiple statements."""
        generator = ConcreteBaseSqlGenerator()
        statements = ["CREATE TABLE test1;", "CREATE TABLE test2;"]
        result = generator._format_statements(statements, "postgresql")
        assert "CREATE TABLE test1" in result
        assert "CREATE TABLE test2" in result
        assert "\n\n" in result

    def test_format_statements_filters_empty(self):
        """Test _format_statements filters empty statements."""
        generator = ConcreteBaseSqlGenerator()
        statements = ["CREATE TABLE test1;", "", "   ", "CREATE TABLE test2;"]
        result = generator._format_statements(statements, "postgresql")
        assert "CREATE TABLE test1" in result
        assert "CREATE TABLE test2" in result
        assert result.count("CREATE TABLE") == 2

    def test_generate_additional_statements_empty(self):
        """Test _generate_additional_statements with no additional statements."""
        generator = ConcreteBaseSqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        result = generator._generate_additional_statements(table, "postgresql")
        assert result == []

    def test_generate_additional_statements_index_with_comment(self):
        """Test _generate_additional_statements for index with comment."""
        generator = ConcreteBaseSqlGenerator()
        index = Index(
            name="idx_test",
            table_name="users",
            columns=["id"],
            comment="Test comment",
            dialect="postgresql",
        )
        result = generator._generate_additional_statements(index, "postgresql")
        # Should generate COMMENT ON INDEX statement
        assert len(result) > 0
        assert "COMMENT ON INDEX" in result[0]

    def test_generate_index_comment_statement_postgresql(self):
        """Test _generate_index_comment_statement for PostgreSQL."""
        generator = ConcreteBaseSqlGenerator()
        index = Index(
            name="idx_test",
            table_name="users",
            columns=["id"],
            comment="Test comment",
            dialect="postgresql",
        )
        result = generator._generate_index_comment_statement(index, "postgresql")
        assert "COMMENT ON INDEX" in result
        assert "idx_test" in result
        assert "Test comment" in result

    def test_generate_index_comment_statement_oracle(self):
        """Test _generate_index_comment_statement for Oracle."""
        generator = ConcreteBaseSqlGenerator()
        index = Index(
            name="idx_test",
            table_name="users",
            columns=["id"],
            comment="Test comment",
            dialect="oracle",
        )
        result = generator._generate_index_comment_statement(index, "oracle")
        assert "COMMENT ON INDEX" in result

    def test_generate_index_comment_statement_mysql(self):
        """Test _generate_index_comment_statement for MySQL."""
        generator = ConcreteBaseSqlGenerator()
        index = Index(
            name="idx_test",
            table_name="users",
            columns=["id"],
            comment="Test comment",
            dialect="mysql",
        )
        result = generator._generate_index_comment_statement(index, "mysql")
        # MySQL doesn't support COMMENT ON INDEX
        assert result == ""

    def test_generate_index_comment_statement_sqlserver(self):
        """Test _generate_index_comment_statement for SQL Server."""
        generator = ConcreteBaseSqlGenerator()
        index = Index(
            name="idx_test",
            table_name="users",
            columns=["id"],
            comment="Test comment",
            dialect="sqlserver",
        )
        result = generator._generate_index_comment_statement(index, "sqlserver")
        # SQL Server doesn't support COMMENT ON INDEX
        assert result == ""

    def test_generate_index_comment_statement_with_schema(self):
        """Test _generate_index_comment_statement with schema."""
        generator = ConcreteBaseSqlGenerator()
        index = Index(
            name="idx_test",
            table_name="users",
            columns=["id"],
            comment="Test comment",
            schema="public",
            dialect="postgresql",
        )
        result = generator._generate_index_comment_statement(index, "postgresql")
        assert "public" in result

    def test_generate_index_comment_statement_escapes_quotes(self):
        """Test _generate_index_comment_statement escapes single quotes."""
        generator = ConcreteBaseSqlGenerator()
        index = Index(
            name="idx_test",
            table_name="users",
            columns=["id"],
            comment="Test's comment",
            dialect="postgresql",
        )
        result = generator._generate_index_comment_statement(index, "postgresql")
        assert "Test''s comment" in result

    def test_ensure_statement_terminated_empty(self):
        """Test _ensure_statement_terminated with empty string."""
        generator = ConcreteBaseSqlGenerator()
        result = generator._ensure_statement_terminated("")
        assert result == ""

    def test_ensure_statement_terminated_with_semicolon(self):
        """Test _ensure_statement_terminated with semicolon."""
        generator = ConcreteBaseSqlGenerator()
        result = generator._ensure_statement_terminated("CREATE TABLE test;")
        assert result == "CREATE TABLE test;"

    def test_ensure_statement_terminated_without_semicolon(self):
        """Test _ensure_statement_terminated without semicolon."""
        generator = ConcreteBaseSqlGenerator()
        result = generator._ensure_statement_terminated("CREATE TABLE test")
        assert result == "CREATE TABLE test;"

    def test_ensure_statement_terminated_with_whitespace(self):
        """Test _ensure_statement_terminated with trailing whitespace."""
        generator = ConcreteBaseSqlGenerator()
        result = generator._ensure_statement_terminated("CREATE TABLE test   \n  ")
        assert result == "CREATE TABLE test;"


@pytest.mark.unit
class TestGenerateCreateStatementDispatch:
    """Tests du mécanisme de dispatch dans BaseSqlGenerator."""

    def test_generate_create_statement_uses_dispatch(self):
        """Le dispatcher appelle la méthode correspondante au type."""
        from core.sql_model.base import SqlObject, SqlObjectType

        class MockSqlObject(SqlObject):
            def __init__(self):
                super().__init__(name="mock", object_type=SqlObjectType.TABLE, dialect="test")

        class ConcreteGen(BaseSqlGenerator):
            def _get_create_dispatch(self):
                return {MockSqlObject: "_mock_create"}

            def _mock_create(self, obj):
                return "MOCK_SQL"

            def _generate_drop_statement(self, obj, dialect):
                return ""

        gen = ConcreteGen()
        obj = MockSqlObject()
        result = gen.generate_create_statement(obj)
        assert result == "MOCK_SQL"

    def test_generate_create_statement_unknown_type_uses_fallback(self):
        """Type non-dispatché → _generate_create_fallback."""

        class ConcreteGen(BaseSqlGenerator):
            def _get_create_dispatch(self):
                return {}

            def _generate_create_fallback(self, obj):
                return "FALLBACK"

            def _generate_drop_statement(self, obj, dialect):
                return ""

        gen = ConcreteGen()
        result = gen.generate_create_statement(MagicMock())
        assert result == "FALLBACK"

    def test_get_create_dispatch_returns_eight_common_types_in_base(self):
        """BaseSqlGenerator._get_create_dispatch retourne les 8 types communs (story 21-10).

        Previously returned {}, now returns the 8 types shared by all dialect generators:
        View, Index, Procedure, Table, Synonym, Sequence, UserDefinedType, Trigger.
        """
        from core.sql_model.index import Index
        from core.sql_model.procedure import Procedure
        from core.sql_model.sequence import Sequence
        from core.sql_model.synonym import Synonym
        from core.sql_model.table import Table
        from core.sql_model.trigger import Trigger
        from core.sql_model.user_defined_type import UserDefinedType
        from core.sql_model.view import View

        class MinimalGen(BaseSqlGenerator):
            def _generate_drop_statement(self, obj, dialect):
                return ""

        gen = MinimalGen()
        dispatch = gen._get_create_dispatch()
        assert isinstance(dispatch, dict)
        assert len(dispatch) == 8
        expected_types = {
            View,
            Index,
            Procedure,
            Table,
            Synonym,
            Sequence,
            UserDefinedType,
            Trigger,
        }
        assert set(dispatch.keys()) == expected_types

    def test_generate_create_fallback_default_uses_getattr(self):
        """Le fallback par défaut utilise getattr(obj, 'create_statement', '')."""

        class MinimalGen(BaseSqlGenerator):
            def _generate_drop_statement(self, obj, dialect):
                return ""

        gen = MinimalGen()

        # Object with create_statement attribute
        obj_with = MagicMock()
        obj_with.create_statement = "CREATE TABLE t"
        assert gen._generate_create_fallback(obj_with) == "CREATE TABLE t"

        # Object without create_statement attribute
        obj_without = object()
        assert gen._generate_create_fallback(obj_without) == ""


@pytest.mark.unit
class TestBuildSchemaPrefix:
    """Tests de la méthode statique _build_schema_prefix dans BaseSqlGenerator."""

    def test_build_schema_prefix_with_schema_name(self):
        assert BaseSqlGenerator._build_schema_prefix("myschema") == "myschema."

    def test_build_schema_prefix_with_quoted_schema(self):
        assert BaseSqlGenerator._build_schema_prefix('"public"') == '"public".'

    def test_build_schema_prefix_with_none(self):
        assert BaseSqlGenerator._build_schema_prefix(None) == ""

    def test_build_schema_prefix_with_empty_string(self):
        assert BaseSqlGenerator._build_schema_prefix("") == ""

    def test_build_schema_prefix_is_static_method(self):
        assert isinstance(
            inspect.getattr_static(BaseSqlGenerator, "_build_schema_prefix"),
            staticmethod,
        )

    def test_build_schema_prefix_accessible_on_instance(self):
        gen = ConcreteBaseSqlGenerator()
        assert gen._build_schema_prefix("dbo") == "dbo."

    def test_build_schema_prefix_with_whitespace_only_string(self):
        # Une chaîne whitespace-only est truthy → retourne "   ." (comportement documenté)
        result = BaseSqlGenerator._build_schema_prefix("   ")
        assert result == "   ."

    def test_build_schema_prefix_format_identifier_returns_empty_for_truthy_schema(self):
        # Documente le comportement refactorisé Pattern 1 :
        # si format_identifier retourne "" pour un schema truthy,
        # _build_schema_prefix("") retourne "" (mieux que l'original qui donnait ".")
        result = BaseSqlGenerator._build_schema_prefix("")
        assert result == ""  # pas "." — comportement amélioré vs l'original if-guard

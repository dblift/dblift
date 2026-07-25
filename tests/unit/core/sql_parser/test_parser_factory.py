"""Tests for SQL parser factory."""

import importlib
from unittest.mock import MagicMock, Mock, patch

import pytest

from core.exceptions import ParserNotAvailableError, UnsupportedDialectError
from core.sql_model.base import (
    ParseResult,
    SqlObject,
    SqlStatement,
    SqlStatementType,
)
from core.sql_parser.common.base_parser import RegexBasedParser
from core.sql_parser.parser_factory import SqlParserFactory
from core.sql_parser.parser_interface import SqlParserInterface


@pytest.mark.unit
class TestSqlParserFactory:
    """Test SQL parser factory functionality."""

    def test_factory_initialization(self):
        """Test factory initialization."""
        factory = SqlParserFactory("postgresql")

        assert factory.dialect == "postgresql"
        assert factory.dialect_name == "postgresql"
        assert factory._current_parser is None

    def test_factory_initialization_uppercase(self):
        """Test factory initialization with uppercase dialect."""
        factory = SqlParserFactory("ORACLE")

        assert factory.dialect == "oracle"
        assert factory.dialect_name == "oracle"

    def test_factory_initialization_mixed_case(self):
        """Test factory initialization with mixed case dialect."""
        factory = SqlParserFactory("SqlServer")

        assert factory.dialect == "sqlserver"
        assert factory.dialect_name == "sqlserver"

    def test_parser_class_resolves_for_expected_dialects(self):
        """Story 26-9: parser classes come from plugin Quirks. Each
        first-party plugin must return a non-None class for the
        ``"hybrid"`` parser type."""
        from db.provider_registry import ProviderRegistry

        ProviderRegistry.discover_plugins()
        for dialect in (
            "oracle",
            "sqlserver",
            "db2",
            "postgresql",
            "mysql",
            "sqlite",
        ):
            cls = ProviderRegistry.get_quirks(dialect).parser_class("hybrid")
            assert cls is not None, f"{dialect} hybrid parser_class is None"
        # CosmosDB is deliberately absent: it has no SQL to parse.
        assert ProviderRegistry.get_quirks("cosmosdb").parser_class("hybrid") is None

    def test_cosmosdb_has_no_regex_parser(self):
        """CosmosDB's pseudo-SQL grammar is gone, so no regex parser resolves.

        The dedicated parser existed only to read ``CREATE CONTAINER`` /
        ``SET THROUGHPUT`` pseudo-DDL for the SDK translator. Cosmos
        migrations are Python now, so asking for one is an error rather
        than a silent fallback.
        """
        from core.exceptions import UnsupportedDialectError

        factory = SqlParserFactory("cosmosdb", parser_type="regex")

        with pytest.raises(UnsupportedDialectError):
            factory.get_parser()

    @pytest.mark.parametrize("parser_type", ["regex", "hybrid", "sqlglot"])
    def test_cosmosdb_resolves_no_parser_at_all(self, parser_type):
        """Cosmos has no SQL for dblift to parse, whichever parser is asked for."""
        factory = SqlParserFactory("cosmosdb", parser_type=parser_type)

        with pytest.raises((UnsupportedDialectError, ParserNotAvailableError, ValueError)):
            factory.get_parser()

    def test_hybrid_parser_class_is_HybridParser_for_jdbc_dialects(self):
        """Story 26-9: most dialects route ``hybrid`` to HybridParser."""
        from core.sql_parser.hybrid_parser import HybridParser
        from db.provider_registry import ProviderRegistry

        for dialect in ("oracle", "sqlserver", "db2", "postgresql", "mysql"):
            cls = ProviderRegistry.get_quirks(dialect).parser_class("hybrid")
            assert cls is HybridParser, f"{dialect}: expected HybridParser, got {cls!r}"

    def test_create_parser_quirks_failure_propagates_as_parser_not_available(self):
        """When a plugin's ``parser_class`` raises, the factory wraps it."""
        factory = SqlParserFactory("postgresql")
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks("postgresql")
        with patch.object(quirks, "parser_class", side_effect=Exception("Boom")):
            with pytest.raises(
                ParserNotAvailableError,
                match="No hybrid parser available for dialect postgresql",
            ):
                factory._create_parser()

    def test_create_parser_unknown_dialect_fallback(self):
        """Test parser creation for unknown dialect throws error."""
        factory = SqlParserFactory("unknown_dialect")

        with pytest.raises(UnsupportedDialectError, match="Unsupported dialect: unknown_dialect"):
            factory._create_parser()

    def test_create_parser_returns_none_class_raises_unsupported(self):
        """When a plugin's quirks returns None for the parser type,
        the factory raises ``UnsupportedDialectError`` (matches the
        legacy ``Unsupported dialect:`` message)."""
        factory = SqlParserFactory("postgresql", parser_type="some-bogus-type")

        with pytest.raises(UnsupportedDialectError, match="Unsupported dialect"):
            factory._create_parser()

    def test_parse_sql_creates_parser_on_first_call(self):
        """Test that parse_sql creates parser on first call."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock(spec=SqlParserInterface)
        mock_result = ParseResult(success=True, statements=[], errors=[])
        mock_parser.parse_sql.return_value = mock_result

        with patch.object(factory, "_create_parser", return_value=mock_parser):
            result = factory.parse_sql("SELECT 1")

            assert factory._current_parser == mock_parser
            mock_parser.parse_sql.assert_called_once_with("SELECT 1", None)
            assert result == mock_result

    def test_parse_sql_reuses_existing_parser(self):
        """Test that parse_sql reuses existing parser."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock(spec=SqlParserInterface)
        mock_result = ParseResult(success=True, statements=[], errors=[])
        mock_parser.parse_sql.return_value = mock_result

        factory._current_parser = mock_parser

        with patch.object(factory, "_create_parser") as mock_create:
            result = factory.parse_sql("SELECT 1", "test_schema")

            mock_create.assert_not_called()
            mock_parser.parse_sql.assert_called_once_with("SELECT 1", "test_schema")
            assert result == mock_result

    def test_split_statements_creates_parser_on_first_call(self):
        """Test that split_statements creates parser on first call."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock(spec=SqlParserInterface)
        mock_statements = ["SELECT 1", "SELECT 2"]
        mock_parser.split_statements.return_value = mock_statements

        with patch.object(factory, "_create_parser", return_value=mock_parser):
            result = factory.split_statements("SELECT 1; SELECT 2")

            assert factory._current_parser == mock_parser
            mock_parser.split_statements.assert_called_once_with("SELECT 1; SELECT 2")
            assert result == mock_statements

    def test_split_statements_reuses_existing_parser(self):
        """Test that split_statements reuses existing parser."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock(spec=SqlParserInterface)
        mock_statements = ["SELECT 1", "SELECT 2"]
        mock_parser.split_statements.return_value = mock_statements

        factory._current_parser = mock_parser

        with patch.object(factory, "_create_parser") as mock_create:
            result = factory.split_statements("SELECT 1; SELECT 2")

            mock_create.assert_not_called()
            mock_parser.split_statements.assert_called_once_with("SELECT 1; SELECT 2")
            assert result == mock_statements

    def test_validate_sql_creates_parser_on_first_call(self):
        """Test that validate_sql creates parser on first call."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock(spec=SqlParserInterface)
        mock_validation = {"success": True, "errors": []}
        mock_parser.validate_sql.return_value = mock_validation

        with patch.object(factory, "_create_parser", return_value=mock_parser):
            result = factory.validate_sql("SELECT 1")

            assert factory._current_parser == mock_parser
            mock_parser.validate_sql.assert_called_once_with("SELECT 1")
            assert result == mock_validation

    def test_validate_sql_reuses_existing_parser(self):
        """Test that validate_sql reuses existing parser."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock(spec=SqlParserInterface)
        mock_validation = {"success": True, "errors": []}
        mock_parser.validate_sql.return_value = mock_validation

        factory._current_parser = mock_parser

        with patch.object(factory, "_create_parser") as mock_create:
            result = factory.validate_sql("SELECT 1")

            mock_create.assert_not_called()
            mock_parser.validate_sql.assert_called_once_with("SELECT 1")
            assert result == mock_validation

    def test_extract_objects_creates_parser_on_first_call(self):
        """Test that extract_objects creates parser on first call."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock(spec=SqlParserInterface)
        mock_objects = [Mock(spec=SqlObject)]
        mock_parser.extract_objects.return_value = mock_objects

        with patch.object(factory, "_create_parser", return_value=mock_parser):
            result = factory.extract_objects("CREATE TABLE test (id INT)")

            assert factory._current_parser == mock_parser
            mock_parser.extract_objects.assert_called_once_with("CREATE TABLE test (id INT)", None)
            assert result == mock_objects

    def test_extract_objects_reuses_existing_parser(self):
        """Test that extract_objects reuses existing parser."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock(spec=SqlParserInterface)
        mock_objects = [Mock(spec=SqlObject)]
        mock_parser.extract_objects.return_value = mock_objects

        factory._current_parser = mock_parser

        with patch.object(factory, "_create_parser") as mock_create:
            result = factory.extract_objects("CREATE TABLE test (id INT)", "test_schema")

            mock_create.assert_not_called()
            mock_parser.extract_objects.assert_called_once_with(
                "CREATE TABLE test (id INT)", "test_schema"
            )
            assert result == mock_objects

    def test_parse_creates_parser_on_first_call(self):
        """Test that parse creates parser on first call."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock(spec=SqlParserInterface)
        mock_statement = Mock(spec=SqlStatement)
        mock_parser.parse.return_value = mock_statement

        with patch.object(factory, "_create_parser", return_value=mock_parser):
            result = factory.parse("SELECT 1")

            assert factory._current_parser == mock_parser
            mock_parser.parse.assert_called_once_with("SELECT 1", None)
            assert result == mock_statement

    def test_parse_reuses_existing_parser(self):
        """Test that parse reuses existing parser."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock(spec=SqlParserInterface)
        mock_statement = Mock(spec=SqlStatement)
        mock_parser.parse.return_value = mock_statement

        factory._current_parser = mock_parser

        with patch.object(factory, "_create_parser") as mock_create:
            result = factory.parse("SELECT 1", "test_schema")

            mock_create.assert_not_called()
            mock_parser.parse.assert_called_once_with("SELECT 1", "test_schema")
            assert result == mock_statement

    def test_get_affected_objects_creates_parser_on_first_call(self):
        """Test that get_affected_objects creates parser on first call."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock(spec=SqlParserInterface)
        mock_objects = [Mock(spec=SqlObject)]
        mock_parser.get_affected_objects.return_value = mock_objects

        with patch.object(factory, "_create_parser", return_value=mock_parser):
            result = factory.get_affected_objects("UPDATE test SET value = 1")

            assert factory._current_parser == mock_parser
            mock_parser.get_affected_objects.assert_called_once_with(
                "UPDATE test SET value = 1", None
            )
            assert result == mock_objects

    def test_get_affected_objects_reuses_existing_parser(self):
        """Test that get_affected_objects reuses existing parser."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock(spec=SqlParserInterface)
        mock_objects = [Mock(spec=SqlObject)]
        mock_parser.get_affected_objects.return_value = mock_objects

        factory._current_parser = mock_parser

        with patch.object(factory, "_create_parser") as mock_create:
            result = factory.get_affected_objects("UPDATE test SET value = 1", "test_schema")

            mock_create.assert_not_called()
            mock_parser.get_affected_objects.assert_called_once_with(
                "UPDATE test SET value = 1", "test_schema"
            )
            assert result == mock_objects

    def test_get_errors_no_parser(self):
        """Test get_errors returns empty list when no parser."""
        factory = SqlParserFactory("postgresql")

        result = factory.get_errors()

        assert result == []

    def test_get_errors_parser_has_get_errors_method(self):
        """Test get_errors delegates to parser when method exists."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock()
        mock_errors = ["Error 1", "Error 2"]
        mock_parser.get_errors.return_value = mock_errors

        factory._current_parser = mock_parser

        result = factory.get_errors()

        assert result == mock_errors
        mock_parser.get_errors.assert_called_once()

    def test_get_errors_parser_no_get_errors_method(self):
        """Test get_errors returns empty list when parser lacks method."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock()
        # Don't set up get_errors method - it won't exist
        del mock_parser.get_errors

        factory._current_parser = mock_parser

        result = factory.get_errors()

        assert result == []

    def test_get_errors_parser_get_errors_returns_non_list(self):
        """Test get_errors handles non-list return from parser."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock()
        mock_parser.get_errors.return_value = "not a list"

        factory._current_parser = mock_parser

        result = factory.get_errors()

        assert result == []

    def test_is_valid_no_parser(self):
        """Test is_valid returns False when no parser."""
        factory = SqlParserFactory("postgresql")

        result = factory.is_valid

        assert result is False

    def test_is_valid_parser_has_is_valid_property(self):
        """Test is_valid delegates to parser when property exists."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock()
        mock_parser.is_valid = True

        factory._current_parser = mock_parser

        result = factory.is_valid

        assert result is True

    def test_is_valid_parser_no_is_valid_property(self):
        """Test is_valid returns False when parser lacks property."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock()
        del mock_parser.is_valid

        factory._current_parser = mock_parser

        result = factory.is_valid

        assert result is False

    def test_is_ddl_no_parser(self):
        """Test is_ddl returns False when no parser."""
        factory = SqlParserFactory("postgresql")

        result = factory.is_ddl

        assert result is False

    def test_is_ddl_parser_has_is_ddl_property(self):
        """Test is_ddl delegates to parser when property exists."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock()
        mock_parser.is_ddl = True

        factory._current_parser = mock_parser

        result = factory.is_ddl

        assert result is True

    def test_is_ddl_parser_no_is_ddl_property(self):
        """Test is_ddl returns False when parser lacks property."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock()
        del mock_parser.is_ddl

        factory._current_parser = mock_parser

        result = factory.is_ddl

        assert result is False

    def test_is_dml_no_parser(self):
        """Test is_dml returns False when no parser."""
        factory = SqlParserFactory("postgresql")

        result = factory.is_dml

        assert result is False

    def test_is_dml_parser_has_is_dml_property(self):
        """Test is_dml delegates to parser when property exists."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock()
        mock_parser.is_dml = True

        factory._current_parser = mock_parser

        result = factory.is_dml

        assert result is True

    def test_is_dml_parser_no_is_dml_property(self):
        """Test is_dml returns False when parser lacks property."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock()
        del mock_parser.is_dml

        factory._current_parser = mock_parser

        result = factory.is_dml

        assert result is False

    def test_is_query_no_parser(self):
        """Test is_query returns False when no parser."""
        factory = SqlParserFactory("postgresql")

        result = factory.is_query

        assert result is False

    def test_is_query_parser_has_is_query_property(self):
        """Test is_query delegates to parser when property exists."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock()
        mock_parser.is_query = True

        factory._current_parser = mock_parser

        result = factory.is_query

        assert result is True

    def test_is_query_parser_no_is_query_property(self):
        """Test is_query returns False when parser lacks property."""
        factory = SqlParserFactory("postgresql")
        mock_parser = Mock()
        del mock_parser.is_query

        factory._current_parser = mock_parser

        result = factory.is_query

        assert result is False

    def test_get_parser_quirks_failure_wraps_as_parser_not_available(self):
        """When a plugin's ``parser_class`` raises during ``get_parser``,
        the factory wraps it in ``ParserNotAvailableError``."""
        factory = SqlParserFactory("postgresql")
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks("oracle")
        with patch.object(quirks, "parser_class", side_effect=Exception("Boom")):
            with pytest.raises(
                ParserNotAvailableError,
                match="No hybrid parser available for dialect oracle",
            ):
                factory.get_parser("oracle")

    def test_get_parser_unknown_dialect_fallback(self):
        """Test get_parser for unknown dialect throws error."""
        factory = SqlParserFactory("postgresql")

        with pytest.raises(UnsupportedDialectError, match="Unsupported dialect: unknown_dialect"):
            factory.get_parser("unknown_dialect")

    def test_get_parser_normalises_dialect_to_lowercase(self):
        """``get_parser("ORACLE")`` resolves the same plugin as
        ``get_parser("oracle")``. Case-insensitive lookup happens
        inside ``ProviderRegistry.get_quirks``."""
        from core.sql_parser.hybrid_parser import HybridParser

        factory = SqlParserFactory("postgresql")
        parser = factory.get_parser("ORACLE")
        assert isinstance(parser, HybridParser)

    def test_parse_sql_error_handling_no_parser_creation(self):
        """Test parse_sql when parser creation returns None."""
        factory = SqlParserFactory("postgresql")

        with patch.object(factory, "_create_parser", return_value=None):
            result = factory.parse_sql("SELECT 1")

            assert result.success is False
            assert "No parser available" in result.errors

    def test_split_statements_error_handling_no_parser_creation(self):
        """Test split_statements when parser creation returns None."""
        factory = SqlParserFactory("postgresql")

        with patch.object(factory, "_create_parser", return_value=None):
            result = factory.split_statements("SELECT 1")

            assert result == []

    def test_validate_sql_error_handling_no_parser_creation(self):
        """Test validate_sql when parser creation returns None."""
        factory = SqlParserFactory("postgresql")

        with patch.object(factory, "_create_parser", return_value=None):
            result = factory.validate_sql("SELECT 1")

            assert result["success"] is False
            assert "No parser available" in result["errors"]

    def test_extract_objects_error_handling_no_parser_creation(self):
        """Test extract_objects when parser creation returns None."""
        factory = SqlParserFactory("postgresql")

        with patch.object(factory, "_create_parser", return_value=None):
            result = factory.extract_objects("CREATE TABLE test")

            assert result == []

    def test_parse_error_handling_no_parser_creation(self):
        """Test parse when parser creation returns None."""
        factory = SqlParserFactory("postgresql")

        with patch.object(factory, "_create_parser", return_value=None):
            result = factory.parse("SELECT 1")

            assert result.sql_text == "SELECT 1"
            assert result.statement_type == SqlStatementType.UNKNOWN
            assert result.objects == []
            assert result.affected_objects == []
            assert result.dialect is None
            assert result.schema is None

    def test_get_affected_objects_error_handling_no_parser_creation(self):
        """Test get_affected_objects when parser creation returns None."""
        factory = SqlParserFactory("postgresql")

        with patch.object(factory, "_create_parser", return_value=None):
            result = factory.get_affected_objects("UPDATE test SET value = 1")

            assert result == []

    def test_get_parser_with_none_dialect_uses_factory_dialect(self):
        """Test get_parser with None dialect uses factory's dialect."""
        factory = SqlParserFactory("unknown_dialect")

        with pytest.raises(UnsupportedDialectError, match="Unsupported dialect: unknown_dialect"):
            factory.get_parser(None)

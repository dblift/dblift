"""Comprehensive tests for db.plugins.base_query_executor.BaseQueryExecutor."""

from unittest.mock import MagicMock

import pytest

from dblift.core.logger import NullLog
from dblift.db.plugins.base_query_executor import BaseQueryExecutor


class ConcreteQueryExecutor(BaseQueryExecutor):
    """Concrete implementation of BaseQueryExecutor for testing."""

    def execute_statement(self, connection, sql: str, params=None, return_generated_keys=False):
        return 1

    def execute_query(self, connection, sql: str, params=None):
        return []

    def table_exists(self, connection, schema: str, table_name: str):
        return False

    def get_schema_qualified_name(self, schema: str, object_name: str):
        return f"{schema}.{object_name}"


@pytest.mark.unit
class TestBaseQueryExecutor:
    """Test suite for BaseQueryExecutor base class."""

    @pytest.fixture
    def mock_connection_manager(self):
        """Create a mock connection manager."""
        return MagicMock()

    @pytest.fixture
    def mock_logger(self):
        """Create a mock logger."""
        return MagicMock()

    @pytest.fixture
    def query_executor(self, mock_connection_manager, mock_logger):
        """Create a concrete query executor instance."""
        return ConcreteQueryExecutor(mock_connection_manager, mock_logger)

    @pytest.fixture
    def mock_connection(self):
        """Create a mock native connection."""
        connection = MagicMock()
        connection.isClosed.return_value = False
        return connection

    def test_init_stores_dependencies(self, mock_connection_manager, mock_logger):
        """Test __init__ stores dependencies."""
        executor = ConcreteQueryExecutor(mock_connection_manager, mock_logger)

        assert executor.connection_manager == mock_connection_manager
        assert executor.log == mock_logger

    def test_init_without_logger(self, mock_connection_manager):
        """Test __init__ works without logger."""
        executor = ConcreteQueryExecutor(mock_connection_manager, None)

        assert isinstance(executor.log, NullLog)

    def test_no_log_wrapper_methods(self):
        """Verify log wrappers have been removed (story 18-4)."""
        wrappers = ["_log_debug", "_log_info", "_log_error", "_log_warning"]
        for name in wrappers:
            assert (
                name not in BaseQueryExecutor.__dict__
            ), f"Log wrapper {name!r} must be removed from BaseQueryExecutor (story 18-4)"

    def test_validate_connection_raises_on_none(self, query_executor):
        """Test _validate_connection() raises on None."""
        with pytest.raises(RuntimeError, match="No database connection provided"):
            query_executor._validate_connection(None)

    def test_validate_connection_raises_on_closed(self, query_executor):
        """Test _validate_connection() raises on closed connection."""
        connection = MagicMock()
        connection.isClosed.return_value = True

        with pytest.raises(RuntimeError, match="Database connection is closed"):
            query_executor._validate_connection(connection)

    def test_validate_connection_passes_on_open_connection(self, query_executor, mock_connection):
        """Test _validate_connection() passes on open connection."""
        # Should not raise exception
        query_executor._validate_connection(mock_connection)

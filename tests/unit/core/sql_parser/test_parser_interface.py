"""Unit tests for core.sql_parser.parser_interface module."""

from unittest.mock import patch

import pytest

from dblift.core.sql_model.base import ParseResult, SqlStatement, SqlStatementType
from dblift.core.sql_parser.parser_interface import SqlParserInterface


@pytest.mark.unit
class TestSqlParserInterface:
    """Test SqlParserInterface abstract class."""

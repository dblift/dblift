"""Unit tests for core.sql_parser.common.base_parser module."""

from unittest.mock import patch

import pytest

from dblift.core.sql_model.base import ParseResult, SqlObject, SqlObjectType, SqlStatementType


@pytest.mark.unit
class TestRegexBasedParser:
    """Test RegexBasedParser class."""

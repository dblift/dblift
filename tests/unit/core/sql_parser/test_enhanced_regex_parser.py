"""Tests for enhanced regex parser."""

from unittest.mock import MagicMock, patch

import pytest

from dblift.core.sql_model.base import ParseResult, SqlObject, SqlObjectType, SqlStatementType


@pytest.mark.unit
class TestEnhancedRegexParser:
    """Test suite for enhanced regex parser."""

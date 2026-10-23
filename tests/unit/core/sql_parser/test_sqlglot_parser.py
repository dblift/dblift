"""Tests for SqlGlot-based SQL parser."""

import pytest

from dblift.core.sql_model.base import (
    ParseResult,
    SqlObject,
    SqlObjectType,
    SqlStatementType,
)
from dblift.core.sql_parser.parser_factory import SqlParserFactory

pytestmark = pytest.mark.usefixtures("legacy_oracle")


@pytest.mark.unit
class TestSqlGlotParser:
    """Test SqlGlotParser functionality across all supported dialects."""

    # ==================== Parser Creation Tests ====================

    # ==================== Oracle Tests ====================

    # ==================== SQL Server Tests ====================

    # ==================== Oracle Tests ====================

    # ==================== SQL Server Tests ====================

    # ==================== Common DDL Tests ====================

    # ==================== Complex SQL Tests ====================

    # ==================== Error Handling Tests ====================

    # ==================== Affected Objects Tests ====================

    # ==================== Quoted Identifiers Tests ====================

    # ==================== Dialect-Specific Features ====================

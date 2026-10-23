"""Client commands and backslash sequences (docs/sql-parsing/mysql.md section 6)."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from tests.support.facts_parser import facts_parser

SCRIPT = "source other.sql;\nCREATE TABLE a (id INT);\nSELECT 1\\G\nCREATE TABLE b (id INT);\n"


def test_execution_and_extraction_refuse_the_same_client_command() -> None:
    parser = facts_parser("mysql")
    with pytest.raises(UnsupportedMetaCommandError, match="source"):
        parser.split_statements(SCRIPT)
    with pytest.raises(UnsupportedMetaCommandError, match="source"):
        parser.split_for_extraction(SCRIPT)

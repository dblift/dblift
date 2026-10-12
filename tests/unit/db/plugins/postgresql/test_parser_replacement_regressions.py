"""Execution units retain COPY bytes while analysis can inspect their SQL parts."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import PostgreSqlRegexParser
from dblift.db.plugins.postgresql.provider import _split_copy_from_stdin


@pytest.mark.parametrize(
    "rows",
    ["", "\n", "1\n\n", "\n\n", " \n"],
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_copy_payload_reaches_provider_byte_for_byte(rows: str, newline: str) -> None:
    payload = rows.replace("\n", newline)
    script = f"COPY t(a) FROM STDIN;{newline}{payload}\\.{newline}"

    units = StatementSplitter("postgresql").split_statements(script)

    assert len(units) == 1
    assert _split_copy_from_stdin(units[0]) == ("COPY t(a) FROM STDIN", payload)


def test_psql_combined_unit_has_each_constituent_in_analysis() -> None:
    script = r"SELECT 1 \; DROP TABLE users \; SELECT 2;"
    parser = PostgreSqlRegexParser()

    assert parser.split_statements(script) == ["SELECT 1 ; DROP TABLE users ; SELECT 2;"]
    assert [statement.sql_text for statement in parser.parse_sql(script).statements] == [
        "SELECT 1",
        "DROP TABLE users",
        "SELECT 2",
    ]


def test_combined_unit_preserves_quoted_semicolons_in_execution_and_analysis() -> None:
    script = r"SELECT ';' \; SELECT $$;$$ \; DROP TABLE users;"
    parser = PostgreSqlRegexParser()

    assert parser.split_statements(script) == ["SELECT ';' ; SELECT $$;$$ ; DROP TABLE users;"]
    assert parser.split_for_analysis(script) == [
        "SELECT ';'",
        "SELECT $$;$$",
        "DROP TABLE users",
    ]


def test_copy_data_is_opaque_to_analysis() -> None:
    script = "COPY t(a) FROM STDIN;\nDROP TABLE users;\n\\.\n"

    assert PostgreSqlRegexParser().split_for_analysis(script) == ["COPY t(a) FROM STDIN"]


def test_copy_cannot_hide_an_executed_combined_constituent() -> None:
    script = "SELECT 1 \\; COPY t(a) FROM STDIN;\n1\n\\.\n"

    with pytest.raises(UnsafeStatementSplitError):
        PostgreSqlRegexParser().split_statements(script)

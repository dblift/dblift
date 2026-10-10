"""psql meta-commands are recognised wherever an unquoted backslash appears (spec §6)."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsupportedMetaCommandError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer


@pytest.fixture(scope="module")
def split():
    analyzer = SqlAnalyzer("postgresql")
    return analyzer.split_statements


@pytest.mark.parametrize(
    "script, command",
    [
        ("SELECT 1; \\set x 1", "\\set"),
        ("SELECT count(*) FROM t \\gset n", "\\gset"),
        ("SELECT 1 \\gx", "\\gx"),
    ],
)
def test_mid_line_meta_command_is_rejected_by_name(split, script: str, command: str) -> None:
    with pytest.raises(UnsupportedMetaCommandError) as info:
        split(script)
    assert command in str(info.value) and "line 1" in str(info.value)


@pytest.mark.parametrize(
    "script",
    [
        "SELECT $$\\connect x$$;",
        "SELECT '\\set';",
        "SELECT E'\\\\set';",
        'SELECT "\\i" FROM t;',
        "-- \\connect\nSELECT 1;",
    ],
)
def test_backslash_inside_literals_identifiers_and_comments_is_not_a_command(
    split, script: str
) -> None:
    assert len(split(script)) == 1


def test_restrict_lines_are_dropped_and_the_sql_runs(split) -> None:
    assert split("\\restrict abc\nSELECT 1;\n\\unrestrict abc\n") == ["SELECT 1;"]

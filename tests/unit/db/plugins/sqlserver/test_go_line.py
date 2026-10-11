"""The shape of a GO line, and what follows it (docs/sql-parsing/sqlserver.md section 4)."""

import logging

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.sqlserver.parser import _batches
from dblift.db.plugins.sqlserver.parser._batches import Batch, scan_batches
from dblift.db.plugins.sqlserver.parser.sqlserver_regex_parser import SqlServerRegexParser


def _strings(script):
    return SqlAnalyzer("sqlserver").split_statements(script)


@pytest.mark.parametrize(
    "line, count",
    [
        ("GO", 1),
        ("go", 1),
        ("Go", 1),
        ("   GO", 1),
        ("\tGO   ", 1),
        ("GO -- trailing", 1),
        ("GO 2", 2),
        ("GO\t2  ", 2),
        ("GO 002", 2),
        ("GO 2 -- c", 2),
        ("GO 0", 0),
    ],
)
def test_a_clean_go_line_separates_with_its_count(line, count):
    batches = scan_batches(f"SELECT 1\n{line}\nSELECT 2")
    assert [(b.text, b.repeat) for b in batches] == [("SELECT 1", count), ("SELECT 2", 1)]


@pytest.mark.parametrize(
    "line",
    [
        "GO foo",
        "GO 5x",
        "GO -1",
        "GO +2",
        "GO 2 3",
        "GO ;",
        "GO;",
        "GO /* c */",
        "GO /* c",
        "GO // c",
        "go(1)",
        "go = 1",
        "GO[1]",
        "GO'x'",
        "go/*c*/",
    ],
)
def test_anything_but_a_count_and_a_dash_comment_after_go_is_refused(line):
    with pytest.raises(UnsafeStatementSplitError, match="text after GO on line 2"):
        scan_batches(f"SELECT 1\n{line}\nSELECT 2")


@pytest.mark.parametrize(
    "line", ["GO--c", "GO--", "go--end", "  GO--c", "GO--c --d", "GO 2--c", "GO 0--"]
)
def test_a_comment_glued_to_go_is_refused(line):
    # The ODBC sqlcmd takes GO--c as a separator; go-sqlcmd sends GO to the server as text, which a
    # batch ending in an expression turns into an alias. Refuse what the two clients read differently.
    with pytest.raises(UnsafeStatementSplitError, match="directly after GO") as error:
        scan_batches(f"SELECT 1\n{line}\nSELECT 2")
    assert "line 2" in str(error.value)


def test_a_blank_before_the_comment_is_still_a_separator():
    batches = scan_batches("SELECT 1\nGO --c\nSELECT 2")
    assert [(b.text, b.repeat) for b in batches] == [("SELECT 1", 1), ("SELECT 2", 1)]


@pytest.mark.parametrize(
    "word",
    [
        "GOTO label",
        "GOO",
        "GO_ON",
        "GO$x",
        "GOLD INT",
        "[go]",
        "dbo.go",
        "go.id",
        "go,",
        "go@x",
        "go+1",
        "go)",
        "go*2",
        "go:x",
        "go|1",
        "go<1",
    ],
)
def test_a_longer_word_or_a_quoted_name_is_text_not_a_command(word):
    assert scan_batches(f"SELECT 1\n{word}\nGO") == [Batch(f"SELECT 1\n{word}", 1, 1, True)]


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1\n/* c */ GO\nSELECT 2",
        "SELECT 1\n/* a */ /* b */ GO\nSELECT 2",
        "/* a\nb */ GO\nSELECT 2",
    ],
)
def test_a_go_that_follows_a_comment_on_its_line_is_refused(script):
    with pytest.raises(UnsafeStatementSplitError, match="GO after a comment"):
        scan_batches(script)


def test_go_n_is_one_record_with_repeat_and_n_strings():
    script = "INSERT INTO t VALUES (1)\nGO 3\n"
    assert SqlServerRegexParser().split(script) == [
        Statement(text="INSERT INTO t VALUES (1)", line=1, terminator="GO", repeat=3)
    ]
    assert _strings(script) == ["INSERT INTO t VALUES (1)"] * 3


def test_go_zero_runs_the_batch_never():
    script = "INSERT INTO t VALUES (1)\nGO 0\nSELECT 2"
    assert SqlServerRegexParser().split(script)[0].repeat == 0
    assert _strings(script) == ["SELECT 2"]


def test_a_count_above_the_limit_is_refused(monkeypatch):
    monkeypatch.setattr(_batches, "MAX_GO_COUNT", 5)
    assert len(_strings("SELECT 1\nGO 5\n")) == 5
    with pytest.raises(UnsafeStatementSplitError, match="GO 6 on line 2 exceeds the limit of 5"):
        scan_batches("SELECT 1\nGO 6\n")


def test_the_default_limit_is_one_million():
    assert _batches.MAX_GO_COUNT == 1_000_000


def test_the_default_limit_is_pinned_by_a_count_one_above_it():
    assert scan_batches("SELECT 1\nGO 1000000\n")[0].repeat == 1_000_000
    with pytest.raises(UnsafeStatementSplitError, match="GO 1000001 on line 2 exceeds the limit"):
        scan_batches("SELECT 1\nGO 1000001\n")


def test_go_zero_is_logged_not_dropped_silently(caplog):
    logger = "dblift.db.plugins.sqlserver.parser.sqlserver_regex_parser"
    with caplog.at_level(logging.INFO, logger=logger):
        assert _strings("INSERT INTO t VALUES (1)\nGO 0\nSELECT 2") == ["SELECT 2"]
    assert "GO 0 follows the batch starting on line 1" in caplog.text


def test_a_go_line_inside_an_open_block_comment_is_not_cut():
    with pytest.raises(UnsafeStatementSplitError, match="GO after a comment"):
        scan_batches("SELECT /* a\n b */ GO\nSELECT 2")


def test_text_after_go_on_a_line_that_a_comment_closed_names_the_text_row_6():
    with pytest.raises(UnsafeStatementSplitError, match="text after GO on line 1"):
        scan_batches("/* a /* b */ GO */\nSELECT 1\nGO")


@pytest.mark.parametrize("digits", ["9" * 5000, "0" * 5000 + "9" * 7, "1" + "0" * 7])
def test_a_count_with_more_digits_than_the_limit_allows_is_refused_not_a_crash(digits):
    with pytest.raises(UnsafeStatementSplitError, match="exceeds the limit"):
        scan_batches(f"SELECT 1\nGO {digits}\n")


def test_a_count_of_only_zeros_is_go_zero_however_long():
    assert scan_batches("SELECT 1\nGO " + "0" * 5000 + "\n")[0].repeat == 0


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1\nGO\x0b\nSELECT 2",
        "SELECT 1\nGO\x0c\nSELECT 2",
        "SELECT 1\rGO\rSELECT 2",
    ],
)
def test_go_followed_by_an_unmeasured_blank_or_a_lone_cr_is_refused(script):
    with pytest.raises(UnsafeStatementSplitError, match="text after GO"):
        scan_batches(script)

"""sqlcmd commands and scripting variables are refused, never sent to the server (docs/sql-parsing/sqlserver.md section 6)."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.db.plugins.sqlserver.parser._batches import Batch, scan_batches


def _split(script):
    return SqlAnalyzer("sqlserver").split_statements(script)


@pytest.mark.parametrize(
    "line",
    [
        ":setvar schema dbo",
        ":SETVAR schema dbo",
        "  :setvar schema dbo",
        ":r include.sql",
        ":connect server -U sa",
        ":on error exit",
        ":exit",
        ":quit",
        ":list",
        ":listvar",
        ":error STDERR",
        ":out file.txt",
        ":perftrace STDOUT",
        ":help",
        ":serverlist",
        ":xml on",
        ":reset",
        ":ed",
        ":!!dir",
        "!!dir",
        "  !!echo hi",
        "RESET",
        "reset",
        "ED",
        "QUIT",
        "EXIT",
        "exit",
        "   EXIT",
        "EXIT(SELECT 42)",
        "EXIT -- done",
        "EXIT foo",
        "QUIT now",
        "RESET now",
        "exit = 1",
        "quit(1)",
        "reset = 1",
        "reset(1)",
        "ed = 1",
        "ed(1)",
    ],
)
def test_a_command_at_the_first_token_of_a_line_is_refused_naming_the_line(line):
    with pytest.raises(UnsupportedMetaCommandError, match="on line 2"):
        scan_batches(f"SELECT 1\n{line}\nSELECT 2")


def test_a_command_in_the_middle_of_a_statement_is_refused_too():
    with pytest.raises(UnsupportedMetaCommandError, match=":setvar' on line 2"):
        _split("CREATE TABLE t (id INT,\n:setvar a b\n x INT)\nGO")


def test_a_column_named_like_a_command_at_a_line_start_is_refused_as_sqlcmd_errors():
    with pytest.raises(UnsupportedMetaCommandError, match="'EXIT' on line 2"):
        _split("CREATE TABLE t (\n  exit INT\n)\nGO")


@pytest.mark.parametrize(
    "script",
    [
        ":foo\nGO",
        ":random\nGO",
        "exit;\nGO",
        "quit;\nGO",
        "reset;\nGO",
        "ed;\nGO",
        "quit.id\nGO",
        "ed.id\nGO",
        "exit.id\nGO",
        "reset.x\nGO",
        "quit,\nGO",
        "ed,\nGO",
        "EXITED INT\nGO",
        "QUITE INT\nGO",
        "EDITOR INT\nGO",
        "RESETS INT\nGO",
        "SELECT 1 :setvar x y\nGO",
        "SELECT 1 EXIT\nGO",
        "SELECT 1 AS reset\nGO",
        "SELECT !!x\nGO",
        "SELECT 1 -- :setvar x y\nGO",
    ],
)
def test_an_unknown_colon_word_a_longer_word_or_a_mid_line_command_is_sql_text(script):
    assert len(scan_batches(script)) == 1


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 'x\n:setvar a b\ny' AS s\nGO",
        "SELECT 'x\nEXIT\ny' AS s\nGO",
        "SELECT 'x\n:r file.sql\ny' AS s\nGO",
        "SELECT 1 /*\n:setvar a b\n*/\nGO",
        "SELECT 1 /*\nEXIT\n*/\nGO",
        "SELECT 1 AS [a\n:setvar b\nc]\nGO",
    ],
)
def test_a_command_line_inside_a_string_an_identifier_or_a_comment_is_text(script):
    assert len(scan_batches(script)) == 1


@pytest.mark.parametrize(
    "script",
    [
        "SELECT * FROM $(table)",
        "CREATE TABLE [$(name)] (id INT)",
        "SELECT '$(x)' AS s",
        'SELECT "$(x)" FROM t',
        "SELECT 'a\n$(x)\nb'",
        "USE [$(db)]",
        "SELECT $(x-y)",
        "SELECT '$()' AS s",
        "SELECT '$(1x)' AS s",
        "SELECT $(a.b)",
        "SELECT $(x y)",
    ],
)
def test_a_scripting_variable_reference_is_refused_outside_comments(script):
    with pytest.raises(UnsupportedMetaCommandError, match=r"scripting variable \$\(.* on line \d"):
        scan_batches(script + "\nGO")


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1 -- $(x)",
        "-- $(x)\nSELECT 1",
        "/* $(x) */ SELECT 1",
        "SELECT 1 /*\n$(x)\n*/",
        "SELECT '$ (x)' AS s",
        "SELECT $action FROM t",
        "SELECT $IDENTITY FROM t",
    ],
)
def test_a_comment_and_text_that_is_not_a_reference_are_left_alone(script):
    assert [b.text for b in scan_batches(script + "\nGO")] == [script]


def test_the_refusal_names_the_line_of_a_reference_inside_a_multi_line_string():
    with pytest.raises(UnsupportedMetaCommandError, match=r"\$\(x\) on line 4"):
        scan_batches("SELECT 1\nGO\nSELECT 'a\n$(x)\nb'")


def test_go_n_with_a_variable_is_refused_as_text_after_go_not_substituted():
    with pytest.raises(
        UnsafeStatementSplitError, match=r"text after GO.*\$\(n\) is not substituted"
    ):
        scan_batches("SELECT 1\nGO $(n)\n")


def test_the_batch_of_a_refused_script_is_not_partially_returned():
    with pytest.raises(UnsupportedMetaCommandError):
        scan_batches("SELECT 1\nGO\n:setvar a b\nSELECT 2\nGO\n")
    assert scan_batches("SELECT 1\nGO\n") == [Batch("SELECT 1", 1, 1, True)]


@pytest.mark.parametrize("script", ["SELECT $(", "SELECT $(x", "SELECT '$(' AS s"])
def test_an_unfinished_dollar_paren_is_refused_like_a_reference(script):
    with pytest.raises(UnsupportedMetaCommandError, match=r"scripting variable \$\(.* on line 1"):
        scan_batches(script + "\nGO")

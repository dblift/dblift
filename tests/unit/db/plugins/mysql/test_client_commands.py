"""Client commands and backslash sequences (docs/sql-parsing/mysql.md section 6)."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.db.plugins.mariadb.regex_parser import MariaDbRegexParser
from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser


def _split(script: str, *, mariadb: bool = False):  # type: ignore[no-untyped-def]
    return (MariaDbRegexParser if mariadb else MySqlRegexParser)().split(script)


def sql(script: str, *, mariadb: bool = False) -> list[str]:
    return [s.text for s in _split(script, mariadb=mariadb) if s.kind == "sql"]


@pytest.mark.parametrize(
    "line",
    [
        "exit", "quit", "EXIT", "Quit", "  exit", "\texit", "exit  ", "exit;", "exit ;", "quit;", "go", "ego",
        "status", "status;", "status ;", "help", "help;", "?", "?;", "rehash", "print", "nopager",
        "notee", "nowarning", "warnings", "clear", "edit", "edit;", "resetconnection",
        "source /tmp/f.sql", "source /tmp/f.sql;", "source", "source;", "connect", "connect db",
        "system echo hi", "system", "tee /tmp/t", "tee", "charset utf8mb4", "prompt p>", "pager cat",
        "query_attributes", "query_attributes n v", "ssl_session_data_print",
    ],
)  # fmt: skip
def test_a_command_word_alone_on_a_line_is_refused(line: str) -> None:
    with pytest.raises(UnsupportedMetaCommandError) as caught:
        _split(f"SELECT 1;\n{line}\nSELECT 2;")
    assert "on line 2" in str(caught.value)


@pytest.mark.parametrize(
    "line",
    [
        "exit now", "quit now", "go;", "ego;", "go now",
        "status x", "status x;", "help 'x';", "help x;", "? x;", "print x", "clear x",
        "exiting", "status_flag INT,", "source_table", "use_x", "gone", "goal", "helper",
        "exit -- c", "exit # c", "exit /* c */", "delimiters //", "delimiter_x",
    ],
)  # fmt: skip
def test_a_command_word_with_more_on_the_line_is_text(line: str) -> None:
    assert sql(f"SELECT 1;\n{line}\nSELECT 2;")[1].startswith(line.split()[0].rstrip(";"))


def test_a_command_word_is_text_while_a_statement_is_pending_or_after_a_terminator() -> None:
    assert sql("SELECT 1\nexit\n;") == ["SELECT 1\nexit"]
    assert sql("SELECT 1; exit\nSELECT 2;") == ["SELECT 1", "exit\nSELECT 2"]
    assert sql("CREATE TABLE t (\nstatus INT,\nsource INT,\nuse_x INT\n);") == [
        "CREATE TABLE t (\nstatus INT,\nsource INT,\nuse_x INT\n)"
    ]


def test_a_command_word_after_a_comment_line_is_a_command() -> None:
    with pytest.raises(UnsupportedMetaCommandError):
        _split("-- c\nexit\nSELECT 1;")


def test_use_needs_its_terminator() -> None:
    assert sql("USE db;\nSELECT 1;") == ["USE db", "SELECT 1"]
    assert sql("use db; SELECT 1;") == ["use db", "SELECT 1"]
    assert sql("DELIMITER //\nuse db//\nDELIMITER ;") == ["use db"]
    for script in ("use db\nSELECT 1;", "use\nSELECT 1;", "USE db -- c\nSELECT 1;"):
        with pytest.raises(UnsupportedMetaCommandError, match="'(use|USE)'"):
            _split(script)


@pytest.mark.parametrize(
    "text,name",
    [
        ("SELECT 1\\G", "\\G"),
        ("SELECT 1\\g", "\\g"),
        ("SELECT 1 \\c", "\\c"),
        ("\\d //", "\\d"),
        ("\\. file", "\\."),
        ("\\! echo", "\\!"),
        ("\\q", "\\q"),
        ("SELECT 1 \\z", "\\z"),
        ("SELECT 1\\;", "\\;"),
        ("SELECT 1 AS a \\ ", "\\ "),
        ("SELECT 1 /*! \\G */", "\\G"),
        ("SELECT 1 -- c\n\\G", "\\G"),
    ],
)
def test_a_backslash_outside_a_string_is_a_client_command_and_refused(text: str, name: str) -> None:
    with pytest.raises(UnsupportedMetaCommandError) as caught:
        _split(f"{text}\nSELECT 2;")
    assert name in str(caught.value)


def test_a_backslash_at_the_end_of_a_line_is_refused() -> None:
    with pytest.raises(UnsupportedMetaCommandError, match="end of a line"):
        _split("SELECT 1 \\\nUNION SELECT 2;")


def test_a_backslash_inside_a_hint_is_refused_and_inside_comments_is_text() -> None:
    with pytest.raises(UnsupportedMetaCommandError, match="optimizer hint"):
        _split("SELECT /*+ \\G */ 1;")
    assert sql("SELECT 1 -- \\G\n;\nSELECT 2 /* \\G */; SELECT 3 # \\c\n;") == [
        "SELECT 1 -- \\G",
        "SELECT 2 /* \\G */",
        "SELECT 3 # \\c",
    ]


def test_backslash_n_outside_a_string_is_text() -> None:
    assert sql("SELECT \\N AS n; SELECT 2;") == ["SELECT \\N AS n", "SELECT 2"]


@pytest.mark.parametrize(
    "setting",
    [
        "SET sql_mode = 'NO_BACKSLASH_ESCAPES'",
        "set SESSION sql_mode='ANSI,no_backslash_escapes'",
        "SET @@sql_mode = CONCAT(@@sql_mode, ',NO_BACKSLASH_ESCAPES')",
        "/*!40101 SET SQL_MODE='NO_BACKSLASH_ESCAPES' */",
    ],
)
def test_a_script_that_sets_no_backslash_escapes_is_refused(setting: str) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="NO_BACKSLASH_ESCAPES"):
        _split(f"{setting};\nSELECT 1;")


def test_other_statements_that_mention_the_mode_are_not_refused() -> None:
    assert sql("SELECT 'NO_BACKSLASH_ESCAPES';") == ["SELECT 'NO_BACKSLASH_ESCAPES'"]


SCRIPT = "source other.sql;\nCREATE TABLE a (id INT);\nSELECT 1\\G\nCREATE TABLE b (id INT);\n"


def test_execution_and_extraction_refuse_the_same_client_command() -> None:
    parser = MySqlRegexParser()
    with pytest.raises(UnsupportedMetaCommandError, match="source"):
        parser.split_statements(SCRIPT)
    with pytest.raises(UnsupportedMetaCommandError, match="source"):
        parser.split_for_extraction(SCRIPT)


@pytest.mark.parametrize("line", ["exit", "exit;", "status", "source f", "use db"])
def test_a_command_word_after_a_comment_on_its_line_is_refused(line: str) -> None:
    """mysql 8.4 runs it and mysql 8.0 sends it to the server as text: neither is safe to guess."""
    for comment in ("/* c */", "/* a */ /* b */"):
        with pytest.raises(UnsupportedMetaCommandError, match="after a comment on line 2"):
            _split(f"SELECT 1;\n{comment} {line}\nSELECT 2;")


def test_a_terminated_use_or_a_word_with_arguments_after_a_comment_is_sql() -> None:
    assert sql("/* c */ use db;\nSELECT 1;") == ["use db", "SELECT 1"]
    assert sql("/* c */ exit now\nSELECT 1;") == ["exit now\nSELECT 1"]
    assert sql("SELECT 1; exit\nSELECT 2;") == ["SELECT 1", "exit\nSELECT 2"]


@pytest.mark.parametrize("comment", ["/*!50000 */", "/*+ x */", "/* c */"])
@pytest.mark.parametrize("line", ["exit", "status;", "use db", "source f"])
def test_a_command_word_after_any_comment_that_starts_the_line_is_refused(
    comment: str, line: str
) -> None:
    with pytest.raises(UnsupportedMetaCommandError, match="after a comment on line 2"):
        _split(f"SELECT 1;\n{comment} {line}\nSELECT 2;")


def test_the_no_backslash_escapes_check_ignores_comments() -> None:
    assert sql("SELECT 1 /* never SET NO_BACKSLASH_ESCAPES */; SELECT 2;") == [
        "SELECT 1 /* never SET NO_BACKSLASH_ESCAPES */",
        "SELECT 2",
    ]
    assert sql("-- SET NO_BACKSLASH_ESCAPES\nSELECT 1;\n# SET NO_BACKSLASH_ESCAPES\nSELECT 2;") == [
        "SELECT 1",
        "SELECT 2",
    ]
    assert sql(
        "SELECT 1 -- SET NO_BACKSLASH_ESCAPES\n;\nSELECT 2 # SET NO_BACKSLASH_ESCAPES\n;"
    ) == [
        "SELECT 1 -- SET NO_BACKSLASH_ESCAPES",
        "SELECT 2 # SET NO_BACKSLASH_ESCAPES",
    ]


def test_a_refusal_names_the_client_of_the_dialect() -> None:
    with pytest.raises(UnsupportedMetaCommandError, match="mariadb client command 'exit'"):
        _split("SELECT 1;\nexit\n", mariadb=True)
    with pytest.raises(UnsupportedMetaCommandError, match="mysql client command 'exit'"):
        _split("SELECT 1;\nexit\n")


@pytest.mark.parametrize(
    "line",
    [
        "USE db; -- c", "USE db; # c", "USE db; /* c */", "USE `db`; -- x", "use db ; -- x",
        "use testdb; xyz", "use db;;",
    ],
)  # fmt: skip
def test_a_terminated_use_is_sql_whatever_follows_its_terminator(line: str) -> None:
    """All three clients send it to the server (`use testdb; xyz` is error 1064 near `xyz`)."""
    assert sql(f"SELECT 1;\n{line}\nSELECT 2;")[1].lower().startswith("use")


@pytest.mark.parametrize(
    "line",
    [
        "status;;", "status ; ;", "help;;", "?;;", "warnings;;", "print;;", "nopager;;",
        "notee;;", "clear;;", "rehash;;", "nowarning;;", "tee;;", "prompt;;", "pager;;",
        "connect;;", "resetconnection;;", "query_attributes;;", "exit;;", "exit ; ;", "exit;x",
        "quit;;", "source;;",
    ],
)  # fmt: skip
def test_a_command_word_followed_by_any_run_of_terminators_is_a_command(line: str) -> None:
    with pytest.raises(UnsupportedMetaCommandError, match="on line 2"):
        _split(f"SELECT 1;\n{line}\nSELECT 2;")


@pytest.mark.parametrize("line", ["status //", "exit //", "help //", "tee //", "exit ; //"])
def test_a_command_word_followed_by_the_active_delimiter_is_a_command(line: str) -> None:
    with pytest.raises(UnsupportedMetaCommandError, match="on line 3"):
        _split(f"DELIMITER //\nSELECT 1//\n{line}\nSELECT 2//")


def test_exit_after_an_executable_comment_that_is_the_whole_pending_text_is_a_command() -> None:
    """mysql 8.4 ends the script there; a statement text before it keeps it text."""
    with pytest.raises(UnsupportedMetaCommandError, match="'exit'"):
        _split("/*!50000 SET @a=1 */\nexit\n;")
    with pytest.raises(UnsupportedMetaCommandError, match="'quit'"):
        _split("/*!50000 SET @a=1 */\nquit\n;")
    assert sql("SELECT 1 /*!50000 + 1 */\nexit\n;") == ["SELECT 1 /*!50000 + 1 */\nexit"]


@pytest.mark.parametrize("line", ["help x", "help 'x'", "? x", "? 'x'", "HELP contents"])
def test_help_with_an_argument_and_no_terminator_is_a_command(line: str) -> None:
    with pytest.raises(UnsupportedMetaCommandError, match="on line 2"):
        _split(f"SELECT 1;\n{line}\nSELECT 2;")


@pytest.mark.parametrize(
    "script",
    [
        "UPDATE cfg SET mode = 'NO_BACKSLASH_ESCAPES' WHERE id = 1;",
        "INSERT INTO t VALUES ('SET x NO_BACKSLASH_ESCAPES');",
        "CREATE TABLE t (m SET('NO_BACKSLASH_ESCAPES', 'x'));",
        "SELECT `NO_BACKSLASH_ESCAPES` FROM t WHERE a = 'SET';",
    ],
)
def test_the_mode_name_in_a_literal_of_another_statement_is_not_a_setting(script: str) -> None:
    assert len(sql(script)) == 1


def test_the_mode_set_by_a_stored_program_body_is_still_refused() -> None:
    with pytest.raises(UnsafeStatementSplitError, match="NO_BACKSLASH_ESCAPES"):
        _split("CREATE PROCEDURE p() BEGIN SET sql_mode = 'NO_BACKSLASH_ESCAPES'; END;")


def test_a_backslash_in_a_hint_is_text_on_mariadb_only() -> None:
    assert sql("SELECT /*+ \\G */ 1;", mariadb=True) == ["SELECT /*+ \\G */ 1"]
    assert sql("SELECT /*+\n \\G\n*/ 1 AS x;", mariadb=True) == ["SELECT /*+\n \\G\n*/ 1 AS x"]
    with pytest.raises(UnsupportedMetaCommandError):
        _split("SELECT /*+\n \\G\n*/ 1 AS x;")


def test_a_mode_setting_behind_a_maria_comment_is_refused_on_mariadb_only() -> None:
    script = "/*M!100500 SET sql_mode = 'NO_BACKSLASH_ESCAPES' */;\nSELECT 1;"
    with pytest.raises(UnsafeStatementSplitError, match="NO_BACKSLASH_ESCAPES"):
        _split(script, mariadb=True)
    assert sql(script) == ["SELECT 1"]


@pytest.mark.parametrize("mariadb", [False, True])
def test_a_prepared_statement_that_sets_the_mode_is_refused(mariadb: bool) -> None:
    script = "PREPARE s FROM 'SET sql_mode=''NO_BACKSLASH_ESCAPES''';\nEXECUTE s;"
    with pytest.raises(UnsafeStatementSplitError, match="NO_BACKSLASH_ESCAPES"):
        _split(script, mariadb=mariadb)


@pytest.mark.parametrize("mariadb", [False, True])
def test_a_prepared_statement_that_does_not_set_the_mode_passes(mariadb: bool) -> None:
    script = "PREPARE s FROM 'SELECT 1 FROM t WHERE m = ''NO_BACKSLASH_ESCAPES''';"
    assert len(sql(script, mariadb=mariadb)) == 1

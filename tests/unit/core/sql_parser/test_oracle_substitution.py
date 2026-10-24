"""Substitution variables and EXECUTE (docs/sql-parsing/oracle.md section 6), read through the engine."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.oracle.parser._sqlplus import parse_whenever_sqlerror
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC


def records(script):
    return LexicalEngine(ORACLE_SPEC).split(script)


def strings(script):
    return LexicalEngine(ORACLE_SPEC).split_statements(script)


def sql(script):
    return [r.text for r in records(script) if r.kind == "sql"]


def test_row_15_define_off_leaves_the_ampersand_alone():
    assert strings("SET DEFINE OFF\nINSERT INTO t VALUES ('a&b');") == [
        "INSERT INTO t VALUES ('a&b');"
    ]


def test_row_15_define_on_substitutes_and_the_dot_ends_the_reference():
    script = "SET DEFINE ON\nDEFINE s = x\nCREATE TABLE &s.1 (id NUMBER);"
    assert strings(script) == ["CREATE TABLE x1 (id NUMBER);"]
    assert sql(script) == ["CREATE TABLE x1 (id NUMBER)"]


def test_define_is_on_by_default():
    assert strings("DEFINE s = x\nSELECT &s FROM dual;") == ["SELECT x FROM dual;"]


def test_substitution_applies_inside_literals_and_inside_a_comment_in_a_statement():
    assert strings("DEFINE v = q\nINSERT INTO t VALUES ('a&v');") == [
        "INSERT INTO t VALUES ('aq');"
    ]
    assert strings("DEFINE v = q\nSELECT 1 /* &v */ FROM dual;") == ["SELECT 1 /* q */ FROM dual;"]


def test_a_comment_only_line_before_a_statement_is_not_substituted():
    assert records("-- &undefined\nSELECT 1 FROM dual;")[0].text == "SELECT 1 FROM dual"


def test_double_dot_keeps_one_dot_and_the_dot_form_ends_a_name():
    assert strings("DEFINE o = APP\nSELECT * FROM &o..t;") == ["SELECT * FROM APP.t;"]
    assert strings("DEFINE v = a\nSELECT &v.x, &v FROM dual;") == ["SELECT ax, a FROM dual;"]


def test_double_ampersand_keeps_the_value():
    script = "DEFINE e = prod\nSELECT &&e FROM dual;\nSELECT &e FROM dual;"
    assert strings(script) == ["SELECT prod FROM dual;", "SELECT prod FROM dual;"]


def test_quoted_value_loses_its_quotes_and_no_space_form_works():
    assert strings("DEFINE a='x y'\nDEFINE b = 'z'\nSELECT '&a', &b FROM dual;") == [
        "SELECT 'x y', z FROM dual;"
    ]


def test_a_define_after_a_statement_does_not_affect_it():
    script = "DEFINE v = 1\nSELECT &v FROM dual;\nDEFINE v = 2\nSELECT &v FROM dual;"
    assert strings(script) == ["SELECT 1 FROM dual;", "SELECT 2 FROM dual;"]


def test_set_define_off_applies_from_its_line_on():
    script = "DEFINE v = 1\nSELECT '&v' FROM dual;\nSET DEFINE OFF\nSELECT '&v' FROM dual;"
    assert strings(script) == ["SELECT '1' FROM dual;", "SELECT '&v' FROM dual;"]


def test_undefine_makes_the_variable_undefined_again():
    with pytest.raises(UnsafeStatementSplitError, match="&x on line 3 is undefined"):
        strings("DEFINE x = 1\nUNDEFINE x\nSELECT &x FROM dual;")


def test_a_changed_substitution_character_changes_the_prefix():
    script = "SET DEFINE ^\nDEFINE x = 1\nSELECT ^x, '&x' FROM dual;"
    assert strings(script) == ["SELECT 1, '&x' FROM dual;"]
    with pytest.raises(UnsafeStatementSplitError, match=r"\^v on line 2 is undefined"):
        strings("SET DEFINE ^\nSELECT ^v FROM dual;")


def test_set_scan_is_set_define():
    assert strings("SET SCAN OFF\nINSERT INTO t VALUES ('a&b');") == [
        "INSERT INTO t VALUES ('a&b');"
    ]
    assert strings("SET SCAN OFF\nSET SCAN ON\nDEFINE b = z\nSELECT '&b' FROM dual;") == [
        "SELECT 'z' FROM dual;"
    ]


def test_set_define_with_a_word_that_is_not_one_character_keeps_the_state():
    assert strings("DEFINE v = 1\nSET DEFINE ab\nSELECT &v FROM dual;") == ["SELECT 1 FROM dual;"]


def test_undefined_variable_is_refused_naming_it_and_its_line():
    with pytest.raises(
        UnsafeStatementSplitError,
        match="&y on line 2 is undefined; SQL\\*Plus would prompt for it",
    ):
        strings("SELECT 1 FROM dual;\nSELECT &y FROM dual;")


def test_a_reference_on_a_later_line_of_a_statement_names_that_line():
    with pytest.raises(UnsafeStatementSplitError, match="&y on line 3 is undefined"):
        strings("SELECT 1 FROM dual;\nSELECT 1,\n  &y FROM dual;")


def test_row_16_exec_becomes_a_unit():
    script = "EXEC dbms_output.put_line('hi');\nSELECT 1 FROM dual;"
    assert strings(script) == ["BEGIN dbms_output.put_line('hi'); END;", "SELECT 1 FROM dual;"]
    assert records(script) == [
        Statement(
            text="BEGIN dbms_output.put_line('hi'); END;", line=1, terminator=None, kind="sql"
        ),
        Statement(text="SELECT 1 FROM dual", line=2, terminator=";"),
    ]


@pytest.mark.parametrize("word", ["EXEC", "EXECUTE", "execute"])
def test_exec_without_a_semicolon(word):
    assert strings(f"{word} p16\nSELECT 1 FROM dual;")[0] == "BEGIN p16; END;"


def test_exec_unit_is_substituted_too():
    assert strings("DEFINE p = proc\nEXEC &p;") == ["BEGIN proc; END;"]
    with pytest.raises(UnsafeStatementSplitError, match="&p on line 1 is undefined"):
        strings("EXEC &p;")


def test_define_value_is_substituted_when_defined():
    assert strings("DEFINE a = q\nDEFINE b = &a\nSELECT '&b' FROM dual;") == [
        "SELECT 'q' FROM dual;"
    ]


def test_define_value_keeps_double_hyphen_inside_quotes():
    assert strings("DEFINE x = 'a--b'\nSELECT '&x' FROM dual;") == ["SELECT 'a--b' FROM dual;"]


def test_two_calls_start_from_fresh_state():
    engine = LexicalEngine(ORACLE_SPEC)
    assert engine.split_statements("DEFINE v = 1\nSET DEFINE OFF\nSELECT &v FROM dual;") == [
        "SELECT &v FROM dual;"
    ]
    with pytest.raises(UnsafeStatementSplitError, match="&v on line 1 is undefined"):
        engine.split_statements("SELECT &v FROM dual;")
    assert engine.split("SELECT 1 FROM dual;") == engine.split("SELECT 1 FROM dual;")


@pytest.mark.parametrize(
    "action",
    [
        "EXIT",
        "CONTINUE",
        "exit",
        "EXIT FAILURE",
        "CONTINUE NONE",
        "EXITS",
        "ROLLBACK",
        "",
        "EXIT-1",
    ],
)
def test_whenever_policy_actions_agree_with_the_policy_reader(action):
    line = f"WHENEVER SQLERROR {action}".rstrip()
    try:
        strings(f"{line}\nSELECT 1 FROM dual;")
        accepted = True
    except UnsupportedMetaCommandError:
        accepted = False
    assert accepted == (parse_whenever_sqlerror(line) is not None)


@pytest.mark.parametrize(
    "script, line",
    [
        ("SELECT 1,\n&v FROM dual;", 2),
        ("-- c\nSELECT &v FROM dual;", 2),
        ("-- a\n-- b\n\nSELECT 1,\n  &v FROM dual;", 5),
        ("SELECT 1 FROM dual;\nSELECT\n&w FROM dual;", 3),
    ],
)
def test_row_37_a_refusal_names_the_line_of_the_reference_in_the_source(script, line):
    with pytest.raises(UnsafeStatementSplitError) as raised:
        strings(script)
    assert f" on line {line} is undefined" in str(raised.value)

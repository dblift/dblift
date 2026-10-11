"""DEFINE substitutes positionally and EXEC becomes a PL/SQL unit (docs/sql-parsing/oracle.md section 6)."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.oracle.parser.oracle_statement_parser import OracleStatementParser
from dblift.db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer


def _records(script):
    tokens = OracleTokenizer(script).tokenize()
    return OracleStatementParser(tokens, ParserContext(), source=script).split()


def _strings(script):
    return SqlAnalyzer("oracle").split_statements(script)


def _sql(records):
    return [r.text for r in records if r.kind == "sql"]


def test_row_15_define_off_leaves_the_ampersand_alone():
    assert _strings("SET DEFINE OFF\nINSERT INTO t VALUES ('a&b');") == [
        "INSERT INTO t VALUES ('a&b');"
    ]


def test_row_15_define_on_substitutes_and_the_dot_ends_the_reference():
    script = "SET DEFINE ON\nDEFINE s = x\nCREATE TABLE &s.1 (id NUMBER);"

    assert _strings(script) == ["CREATE TABLE x1 (id NUMBER);"]
    assert _sql(_records(script)) == ["CREATE TABLE x1 (id NUMBER)"]


def test_define_is_on_by_default():
    assert _strings("DEFINE s = x\nSELECT &s FROM dual;") == ["SELECT x FROM dual;"]


def test_substitution_applies_inside_literals():
    # SQL*Plus substitutes variables before sending the command to the server.
    script = "SET DEFINE ON\nDEFINE v = q\nINSERT INTO t VALUES ('a&v');"

    assert _strings(script) == ["INSERT INTO t VALUES ('aq');"]


def test_double_dot_keeps_one_dot():
    assert _strings("DEFINE o = APP\nSELECT * FROM &o..t;") == ["SELECT * FROM APP.t;"]


def test_double_ampersand_defines_on_first_use_and_keeps_the_value():
    script = "DEFINE e = prod\nSELECT &&e FROM dual;\nSELECT &e FROM dual;"

    assert _strings(script) == ["SELECT prod FROM dual;", "SELECT prod FROM dual;"]


def test_quoted_value_loses_its_quotes_and_no_space_form_works():
    assert _strings("DEFINE a='x y'\nDEFINE b = 'z'\nSELECT '&a', &b FROM dual;") == [
        "SELECT 'x y', z FROM dual;"
    ]


def test_a_define_after_a_statement_does_not_affect_it():
    script = "DEFINE v = 1\nSELECT &v FROM dual;\nDEFINE v = 2\nSELECT &v FROM dual;"

    assert _strings(script) == ["SELECT 1 FROM dual;", "SELECT 2 FROM dual;"]


def test_set_define_off_applies_from_its_line_on():
    script = "DEFINE v = 1\nSELECT '&v' FROM dual;\nSET DEFINE OFF\nSELECT '&v' FROM dual;"

    assert _strings(script) == ["SELECT '1' FROM dual;", "SELECT '&v' FROM dual;"]


def test_undefine_makes_the_variable_undefined_again():
    with pytest.raises(UnsafeStatementSplitError, match="&x on line 3 is undefined"):
        _strings("DEFINE x = 1\nUNDEFINE x\nSELECT &x FROM dual;")


def test_custom_define_character_changes_the_prefix():
    script = "SET DEFINE ^\nDEFINE x = 1\nSELECT ^x, '&x' FROM dual;"

    assert _strings(script) == ["SELECT 1, '&x' FROM dual;"]


def test_undefined_variable_is_refused_naming_it_and_its_line():
    with pytest.raises(
        UnsafeStatementSplitError,
        match="&y on line 2 is undefined; SQL\\*Plus would prompt for it",
    ):
        _strings("SELECT 1 FROM dual;\nSELECT &y FROM dual;")


def test_row_16_exec_becomes_a_plsql_unit():
    script = "EXEC dbms_output.put_line('hi');\nSELECT 1 FROM dual;"

    assert _strings(script) == ["BEGIN dbms_output.put_line('hi'); END;", "SELECT 1 FROM dual;"]
    assert _records(script) == [
        Statement(
            text="BEGIN dbms_output.put_line('hi'); END;", line=1, terminator=None, kind="sql"
        ),
        Statement(text="SELECT 1 FROM dual", line=2, terminator=";"),
    ]


@pytest.mark.parametrize("word", ["EXEC", "EXECUTE", "execute"])
def test_exec_without_a_semicolon(word):
    assert _strings(f"{word} p16\nSELECT 1 FROM dual;")[0] == "BEGIN p16; END;"


def test_exec_unit_is_substituted_too():
    assert _strings("DEFINE p = proc\nEXEC &p;") == ["BEGIN proc; END;"]


def test_define_value_is_substituted_when_defined():
    # sqlplus 23.x, Oracle Free 23ai, 2026-10-10: DEFINE a = q, DEFINE b = &a, SELECT '&b' -> q
    assert _strings("DEFINE a = q\nDEFINE b = &a\nSELECT '&b' FROM dual;") == [
        "SELECT 'q' FROM dual;"
    ]


def test_define_value_keeps_double_hyphen_inside_quotes():
    assert _strings("DEFINE x = 'a--b'\nSELECT '&x' FROM dual;") == ["SELECT 'a--b' FROM dual;"]

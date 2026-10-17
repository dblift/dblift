"""CLP commands and the epilogue of a Db2 script: refused, or SQL, as the established splitter decided."""

from dataclasses import replace

from dblift.db.plugins.db2.parser.lexical_spec import DB2_RULES, DB2_SPEC
from tests.unit.core.sql_parser.test_db2_terminator_script import CASES, check, group, outcome


def with_rules(**changes):
    return replace(DB2_SPEC, terminator_script=replace(DB2_RULES, **changes))


@group("command_words")
def test_every_command_word_is_refused_as_a_first_word(case):
    check(case)


@group("command_phrases")
def test_every_command_phrase_is_refused(case):
    check(case)


@group("commands")
def test_commands_sql_and_the_epilogue(case):
    check(case)


def test_the_cases_cover_every_word_and_phrase_of_the_data():
    assert {c["id"] for c in CASES["command_words"]} == set(DB2_RULES.command_words)
    assert {c["id"] for c in CASES["command_phrases"]} == {
        " ".join(p) for p in DB2_RULES.command_phrases
    }


def test_command_words_field_is_read():
    assert outcome("REORG TABLE t;\n")[:2] == ["error", "UnsupportedMetaCommandError"]
    spec = with_rules(command_words=DB2_RULES.command_words - {"REORG"})
    assert outcome("REORG TABLE t;\n", spec) == ["records", ["REORG TABLE t", 1, ";", "sql", 0, 15]]


def test_command_phrases_field_is_read():
    assert outcome("SET CLIENT X;\n")[:2] == ["error", "UnsupportedMetaCommandError"]
    spec = with_rules(command_phrases=DB2_RULES.command_phrases - {("SET", "CLIENT")})
    assert outcome("SET CLIENT X;\n", spec)[1][0] == "SET CLIENT X"
    spec = with_rules(command_phrases=DB2_RULES.command_phrases - {("UPDATE", "DB", "CFG")})
    assert outcome("UPDATE DB CFG USING x 1;\n", spec)[1][0] == "UPDATE DB CFG USING x 1"


def test_sql_phrases_field_is_read():
    assert outcome("GET DIAGNOSTICS x = ROW_COUNT;\n")[1][0] == "GET DIAGNOSTICS x = ROW_COUNT"
    spec = with_rules(sql_phrases=frozenset())
    assert outcome("GET DIAGNOSTICS x = ROW_COUNT;\n", spec)[2] == (
        "CLP command GET on line 1: dblift does not run client commands"
    )


def test_epilogue_words_field_is_read():
    script = "VALUES 1;\nQUIT;\nVALUES 2;\n"
    assert outcome(script)[2] == "CLP command QUIT on line 2: dblift does not run client commands"
    spec = with_rules(epilogue_words=DB2_RULES.epilogue_words - {("QUIT",)})
    assert outcome("VALUES 1;\nQUIT;\n", spec)[2] == (
        "CLP command QUIT on line 2: dblift does not run client commands"
    )
    assert outcome("VALUES 1;\nQUIT;\n")[2][0] == "QUIT"
    only_quit = with_rules(epilogue_words=frozenset({("QUIT",)}))
    assert outcome("VALUES 1;\nCONNECT RESET;\n", only_quit)[2] == (
        "CLP command CONNECT on line 2: dblift does not run client commands"
    )


def test_epilogue_field_is_read():
    script = "VALUES 1;\nQUIT -- bye\n;\n"
    assert outcome(script)[2] == ["QUIT -- bye", 2, ";", "directive", 10, 24]
    strict = with_rules(epilogue=r"(?i)(?:QUIT|TERMINATE|CONNECT[ \t]+RESET)[ \t]*\Z")
    assert outcome(script, strict)[2] == (
        "QUIT on line 2 is not alone on its line: the CLP joins it with what follows and the "
        "server rejects the text; end it with the terminator"
    )


def test_command_prefixes_field_is_read():
    assert outcome("? x;\n")[2] == "CLP command '?' on line 1: dblift does not run client commands"
    spec = with_rules(command_prefixes="!")
    assert outcome("? x;\n", spec)[1][0] == "? x"
    assert (
        outcome("!echo;\n", spec)[2]
        == "CLP command '!' on line 1: dblift does not run client commands"
    )


def test_leading_word_field_is_read():
    assert outcome("ECHO1 x;\n")[1][0] == "ECHO1 x"
    assert outcome("ECHO" + chr(36) + " x;\n")[2] == (
        "CLP command ECHO on line 1: dblift does not run client commands"
    )
    spec = with_rules(leading_word=r"[A-Za-z_]+")
    assert (
        outcome("ECHO1 x;\n", spec)[2]
        == "CLP command ECHO on line 1: dblift does not run client commands"
    )


def test_the_client_name_is_in_every_command_message():
    named = replace(DB2_SPEC, client_name="X")
    for script in ("REORG TABLE t;\n", "!echo;\n", "QUIT foo;\n", "QUIT;\nVALUES 1;\n"):
        message = outcome(script, named)[2]
        assert "CLP" not in message and "X" in message, script

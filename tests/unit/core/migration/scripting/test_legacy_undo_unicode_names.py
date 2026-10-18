"""The legacy undo generator and script analysis never name an object an engine reads differently.

On dialects without an active statement-facts reader, a character the extractors skip or cut at
(a no-break space, a zero-width space, a combining accent) can sit inside the name the engine
reads, so ``CREATE TABLE t<NBSP>(id INT)`` makes ``t<NBSP>``. Naming ``t`` would make the
generated undo drop the user's own ``t``. Such statements are left to manual review instead.
"""

from __future__ import annotations

import logging
import warnings

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.scripting.undo_script_generator._generator import UndoScriptGenerator
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC

LEGACY = (
    "postgresql",
    "mysql",
    "mariadb",
    "sqlserver",
    "oracle",
    "db2",
    "snowflake",
    "redshift",
    "cockroachdb",
)

# The 22 characters (sqlglot's non-ASCII blanks, plus the zero-width ones): a sample of each kind.
BLANKS = [" ", " ", "　", "\u0085", " ", " "]
ZERO_WIDTH = ["​", "⁠", "﻿"]
# Not blanks: an engine keeps them in a name, and the extractors stop at them.
READ_WHOLE = ("sqlserver", "snowflake")  # their extractors read these as part of the name
NAME_PARTS = ["‍", "­", "́"]
RULE = BLANKS + ZERO_WIDTH
IDS = {c: f"U+{ord(c):04X}" for c in RULE + NAME_PARTS}

TRIGGERS = {
    "postgresql": "CREATE TRIGGER tr{c} BEFORE INSERT ON t FOR EACH ROW EXECUTE FUNCTION f();",
    "mysql": "CREATE TRIGGER tr{c} BEFORE INSERT ON t FOR EACH ROW SET NEW.a = 1;",
    "mariadb": "CREATE TRIGGER tr{c} BEFORE INSERT ON t FOR EACH ROW SET NEW.a = 1;",
    "sqlserver": "CREATE TRIGGER tr{c} ON t AFTER INSERT AS SELECT 1;",
}
SHAPES = {
    "table": "CREATE TABLE t{c}(id INT);",
    "table-prefix": "CREATE TABLE {c}t(id INT);",
    "table-qualified": "CREATE TABLE s.t{c}(id INT);",
    "index": "CREATE INDEX ix{c} ON t(id);",
    "view": "CREATE VIEW v{c} AS SELECT 1 AS a;",
}


@pytest.fixture(autouse=True)
def _quiet():
    logging.disable(logging.CRITICAL)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield
    logging.disable(logging.NOTSET)


def refused(dialect: str, char: str) -> bool:
    """Oracle's driver strips an edge character its engine does not read as a blank: refused."""
    return dialect == "oracle" and char.isspace() and char not in ORACLE_SPEC.text_blanks


def read_as_blank(dialect: str, char: str, sql: str) -> bool:
    """Oracle's engine reads these characters as blanks: the name before one that ends the statement
    is read whole. A blank before a terminator stays under the caution (its span holds it)."""
    return dialect == "oracle" and char in ORACLE_SPEC.text_blanks and ";" not in sql


def _undo(tmp_path, dialect: str, sql: str) -> str:
    migration = tmp_path / "V1__x.sql"
    migration.write_text(sql + "\n", encoding="utf-8")
    out = UndoScriptGenerator(dialect).generate_undo_script(migration)
    return out.read_text(encoding="utf-8")


def _code_lines(script: str) -> list[str]:
    return [line for line in script.split("\n") if line.strip() and not line.startswith("--")]


def _assert_manual_review(script: str) -> None:
    assert not _code_lines(script), f"an undo statement was written:\n{script}"
    assert "WARNING" in script


@pytest.mark.parametrize("dialect", LEGACY)
@pytest.mark.parametrize("shape", sorted(SHAPES))
@pytest.mark.parametrize("char", RULE + NAME_PARTS, ids=IDS.get)
def test_undo_names_no_object_whose_name_holds_the_character(tmp_path, dialect, shape, char):
    script = _undo(tmp_path, dialect, SHAPES[shape].format(c=char))
    if dialect in READ_WHOLE and char in NAME_PARTS:
        # it reads these as part of the name: whatever is dropped, it is that name
        assert all(char in line for line in _code_lines(script))
        return
    _assert_manual_review(script)


@pytest.mark.parametrize("dialect", sorted(TRIGGERS))
@pytest.mark.parametrize("char", RULE + NAME_PARTS, ids=IDS.get)
def test_undo_names_no_trigger_whose_name_holds_the_character(tmp_path, dialect, char):
    script = _undo(tmp_path, dialect, TRIGGERS[dialect].format(c=char))
    if dialect in READ_WHOLE and char in NAME_PARTS:
        return
    assert not any("DROP TRIGGER" in line for line in _code_lines(script))


@pytest.mark.parametrize("dialect", LEGACY)
def test_undo_keeps_dropping_ascii_names(tmp_path, dialect):
    script = _undo(tmp_path, dialect, "CREATE TABLE t (id INT);\nCREATE INDEX ix ON t (id);")
    assert len([line for line in _code_lines(script) if "DROP" in line]) >= 1


@pytest.mark.parametrize("dialect", LEGACY)
def test_undo_ignores_the_character_inside_strings_comments_and_quotes(tmp_path, dialect):
    nbsp = " "
    quote = {"mysql": "`", "mariadb": "`", "sqlserver": '"'}.get(dialect, '"')
    sql = (
        f"CREATE TABLE t (id INT);\n-- note{nbsp}here\n"
        f"/* a{nbsp}b */\nCREATE INDEX ix ON t (id);\n"
        f"CREATE VIEW v AS SELECT 'a{nbsp}b' AS c;\n"
        f"CREATE TABLE {quote}q{nbsp}{quote} (id INT);"
    )
    drops = [line for line in _code_lines(_undo(tmp_path, dialect, sql)) if "DROP" in line]
    # the statements around the quoted name are still reversed
    assert len(drops) >= 2


@pytest.mark.parametrize("dialect", ("sqlserver", "oracle"))
def test_non_ascii_letter_name_is_named_where_the_extractor_reads_it_whole(tmp_path, dialect):
    script = _undo(tmp_path, dialect, "CREATE TABLE tété (id INT);")
    assert any("é" in line.lower() for line in _code_lines(script))


@pytest.mark.parametrize("dialect", ("postgresql", "mysql", "mariadb", "db2", "redshift"))
def test_non_ascii_letter_name_needs_manual_review_on_cutting_dialects_until_facts_readers_activate(
    tmp_path, dialect
):
    """The extractor reads ``t`` from ``t<e acute>``: that is a different object."""
    _assert_manual_review(_undo(tmp_path, dialect, "CREATE TABLE t\u00e9 (id INT);"))


@pytest.mark.parametrize(
    "sql", ['CREATE TABLE "q\u00e9" (id INT);', "INSERT INTO t\u00e9 (id) VALUES (1);"]
)
def test_undo_trusts_no_name_of_a_non_ascii_statement_that_named_nothing(tmp_path, sql):
    """Oracle's extractor names neither; the undo's own pattern would read them again."""
    _assert_manual_review(_undo(tmp_path, "oracle", sql))


@pytest.mark.parametrize("dialect", LEGACY)
def test_the_unparsed_fallback_names_nothing_either(dialect):
    undo = UndoScriptGenerator(dialect)._reverse_statement(f"CREATE TABLE t{chr(0xA0)}(id INT)")
    assert undo.requires_manual_review and "DROP" not in undo.sql


@pytest.mark.parametrize("dialect", LEGACY)
@pytest.mark.parametrize("char", RULE + NAME_PARTS, ids=IDS.get)
@pytest.mark.parametrize("template", ["DROP TABLE t{c} CASCADE;", "DELETE FROM t{c}WHERE a = 1;"])
def test_analysis_names_no_object_whose_name_holds_the_character(dialect, char, template):
    analysis = analyse_script(template.format(c=char), dialect)
    if dialect in READ_WHOLE and char in NAME_PARTS:
        return
    names = {obj.name.lower() for stmt in analysis.statements for obj in stmt.objects}
    assert "t" not in names
    assert not any(" t " in f" {c.reason} ".lower() for c in analysis.cautions)


# The analysis split trims blanks that end a statement, so a name that ends its statement is
# seen without the character the engine reads as part of it.
ALL_BLANKS = [c for c in map(chr, range(0x80, 0x10000)) if c.isspace()]
TAIL_DIALECTS = ("postgresql", "mysql", "mariadb", "oracle", "db2", "redshift", "cockroachdb")


def test_there_are_19_trailing_blanks():
    assert len(ALL_BLANKS) == 19


@pytest.mark.parametrize("dialect", TAIL_DIALECTS)
@pytest.mark.parametrize("char", ALL_BLANKS, ids=lambda c: f"U+{ord(c):04X}")
@pytest.mark.parametrize(
    "sql",
    ["CREATE SEQUENCE q{c};", "CREATE SEQUENCE q{c}", "CREATE TABLE t{c}", "CREATE TABLE t{c};\n"],
)
def test_undo_of_a_name_that_ends_its_statement_is_manual_review(tmp_path, dialect, char, sql):
    if refused(dialect, char):
        with pytest.raises(UnsafeStatementSplitError):
            _undo(tmp_path, dialect, sql.format(c=char))
        return
    script = _undo(tmp_path, dialect, sql.format(c=char))
    if read_as_blank(
        dialect, char, sql
    ):  # the engine reads the name before the blank: it is dropped
        assert any(line.startswith("DROP") for line in _code_lines(script)), script
        return
    _assert_manual_review(script)


@pytest.mark.parametrize("dialect", TAIL_DIALECTS)
@pytest.mark.parametrize("char", ALL_BLANKS, ids=lambda c: f"U+{ord(c):04X}")
@pytest.mark.parametrize(
    "sql", ["DROP TABLE t{c};", "TRUNCATE TABLE t{c};", "DELETE FROM t{c};", "DROP TABLE t{c}"]
)
def test_analysis_of_a_name_that_ends_its_statement_names_nothing(dialect, char, sql):
    if refused(dialect, char):  # the script is not parsed: nothing is named
        assert not analyse_script(sql.format(c=char), dialect).statements
        return
    analysis = analyse_script(sql.format(c=char), dialect)
    names = {obj.name.lower() for stmt in analysis.statements for obj in stmt.objects}
    if read_as_blank(dialect, char, sql):  # the engine reads the name before the blank
        assert "t" in names
        return
    assert "t" not in names
    assert not any(" t " in f" {c.reason} ".lower() for c in analysis.cautions)
    assert analysis.cautions, "the statement still deserves its caution"


@pytest.mark.parametrize("dialect", ("postgresql", "mysql", "redshift"))
def test_analysis_respects_the_flag_the_parser_set_for_a_cut_name(dialect):
    analysis = analyse_script("DROP TABLE tété;", dialect)
    assert not [obj for stmt in analysis.statements for obj in stmt.objects]
    assert analysis.cautions and not any("tété" in c.reason for c in analysis.cautions)


@pytest.mark.parametrize("dialect", LEGACY)
def test_unreadable_delete_is_cautioned_as_an_unreadable_one(dialect):
    (caution,) = analyse_script(f"DELETE FROM t{chr(0xA0)} CASCADE;", dialect).cautions
    assert "could not be read" in caution.reason and " of t" not in caution.reason


def test_the_unparsed_fallback_reads_the_blanks_the_split_trimmed():
    generator = UndoScriptGenerator("postgresql")
    undo = generator._reverse_statement("CREATE SEQUENCE q", "CREATE SEQUENCE q ")
    assert undo.requires_manual_review and "DROP" not in undo.sql
    assert generator._reverse_statement("CREATE SEQUENCE q", None).requires_manual_review
    assert "DROP" in generator._reverse_statement("CREATE SEQUENCE q").sql


@pytest.mark.parametrize("dialect", ("postgresql", "mysql", "oracle"))
def test_the_unparsed_fallback_of_a_script_reads_the_blanks_the_split_trimmed(dialect):
    from types import SimpleNamespace

    from dblift.core.sql_model.base import ParseResult

    generator = UndoScriptGenerator(dialect)
    generator.parser.parse_sql = lambda *a, **k: ParseResult(
        success=False, statements=[], errors=["x"]
    )
    migration = SimpleNamespace(content=f"CREATE SEQUENCE q{chr(0xA0)};\n")
    if refused(dialect, chr(0xA0)):
        with pytest.raises(UnsafeStatementSplitError):
            generator._generate_undo_statements(migration)
        return
    (undo,) = generator._generate_undo_statements(migration)
    assert undo.requires_manual_review and "DROP" not in undo.sql


# The statement text also stands, unchanged, in an earlier comment: the span must be the
# statement's own, not the first place its text appears.
BYPASS_DIALECTS = ("postgresql", "mysql", "oracle")
BYPASS_CHARS = (" ", " ")


@pytest.mark.parametrize("dialect", BYPASS_DIALECTS)
@pytest.mark.parametrize("char", BYPASS_CHARS, ids=lambda c: f"U+{ord(c):04X}")
@pytest.mark.parametrize(
    "script",
    [
        "-- CREATE SEQUENCE q\nCREATE SEQUENCE q{c};",
        "/* CREATE TABLE t */\nCREATE TABLE t{c};",
        "-- CREATE SEQUENCE q\nCREATE SEQUENCE q{c}\n",
    ],
)
def test_undo_of_a_statement_whose_text_also_stands_in_a_comment(tmp_path, dialect, char, script):
    if refused(dialect, char):
        with pytest.raises(UnsafeStatementSplitError):
            _undo(tmp_path, dialect, script.format(c=char))
        return
    _assert_manual_review(_undo(tmp_path, dialect, script.format(c=char)))


@pytest.mark.parametrize("dialect", BYPASS_DIALECTS)
@pytest.mark.parametrize("char", BYPASS_CHARS, ids=lambda c: f"U+{ord(c):04X}")
def test_analysis_of_a_statement_whose_text_also_stands_in_a_comment(dialect, char):
    if refused(dialect, char):  # the script is not parsed: nothing is named
        assert not analyse_script(f"-- DROP TABLE t\nDROP TABLE t{char};", dialect).statements
        return
    analysis = analyse_script(f"-- DROP TABLE t\nDROP TABLE t{char};", dialect)
    assert not [obj for stmt in analysis.statements for obj in stmt.objects]
    assert analysis.cautions and not any(" t " in f" {c.reason} " for c in analysis.cautions)


def test_a_readable_statement_before_an_unreadable_one_is_still_reversed(tmp_path):
    script = f"CREATE SEQUENCE q;\nCREATE SEQUENCE q{chr(0xA0)};\n"
    text = _undo(tmp_path, "postgresql", script)
    assert [line for line in _code_lines(text) if "DROP" in line] == [
        'DROP SEQUENCE IF EXISTS "q";'
    ]
    assert text.count("WARNING: Cannot reverse a statement whose object names") == 1

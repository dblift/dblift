"""Analysis reads the statements execution runs: a statement of kept characters is not empty."""

import pytest

from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.unit

NBSP = " "
CASES = [
    ("db2", f"VALUES 1;\n{NBSP};\nVALUES 2;"),
    ("mysql", f"SELECT 1;\n{NBSP};\nSELECT 2;"),
    ("mariadb", f"SELECT 1;\n{NBSP};\nSELECT 2;"),
    ("postgresql", f"SELECT 1;\n{NBSP};\nSELECT 2;"),
    ("sqlite", f"SELECT 1;\n{NBSP};\nSELECT 2;"),
    ("duckdb", f"SELECT 1;\n{NBSP};\nSELECT 2;"),
]


def _executed(dialect, text):
    quirks = ProviderRegistry.get_quirks(dialect)
    blanks = quirks.empty_statement_blanks()
    parser = ProviderRegistry.get_quirks(dialect).parser_class("regex")()
    return [s.strip(blanks) for s in parser.split_for_analysis(text) if s.strip(blanks)]


@pytest.mark.parametrize(("dialect", "text"), CASES)
def test_analysis_statements_equal_the_executed_statements(dialect, text):
    analysis = analyse_script(text, dialect)
    assert [
        s.sql.strip(ProviderRegistry.get_quirks(dialect).empty_statement_blanks())
        for s in analysis.statements
    ] == _executed(dialect, text)


@pytest.mark.parametrize("dialect", ["db2", "mysql", "mariadb"])
def test_a_kept_character_statement_is_surfaced_not_dropped(dialect):
    text = dict(CASES)[dialect]
    analysis = analyse_script(text, dialect)
    assert len(analysis.statements) == 3
    assert analysis.statements[1].sql == NBSP


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite", "duckdb"])
def test_str_strip_dialects_still_skip_the_character(dialect):
    assert len(analyse_script(dict(CASES)[dialect], dialect).statements) == 2


def test_oracle_refuses_the_character_and_the_refusal_is_surfaced():
    analysis = analyse_script(f"SELECT 1 FROM dual;\n{NBSP};\nSELECT 2 FROM dual;", "oracle")
    assert analysis.statements == () and analysis.errors


@pytest.mark.parametrize("dialect", ["db2", "mysql", "mariadb"])
def test_undo_flags_the_kept_character_statement_for_manual_review(dialect):
    from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
    from tests.unit._migration_factory import make_migration

    script = f"CREATE TABLE a (i int);\n{NBSP};\nCREATE TABLE b (i int);"
    migration = make_migration(script_name="V1__t.sql", content=script)
    undo = UndoScriptGenerator(dialect)._generate_undo_statements(migration)
    assert [s.requires_manual_review for s in undo] == [False, True, False]


@pytest.mark.parametrize("dialect", ["db2", "mysql", "mariadb"])
def test_lint_does_not_crash_on_the_kept_character_statement(dialect):
    from dblift.core.migration.sql.lint import lint_script

    script = f"CREATE TABLE a (i int);\n{NBSP};\nCREATE TABLE b (i int);"
    assert lint_script(script, dialect, "V1.sql").verdict == "SAFE"


@pytest.mark.parametrize(
    ("dialect", "text", "snippet"),
    [
        ("db2", NBSP, "U+00A0"),
        ("mysql", NBSP, "U+00A0"),
        ("mysql", "\x1c SELECT 1", "U+001C SELECT 1"),
    ],
)
def test_the_snippet_shows_a_kept_character_as_its_code_point(dialect, text, snippet):
    analysis = analyse_script(f"SELECT 1;\n{text};", dialect)
    assert analysis.statements[1].snippet == snippet

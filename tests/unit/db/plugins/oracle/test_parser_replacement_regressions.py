"""Oracle parsing uses its executable SQL*Plus selection consistently."""

from dblift.core.migration.sql.statement_reader import StatementReader
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from tests.support.facts_parser import facts_parser


def test_exit_shields_ignored_malformed_tail_from_tokenizer() -> None:
    script = "SELECT 1 FROM dual;\nEXIT\nSELECT 'unterminated"

    assert facts_parser("oracle").split_statements(script) == ["SELECT 1 FROM dual;"]


def test_exit_does_not_parse_later_exits_or_malformed_tail() -> None:
    script = "SELECT 1 FROM dual;\nEXIT\n" + "EXIT\n" * 1000 + "SELECT 'unterminated"

    assert facts_parser("oracle").split_statements(script) == ["SELECT 1 FROM dual;"]


def test_parse_sql_selects_the_same_statements_as_execution() -> None:
    script = "SELECT 1 FROM dual;\nEXIT\nDROP TABLE users;"
    parser = facts_parser("oracle")

    assert [stmt.sql_text for stmt in parser.parse_sql(script).statements] == ["SELECT 1 FROM dual"]


def test_public_analyzer_uses_oracle_execution_selection() -> None:
    script = "SELECT 1 FROM dual;\nEXIT\nDROP TABLE users;"

    assert StatementReader(dialect="oracle").split_statements_for_analysis(script) == [
        "SELECT 1 FROM dual"
    ]


def test_repeated_record_and_string_projections_preserve_define_state() -> None:
    script = "DEFINE x = ok\nSELECT '&x' FROM dual;\nSET DEFINE OFF\n"
    engine = LexicalEngine(ORACLE_SPEC)

    first = engine.split(script)

    assert engine.split(script) == first
    assert engine.split_statements(script) == ["SELECT 'ok' FROM dual;"]


def test_large_script_cost_is_bounded_in_sliced_characters() -> None:
    class CountingText(str):
        sliced = 0

        def __getitem__(self, key):
            if isinstance(key, slice):
                self.sliced += len(range(*key.indices(len(self))))
            return super().__getitem__(key)

    for repetitions in (100, 400):
        script = CountingText("SELECT 1 FROM dual;\n" * repetitions)
        assert len(LexicalEngine(ORACLE_SPEC).split(script)) == repetitions
        assert script.sliced <= 12 * len(script)

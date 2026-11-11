"""A psql ``\\;`` statement that the end of the script, not a terminator, ends.

Its last joined statement runs to the end of the source.
"""

from dataclasses import astuple

from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC


def test_last_joined_statement_runs_to_the_end_of_the_script() -> None:
    records = LexicalEngine(POSTGRESQL_SPEC).split("SELECT 1 \\; SELECT 2")

    assert [astuple(r) for r in records] == [
        ("SELECT 1 ; SELECT 2", 1, None, "sql", True, 1, ("SELECT 1", "SELECT 2"), 0, 20, None)
    ]

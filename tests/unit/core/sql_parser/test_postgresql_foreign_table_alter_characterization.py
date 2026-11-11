"""Characterization of ALTER FOREIGN TABLE parser branches other suites leave unexercised.

A form the foreign-table grammar does not read becomes a Command. Which Command it becomes tells
where the reading stopped: a refusal before the table becomes ``ALTER`` and the text after it,
while a tail no foreign-table action reads is handed to the PostgreSQL ALTER grammar and comes
back as ``FOREIGN`` and the text after that.
"""

import pytest
import sqlglot
from sqlglot import exp

from dblift.db.plugins.postgresql.foreign_table_dialect import PostgresForeignTable


@pytest.mark.parametrize(
    ("sql", "this", "expression"),
    [
        # FOREIGN not followed by TABLE.
        (
            "ALTER FOREIGN DATA WRAPPER w OPTIONS (ADD a 'b')",
            "ALTER",
            " FOREIGN DATA WRAPPER w OPTIONS (ADD a 'b')",
        ),
        # ENABLE not followed by TRIGGER.
        ("ALTER FOREIGN TABLE t ENABLE RULE r", "FOREIGN", " TABLE t ENABLE RULE r"),
        # ENABLE TRIGGER without a trigger name.
        ("ALTER FOREIGN TABLE t ENABLE TRIGGER", "FOREIGN", " TABLE t ENABLE TRIGGER"),
        # NO INHERIT without a parent table.
        ("ALTER FOREIGN TABLE t NO INHERIT 1", "FOREIGN", " TABLE t NO INHERIT 1"),
    ],
)
def test_an_alter_foreign_form_the_grammar_does_not_read_is_a_command(sql, this, expression):
    node = sqlglot.parse_one(sql, read=PostgresForeignTable)

    assert type(node) is exp.Command
    assert (node.this, node.expression) == (this, expression)


def test_an_unread_alter_tail_does_not_turn_the_next_statement_into_a_command():
    sql = "ALTER FOREIGN TABLE t ALTER COLUMN c TYPE int USING; ALTER FOREIGN TABLE t ADD COLUMN d int"

    first, second = sqlglot.parse(sql, read=PostgresForeignTable)

    assert type(first) is exp.Command
    assert type(second) is exp.Alter

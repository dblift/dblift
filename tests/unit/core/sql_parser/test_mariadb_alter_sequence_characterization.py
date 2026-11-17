"""Characterization of MariaDB ALTER SEQUENCE proof branches other suites leave unexercised.

Statement facts drop the opaque diagnostic only when the whole MariaDB ALTER SEQUENCE form is
proven. The reader cases pin a head whose name the proof cannot read and one whose name differs
from the name the facts carry. The direct cases pin refusals the reader never reaches, because it
only asks for a proof of a statement it has tokenized and named itself. The cases pin outcomes:
where a later check refuses the same input, removing the earlier refusal alone is not caught.
"""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts
from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mariadb.statement_facts import _alter_sequence_options_are_proven

OPAQUE = "sequence: mysql Command is opaque to statement facts"


@pytest.mark.parametrize(
    ("sql", "name"),
    [
        # EXISTS without IF is a keyword token, not a name the proof reads.
        ("ALTER SEQUENCE EXISTS RESTART", "RESTART"),
        # The proof reads IF EXISTS, then IF as the name; the facts name RESTART.
        ("ALTER SEQUENCE IF EXISTS IF RESTART", "RESTART"),
    ],
)
def test_a_sequence_head_the_proof_does_not_name_as_the_facts_do_stays_opaque(sql, name):
    facts = MariadbQuirks().statement_facts(sql)

    assert (facts.operation, facts.kind, facts.diagnostic, facts.error) == (
        "ALTER",
        "DDL",
        OPAQUE,
        None,
    )
    assert [(o.name, o.type, o.role, o.schema) for o in facts.objects] == [
        (name, SqlObjectType.SEQUENCE, "altered", None)
    ]


def _facts(*names):
    return StatementFacts(
        "ALTER",
        "DDL",
        objects=tuple(NamedObject(n, SqlObjectType.SEQUENCE, "altered") for n in names),
        diagnostic=OPAQUE,
    )


@pytest.mark.parametrize(
    ("sql", "facts"),
    [
        # Text the MySQL tokenizer refuses proves nothing.
        ("ALTER SEQUENCE s RESTART 'x", _facts("s")),
        # The tokens must start with ALTER SEQUENCE.
        ("s RESTART", _facts("s")),
        # The facts must name exactly one object.
        ("ALTER SEQUENCE s RESTART", _facts("s", "s")),
    ],
)
def test_a_proof_the_reader_never_requests_is_refused(sql, facts):
    assert _alter_sequence_options_are_proven(sql, facts) is False

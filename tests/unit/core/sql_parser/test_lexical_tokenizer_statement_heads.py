"""Characterization of where the shared tokenizer sees a statement head for COPY FROM STDIN."""

import pytest

from dblift.core.exceptions import UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("head", ["copy t from stdin;", "Copy t From Stdin;"])
def test_a_copy_header_in_any_letter_case_reads_its_data_block(head):
    script = f"{head}\n1;2\n\\.\nSELECT 1;"

    records = LexicalEngine(POSTGRESQL_SPEC).split(script)

    assert [record.text for record in records] == [f"{head}\n1;2\n", "SELECT 1"]


def test_a_semicolon_inside_parentheses_does_not_start_a_copy_statement():
    script = "SELECT (1; COPY t FROM STDIN;\n1\t2\n\\.\nSELECT 2;"

    with pytest.raises(UnsupportedMetaCommandError, match="meta-command .* at line 3"):
        LexicalEngine(POSTGRESQL_SPEC).split(script)

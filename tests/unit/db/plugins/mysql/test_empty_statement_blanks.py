"""How the MySQL lexical spec reads its trailing edge."""

from dataclasses import replace

import pytest

pytestmark = pytest.mark.unit


def test_a_spec_without_trailing_blanks_strips_its_trailing_edge_as_its_leading_edge():
    from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC

    plain = replace(MYSQL_SPEC, trailing_blanks="")
    assert plain.trailing_edge_blanks == plain.text_blanks
    assert MYSQL_SPEC.trailing_edge_blanks == MYSQL_SPEC.trailing_blanks

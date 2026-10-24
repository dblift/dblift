"""MySQL-family character refusals come from the lexical specification."""

from dataclasses import replace

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.mariadb.lexical_spec import MARIADB_SPEC
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC


@pytest.mark.parametrize("spec", [MYSQL_SPEC, MARIADB_SPEC], ids=["mysql", "mariadb"])
@pytest.mark.parametrize(
    "script, line, column",
    [
        ("SELECT 1;\x00SELECT 2;", 1, 10),
        ("SELECT 'é\x00';", 1, 10),
        ("SELECT /* é\x00 */;", 1, 12),
        ("\ufeffSELECT \x00;", 1, 8),
        ("\ufeffSELECT é;\r\n-- α\x00\nexit", 2, 5),
        ("exit\nSELECT 1\x00;", 2, 9),
        ("DELIMITER\nSELECT \x00", 2, 8),
    ],
)
def test_nul_is_refused_first_at_its_source_position(spec, script, line, column):
    with pytest.raises(UnsafeStatementSplitError) as caught:
        LexicalEngine(spec).split_statements(script)
    assert str(caught.value) == (
        f"a NUL character on line {line}, column {column}: "
        f"the {spec.client_name} client refuses it unless --binary-mode is set"
    )


@pytest.mark.parametrize("spec", [MYSQL_SPEC, MARIADB_SPEC], ids=["mysql", "mariadb"])
def test_refusal_character_is_spec_data(spec):
    alternate = replace(
        spec,
        refused_character="@",
        refused_character_name="at sign",
        refused_reason="test policy",
    )
    with pytest.raises(UnsafeStatementSplitError, match="at sign character on line 1, column 8"):
        LexicalEngine(alternate).split_statements("SELECT @;")
    assert LexicalEngine(alternate).split_statements("SELECT '\x00';") == ["SELECT '\x00'"]


@pytest.mark.parametrize("spec", [MYSQL_SPEC, MARIADB_SPEC], ids=["mysql", "mariadb"])
def test_removing_spec_refusal_allows_nul_in_a_literal(spec):
    permissive = replace(spec, refused_character="", refused_character_name="", refused_reason="")
    assert LexicalEngine(permissive).split_statements("SELECT '\x00';") == ["SELECT '\x00'"]

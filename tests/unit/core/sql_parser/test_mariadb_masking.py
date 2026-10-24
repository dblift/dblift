"""MariaDB literal masking replaces string values and credentials, and keeps the statement's shape."""

import pytest

from dblift.core.sql_parser.redaction import describe_statement, mask_string_literals

pytestmark = pytest.mark.unit


def test_string_literals_are_masked_in_both_quote_styles():
    sql = "INSERT INTO t VALUES ('secret', \"s2\") -- 'c'"
    assert mask_string_literals(sql, "mariadb") == "INSERT INTO t VALUES ('?', '?') -- 'c'"


def test_the_value_after_identified_by_is_masked():
    sql = "CREATE USER bob IDENTIFIED BY 'pw'"
    assert mask_string_literals(sql, "mariadb") == "CREATE USER bob IDENTIFIED BY '?'"


def test_a_description_names_the_verb_and_the_object_only():
    assert describe_statement("CREATE USER bob IDENTIFIED BY 'pw'", "mariadb") == "CREATE USER bob"

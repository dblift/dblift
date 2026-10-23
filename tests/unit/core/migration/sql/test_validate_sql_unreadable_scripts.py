"""What `validate-sql` reports for two scripts the removed analyzer used to judge differently.

The command lints through the script analysis, not through the analyzer's own check: a script the
reader cannot tokenize is marked for review, with the reason, on every dialect.
"""

import pytest

from dblift.core.migration.sql.lint import REVIEW, lint_script

pytestmark = pytest.mark.unit


def test_an_unresolved_placeholder_in_a_name_is_marked_for_review():
    lint = lint_script("CREATE TABLE ${schema}.${table} (id INT);\n", "postgresql", "V1__a.sql")

    assert lint.verdict == REVIEW
    assert any("could not be tokenized" in message for message in lint.errors)


def test_a_nested_comment_script_on_sql_server_is_marked_for_review():
    script = "/* a /* b */ DROP TABLE t_keep; */ CREATE TABLE t_after (x INT) /* tail */;\n"
    lint = lint_script(script, "sqlserver", "V1__a.sql")

    assert lint.verdict == REVIEW

"""Only plugin quirks select a DML reader in the 5.0 entry points."""

import inspect

import pytest

from dblift.db import dml_analysis

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("name", "keyword"),
    [
        ("analyze_dml", "sqlglot_dialect"),
        ("dml_where_predicate", "sqlglot_dialect"),
        ("updates_restore_key", "sqlglot_dialect"),
        ("is_full_table_dml", "sqlglot_dialect"),
        ("statement_dml_table", "dialect"),
    ],
)
def test_legacy_dml_keyword_is_absent_and_rejected(name, keyword):
    function = getattr(dml_analysis, name)
    assert keyword not in inspect.signature(function).parameters
    args = ("UPDATE t SET id = 1", ("id",)) if name == "updates_restore_key" else ("UPDATE t SET id = 1",)
    with pytest.raises(TypeError):
        function(*args, **{keyword: "postgres"})


def test_statement_dml_table_rejects_positional_dialect():
    with pytest.raises(TypeError):
        dml_analysis.statement_dml_table("UPDATE t SET id = 1", "postgres")


def test_other_sql_dialect_options_remain_available():
    assert "sqlglot_dialect" in inspect.signature(dml_analysis.insert_value_rows).parameters
    assert "sqlglot_dialect" in inspect.signature(dml_analysis.cte_outer_statement_type).parameters

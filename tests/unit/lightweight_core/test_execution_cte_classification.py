"""CTE dispatch in execution mode is independent of sqlglot."""

import pytest

from dblift.db import dml_analysis
from tests.unit.lightweight_core._support import run_python


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("WITH x AS (SELECT 1) SELECT * FROM x", "QUERY"),
        ("WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT * FROM x", "QUERY"),
        ("WITH x AS (SELECT 1), y AS (SELECT 2) UPDATE t SET n=1", "DML"),
        ("WITH x AS (DELETE FROM t RETURNING id) INSERT INTO archive SELECT id FROM x", "DML"),
        ("WITH x AS (SELECT '(INSERT)' AS v /* DELETE */) DELETE FROM t", "DML"),
        ("WITH x AS (SELECT $tag$(UPDATE t)$tag$ AS v) SELECT * FROM x", "QUERY"),
        ("WITH x AS (SELECT 1) MERGE INTO t USING x ON 1=1 WHEN MATCHED THEN DELETE", "DML"),
        ("WITH x AS (SELECT 1) SELECT * INTO new_t FROM x", "QUERY"),
        ("WITH x AS (SELECT 'UPDATE' AS v) SELECT * FROM x", "QUERY"),
        ("WITH x AS (SELECT 1", None),
        ("WITH x AS (SELECT 1) -- no outer verb", None),
        ("WITH x AS (SELECT 1) SELECT ('unterminated'", None),
        ("WITH x AS (SELECT 1) SELECT $tag$unterminated", None),
        ("WITH x AS (SELECT 1) SELECT 'unterminated", None),
    ],
)
def test_scan_identifies_outer_verb_without_ast(sql, expected):
    assert dml_analysis.scan_cte_outer_statement_type(sql, strict=True) == expected


def test_execution_analyzer_rejects_unbalanced_cte_select_into():
    from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer

    analyzer = SqlAnalyzer("sqlite", analysis_mode="execution")
    with pytest.raises(ValueError, match="analysis_mode='full'"):
        analyzer.get_statement_type("WITH x AS (SELECT 1) SELECT * INTO t FROM ('bad'")


def test_full_fallback_preserves_lexical_classification_for_unbalanced_tail(monkeypatch):
    import sqlglot

    def parse_failure(*args, **kwargs):
        raise ValueError("force lexical fallback")

    monkeypatch.setattr(sqlglot, "parse_one", parse_failure)
    assert (
        dml_analysis.cte_outer_statement_type("WITH x AS (SELECT 1) SELECT 'unterminated")
        == "QUERY"
    )


def test_execution_analyzer_classifies_bom_prefixed_cte_insert():
    from unittest.mock import patch

    from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer

    analyzer = SqlAnalyzer("sqlite", analysis_mode="execution")
    with patch(
        "dblift.core.migration.sql.sql_analyzer.scan_cte_outer_statement_type",
        return_value="DML",
    ) as scan:
        assert (
            analyzer.get_statement_type("\ufeffWITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x")
            == "DML"
        )
    scan.assert_called_once()


@pytest.mark.parametrize(
    ("dialect", "script"),
    [
        ("sqlserver", "CREATE TABLE t (id INT);\nGO\nINSERT INTO t VALUES (?);\nGO\n"),
        ("oracle", "CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;\n/\nSELECT :id FROM dual;"),
        (
            "mysql",
            "DELIMITER $$\nCREATE PROCEDURE p() BEGIN SELECT 1; END$$\n" "DELIMITER ;\nSELECT ?;",
        ),
        (
            "postgresql",
            "WITH x AS (SELECT 'a (DELETE)' AS txt /* INSERT */) SELECT txt FROM x; "
            "SELECT id INTO saved FROM t; CREATE INDEX CONCURRENTLY ix ON t (id);",
        ),
    ],
)
def test_dialect_split_classification_and_transaction_policy_match_full_without_ast(
    dialect, script, tmp_path
):
    import json

    from dblift.config import DbliftConfig
    from dblift.core.migration.executor.transaction_policy import TransactionPolicy
    from dblift.core.migration.sql.execution_statement import classify_execution_statement
    from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
    from dblift.db.plugins.sqlite.provider import SQLiteProvider

    def route(mode):
        analyzer = SqlAnalyzer(dialect, analysis_mode=mode)
        statements = analyzer.split_statements(script)
        classified = [
            classify_execution_statement(
                statement, dialect=dialect, statement_type=analyzer.get_statement_type(statement)
            )
            for statement in statements
        ]
        provider = SQLiteProvider(
            DbliftConfig.from_dict(
                {"database": {"type": "sqlite", "path": str(tmp_path / "policy.db")}}
            )
        )
        policy = TransactionPolicy().decide(classified, provider)
        return {
            "statements": [
                [entry.sql, entry.statement_type, entry.can_execute_in_transaction]
                for entry in classified
            ],
            "parameter_markers": [entry.sql.count("?") for entry in classified],
            "policy": vars(policy),
        }

    expected = route("full")
    result = run_python(
        f"""
import json
from dblift.config import DbliftConfig
from dblift.core.migration.executor.transaction_policy import TransactionPolicy
from dblift.core.migration.sql.execution_statement import classify_execution_statement
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.db.plugins.sqlite.provider import SQLiteProvider

dialect = {dialect!r}
script = {script!r}
analyzer = SqlAnalyzer(dialect, analysis_mode='execution')
statements = analyzer.split_statements(script)
classified = [classify_execution_statement(
    statement, dialect=dialect, statement_type=analyzer.get_statement_type(statement)
) for statement in statements]
provider = SQLiteProvider(DbliftConfig.from_dict({{
    'database': {{'type': 'sqlite', 'path': 'policy.db'}}
}}))
policy = TransactionPolicy().decide(classified, provider)
print(json.dumps({{
    'statements': [(entry.sql, entry.statement_type, entry.can_execute_in_transaction)
                   for entry in classified],
    'parameter_markers': [entry.sql.count('?') for entry in classified],
    'policy': vars(policy),
}}))
""",
        blocked=("sqlglot", "rich", "jinja2"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected

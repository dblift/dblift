"""Redshift clean-schema behavior."""

from db.plugins.redshift.provider import RedshiftProvider

EXPECTED_VIEW_NAME = '"analytics"."active_events"'
EXPECTED_TABLE_DROP = 'DROP TABLE IF EXISTS "analytics"."events" CASCADE'
EXPECTED_VIEW_DROP = f"DROP VIEW IF EXISTS {EXPECTED_VIEW_NAME} CASCADE"


class _RedshiftProvider(RedshiftProvider):
    def __init__(self) -> None:
        self.queries: list[tuple[str, object]] = []
        self.statements: list[tuple[str, object, object]] = []

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        if "information_schema.views" in sql:
            return [{"object_name": "active_events"}]
        if "information_schema.tables" in sql:
            return [{"object_name": "events"}]
        return []

    def execute_statement(self, sql, schema=None, params=None):
        self.statements.append((sql, schema, params))
        return 1


def test_redshift_clean_schema_uses_redshift_safe_catalogs() -> None:
    provider = _RedshiftProvider()

    summary = provider.clean_schema("analytics")

    queried_sql = "\n".join(sql for sql, _params in provider.queries)
    statement_sql = "\n".join(sql for sql, *_ in provider.statements)

    assert "pg_extension" not in queried_sql
    assert "pg_type" not in queried_sql
    assert "information_schema.views" in queried_sql
    assert "information_schema.tables" in queried_sql
    assert EXPECTED_VIEW_DROP in statement_sql
    assert EXPECTED_TABLE_DROP in statement_sql
    assert [(obj.object_type, obj.name) for obj in summary.objects] == [
        ("view", "active_events"),
        ("table", "events"),
    ]


def test_redshift_clean_preview_does_not_execute_drops() -> None:
    provider = _RedshiftProvider()
    expected_statements = [
        EXPECTED_VIEW_DROP,
        EXPECTED_TABLE_DROP,
    ]

    summary = provider.get_clean_preview("analytics")

    assert provider.statements == []
    assert summary.statements == expected_statements

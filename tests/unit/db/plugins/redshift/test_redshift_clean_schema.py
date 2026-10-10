"""Redshift clean-schema behavior."""

from unittest.mock import MagicMock

import pytest

from dblift.db.plugins.redshift.provider import RedshiftProvider

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


# ---------------------------------------------------------------------------
# Objects other than tables and views: materialized views, late-binding views,
# user-defined functions and stored procedures.
# ---------------------------------------------------------------------------

EXPECTED_MV_DROP = 'DROP MATERIALIZED VIEW IF EXISTS "analytics"."daily_totals" CASCADE'
EXPECTED_LATE_BINDING_DROP = 'DROP VIEW IF EXISTS "analytics"."lbv_events" CASCADE'
EXPECTED_PROCEDURE_DROP = 'DROP PROCEDURE "analytics"."refresh_totals"(integer, character varying)'
EXPECTED_FUNCTION_DROPS = [
    'DROP FUNCTION "analytics"."f_clean"(character varying) CASCADE',
    'DROP FUNCTION "analytics"."f_clean"(integer, integer) CASCADE',
    'DROP FUNCTION "analytics"."f_now"() CASCADE',
    'DROP FUNCTION "analytics"."f_we""ird"(integer) CASCADE',
]


class _FullProvider(_RedshiftProvider):
    """Stub with one object of every kind; ``failing`` names catalogs that raise."""

    def __init__(self, failing: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.failing = failing
        self.log = MagicMock()
        self.rollbacks = 0

    def rollback_transaction(self) -> None:
        self.rollbacks += 1

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        for catalog in self.failing:
            if catalog in sql:
                raise RuntimeError(f"relation {catalog} does not exist")
        if "svv_mv_info" in sql and "svv_redshift_tables" not in sql:
            return [{"object_name": "daily_totals"}]
        if "svv_redshift_tables" in sql:
            return [{"object_name": "lbv_events"}, {"object_name": "active_events"}]
        if "svv_redshift_functions" in sql:
            return [
                {
                    "object_name": "refresh_totals",
                    "function_type": "STORED PROCEDURE",
                    "argument_type": "integer, character varying",
                },
                {
                    "object_name": "f_clean",
                    "function_type": "REGULAR FUNCTION",
                    "argument_type": "character varying",
                },
                {
                    "object_name": "f_clean",
                    "function_type": "REGULAR FUNCTION",
                    "argument_type": "integer, integer",
                },
                {
                    "object_name": "f_now",
                    "function_type": "REGULAR FUNCTION",
                    "argument_type": None,
                },
                {
                    "object_name": 'f_we"ird',
                    "function_type": "REGULAR FUNCTION",
                    "argument_type": "integer",
                },
                {
                    "object_name": "agg_x",
                    "function_type": "AGGREGATE FUNCTION",
                    "argument_type": "integer",
                },
            ]
        # The listing of a materialized view as a plain view must not be dropped twice.
        if "information_schema.views" in sql:
            return [{"object_name": "active_events"}, {"object_name": "daily_totals"}]
        return super().execute_query(sql, params)


def test_clean_drops_every_object_kind_in_dependency_order() -> None:
    provider = _FullProvider()

    summary = provider.clean_schema("analytics")

    assert provider.statements and [sql for sql, *_ in provider.statements] == summary.statements
    assert summary.statements == [
        EXPECTED_MV_DROP,
        EXPECTED_VIEW_DROP,
        EXPECTED_LATE_BINDING_DROP,
        EXPECTED_TABLE_DROP,
        EXPECTED_PROCEDURE_DROP,
        *EXPECTED_FUNCTION_DROPS,
    ]
    assert [obj.object_type for obj in summary.objects] == [
        "materialized view",
        "view",
        "view",
        "table",
        "procedure",
        "function",
        "function",
        "function",
        "function",
    ]
    assert [obj.name for obj in summary.objects][4:6] == [
        "refresh_totals(integer, character varying)",
        "f_clean(character varying)",
    ]


def test_clean_preview_lists_every_object_kind_without_executing() -> None:
    provider = _FullProvider()

    summary = provider.get_clean_preview("analytics")

    assert provider.statements == []
    assert len(summary.statements) == 9
    assert EXPECTED_MV_DROP in summary.statements
    assert EXPECTED_PROCEDURE_DROP in summary.statements


def test_list_droppable_objects_carries_the_new_kinds_to_clean_command() -> None:
    provider = _FullProvider()

    objects = provider.list_droppable_objects("analytics")

    assert [obj.drop_sql for obj in objects][0] == EXPECTED_MV_DROP
    assert {obj.object_type for obj in objects} == {
        "materialized view",
        "view",
        "table",
        "procedure",
        "function",
    }


def test_new_catalog_queries_are_redshift_documented_and_scoped_to_the_schema() -> None:
    provider = _FullProvider()

    provider.get_clean_preview("analytics")

    sql = "\n".join(q for q, _ in provider.queries).lower()
    for catalog in ("svv_mv_info", "svv_redshift_tables", "svv_redshift_functions"):
        assert catalog in sql
    for pg_only in ("pg_extension", "pg_type", "pg_proc", "pg_class", "pg_sequence"):
        assert pg_only not in sql
    for query, params in provider.queries:
        assert params == ["analytics"] * query.count("?")


@pytest.mark.parametrize(
    ("catalog", "kind", "kept"),
    [
        ("svv_mv_info", "materialized view", [EXPECTED_VIEW_DROP, EXPECTED_TABLE_DROP]),
        ("svv_redshift_tables", "late-binding view", [EXPECTED_MV_DROP, EXPECTED_TABLE_DROP]),
        ("svv_redshift_functions", "routine", [EXPECTED_MV_DROP, EXPECTED_TABLE_DROP]),
    ],
)
def test_unreadable_catalog_skips_only_its_kind(catalog, kind, kept) -> None:
    provider = _FullProvider(failing=(catalog,))

    summary = provider.get_clean_preview("analytics")

    assert all(statement in summary.statements for statement in kept)
    assert EXPECTED_TABLE_DROP in summary.statements
    warnings = [call.args[0] for call in provider.log.warning.call_args_list]
    assert any(kind in warning and "analytics" in warning for warning in warnings)
    assert any(kind in error for error in summary.errors)
    assert provider.rollbacks >= 1  # a failed query must not poison the transaction

    executed = _FullProvider(failing=(catalog,))
    executed.clean_schema("analytics")
    assert EXPECTED_TABLE_DROP in [sql for sql, *_ in executed.statements]


def test_unreadable_materialized_view_catalog_does_not_drop_views_blindly() -> None:
    """Without the MV list, a materialized view cannot be told from a late-binding view."""
    provider = _FullProvider(failing=("svv_mv_info",))

    summary = provider.get_clean_preview("analytics")

    assert EXPECTED_LATE_BINDING_DROP not in summary.statements
    assert not any("MATERIALIZED" in statement for statement in summary.statements)

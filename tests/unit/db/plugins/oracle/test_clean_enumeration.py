"""Oracle clean droppable-object enumeration."""

from types import SimpleNamespace

from dblift.db.plugins.oracle.provider import OracleProvider
from dblift.db.provider_interfaces import DroppableObject


class DummyOracleProvider(OracleProvider):
    def __init__(self) -> None:
        self.calls = []
        self.config = SimpleNamespace(database=SimpleNamespace(type="oracle", username="SYSTEM"))
        self.log = SimpleNamespace(
            debug=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
        )

    def _ensure_connection(self):
        return None

    def execute_statement(self, sql, schema=None, params=None):
        self.calls.append(("statement", sql, schema, params))
        return 1


def test_list_droppable_objects_returns_oracle_clean_order_without_executing_drops() -> None:
    provider = DummyOracleProvider()

    def fake_query(sql, params=None):
        provider.calls.append(("query", sql, params))
        if "ALL_DB_LINKS" in sql:
            return [{"db_link": "REMOTE_DB"}]
        if "ALL_VIEWS" in sql:
            return [{"object_name": "APP_VIEW"}]
        if "SELECT MVIEW_NAME AS object_name FROM ALL_MVIEWS" in sql:
            return [{"object_name": "APP_MVIEW"}]
        if "ALL_TABLES" in sql:
            return [{"object_name": "APP_TABLE"}]
        if "ALL_SEQUENCES" in sql:
            return [{"object_name": "APP_SEQ"}, {"object_name": "ISEQ$$_42"}]
        if "ALL_TAB_IDENTITY_COLS" in sql and params == ["APP", "ISEQ$$_42"]:
            return [{"cnt": 1}]
        if "ALL_TAB_IDENTITY_COLS" in sql:
            return [{"cnt": 0}]
        if "ALL_OBJECTS" in sql:
            return [
                {"object_name": "APP_PKG", "object_type": "PACKAGE BODY"},
                {"object_name": "APP_TYPE", "object_type": "TYPE"},
                {"object_name": "APP_PROC", "object_type": "PROCEDURE"},
                {"object_name": "APP_TRG", "object_type": "TRIGGER"},
            ]
        if "ALL_SYNONYMS" in sql:
            return [{"object_name": "APP_SYNONYM"}]
        return []

    provider.execute_query = fake_query

    assert provider.list_droppable_objects("APP") == [
        DroppableObject(
            name="REMOTE_DB",
            object_type="database_link",
            drop_sql='DROP DATABASE LINK "REMOTE_DB"',
        ),
        DroppableObject(
            name="APP_VIEW",
            object_type="view",
            drop_sql='DROP VIEW "APP"."APP_VIEW"',
        ),
        DroppableObject(
            name="APP_MVIEW",
            object_type="materialized_view",
            drop_sql='DROP MATERIALIZED VIEW "APP"."APP_MVIEW"',
        ),
        DroppableObject(
            name="APP_TABLE",
            object_type="table",
            drop_sql='DROP TABLE "APP"."APP_TABLE" CASCADE CONSTRAINTS PURGE',
        ),
        DroppableObject(
            name="APP_SEQ",
            object_type="sequence",
            drop_sql='DROP SEQUENCE "APP"."APP_SEQ"',
        ),
        DroppableObject(
            name="APP_PKG",
            object_type="package_body",
            drop_sql='DROP PACKAGE BODY "APP"."APP_PKG"',
        ),
        DroppableObject(
            name="APP_TYPE",
            object_type="type",
            drop_sql='DROP TYPE "APP"."APP_TYPE" FORCE',
        ),
        DroppableObject(
            name="APP_PROC",
            object_type="procedure",
            drop_sql='DROP PROCEDURE "APP"."APP_PROC"',
        ),
        DroppableObject(
            name="APP_TRG",
            object_type="trigger",
            drop_sql='DROP TRIGGER "APP"."APP_TRG"',
        ),
        DroppableObject(
            name="APP_SYNONYM",
            object_type="synonym",
            drop_sql='DROP SYNONYM "APP"."APP_SYNONYM"',
        ),
    ]
    assert not any(call[0] == "statement" for call in provider.calls)

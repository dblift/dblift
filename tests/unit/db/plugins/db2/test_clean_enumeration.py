"""DB2 clean droppable-object enumeration."""

from types import SimpleNamespace

from db.plugins.db2.provider import Db2Provider


class DummyDb2Provider(Db2Provider):
    def __init__(self, rows_by_marker):
        self.calls = []
        self.rows_by_marker = rows_by_marker
        self.config = SimpleNamespace(database=SimpleNamespace(type="db2"))
        self.log = SimpleNamespace(
            debug=lambda *_args, **_kwargs: None,
            info=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
        )

    def _ensure_connection(self):
        return None

    def execute_query(self, sql, params=None):
        self.calls.append(("query", sql, params))
        for marker, rows in self.rows_by_marker.items():
            if marker in sql:
                if marker == "SYSCAT.SEQUENCES" and "SEQTYPE = 'S'" in sql:
                    return [
                        row
                        for row in rows
                        if row.get("SEQTYPE") == "S" and row.get("ORIGIN") == "U"
                    ]
                return rows
        return []

    def execute_statement(self, sql, schema=None, params=None):
        self.calls.append(("statement", sql, schema, params))
        return 1


def test_list_droppable_objects_matches_db2_clean_order_and_sql() -> None:
    provider = DummyDb2Provider(
        {
            "SYSCAT.TRIGGERS": [{"TRIGNAME": "ORDERS_AUDIT_TRG"}],
            "SYSCAT.TABCONST": [{"CONSTNAME": "FK_ORDER_CUSTOMER", "TABNAME": "ORDERS"}],
            "AND TYPE = 'V'": [{"TABNAME": "CUSTOMER_VIEW"}],
            "AND TYPE = 'S'": [{"TABNAME": "CUSTOMER_MQT"}],
            "AND TYPE = 'G'": [{"TABNAME": "SESSION_CACHE"}],
            "AND TYPE = 'T'": [{"TABNAME": "ORDERS"}, {"TABNAME": "DBLIFT_MIGRATION_LOCK"}],
            "AND TYPE = 'A'": [{"TABNAME": "CUSTOMER_ALIAS"}],
            "SYSCAT.SEQUENCES": [
                {"SEQNAME": "SQL260619043933830", "SEQTYPE": "I", "ORIGIN": "S"},
                {"SEQNAME": "ORDER_SEQ", "SEQTYPE": "S", "ORIGIN": "U"},
            ],
            "SYSCAT.FUNCTIONS": [{"FUNCNAME": "CALC_TOTAL", "SPECIFICNAME": "SQL260619043933831"}],
            "SYSCAT.PROCEDURES": [
                {"PROCNAME": "REFRESH_TOTALS", "SPECIFICNAME": "SQL260619043933832"}
            ],
            "SYSCAT.DATATYPES": [{"TYPENAME": "MONEY_TYPE"}],
            "SYSCAT.MODULES": [{"MODULENAME": "ORDER_MODULE"}],
            "SYSCAT.INDEXES": [{"INDNAME": "IX_ORDERS_CUSTOMER"}],
        }
    )

    objects = provider.list_droppable_objects("APP")

    assert [(obj.object_type, obj.name, obj.drop_sql) for obj in objects] == [
        ("trigger", "ORDERS_AUDIT_TRG", 'DROP TRIGGER "APP"."ORDERS_AUDIT_TRG"'),
        (
            "foreign_key",
            "FK_ORDER_CUSTOMER",
            'ALTER TABLE "APP"."ORDERS" DROP CONSTRAINT "FK_ORDER_CUSTOMER"',
        ),
        ("view", "CUSTOMER_VIEW", 'DROP VIEW "APP"."CUSTOMER_VIEW"'),
        ("materialized_query_table", "CUSTOMER_MQT", 'DROP TABLE "APP"."CUSTOMER_MQT"'),
        ("global_temporary_table", "SESSION_CACHE", 'DROP TABLE "APP"."SESSION_CACHE"'),
        ("table", "ORDERS", 'DROP TABLE "APP"."ORDERS"'),
        (
            "table",
            "DBLIFT_MIGRATION_LOCK",
            'DROP TABLE "APP"."DBLIFT_MIGRATION_LOCK"',
        ),
        ("alias", "CUSTOMER_ALIAS", 'DROP ALIAS "APP"."CUSTOMER_ALIAS"'),
        ("sequence", "ORDER_SEQ", 'DROP SEQUENCE "APP"."ORDER_SEQ"'),
        (
            "function",
            "CALC_TOTAL",
            'DROP SPECIFIC FUNCTION "APP"."SQL260619043933831"',
        ),
        (
            "procedure",
            "REFRESH_TOTALS",
            'DROP SPECIFIC PROCEDURE "APP"."SQL260619043933832"',
        ),
        ("type", "MONEY_TYPE", 'DROP TYPE "APP"."MONEY_TYPE"'),
        ("module", "ORDER_MODULE", 'DROP MODULE "APP"."ORDER_MODULE"'),
    ]
    assert all(call[0] != "statement" for call in provider.calls)
    assert {tuple(call[2]) for call in provider.calls if call[0] == "query"} == {("APP",)}


def test_list_droppable_objects_excludes_db2_identity_sequences() -> None:
    provider = DummyDb2Provider(
        {
            "SYSCAT.SEQUENCES": [
                {"SEQNAME": "SQL260619043933830", "SEQTYPE": "I", "ORIGIN": "S"},
                {"SEQNAME": "ORDER_SEQ", "SEQTYPE": "S", "ORIGIN": "U"},
            ],
        }
    )

    objects = provider.list_droppable_objects("APP")

    assert [(obj.object_type, obj.name, obj.drop_sql) for obj in objects] == [
        ("sequence", "ORDER_SEQ", 'DROP SEQUENCE "APP"."ORDER_SEQ"')
    ]

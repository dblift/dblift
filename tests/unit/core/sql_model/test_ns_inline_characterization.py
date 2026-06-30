"""Characterization tests for ADR-26 E story 26-5.

Pins byte-identical ``to_dict`` output, ``from_dict`` round-trips, ``__eq__``
discrimination, and ``create_statement`` / ``drop_statement`` rendering for the
six models whose per-dialect ``dialect_options`` indirection (``_NS_X``
namespace keys) is being inlined into plain instance attributes.

The dialect-neutral property names (``definer``, ``algorithm``, ``temp`` …)
and every serialized key must remain identical before and after the refactor.
"""

import pytest

from core.sql_model.event import Event
from core.sql_model.index import Index
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.trigger import Trigger
from core.sql_model.view import View

# ---------------------------------------------------------------------------
# Event (MySQL)
# ---------------------------------------------------------------------------


def _make_event() -> Event:
    return Event(
        name="cleanup_evt",
        schema="app",
        definition="DELETE FROM logs WHERE ts < NOW()",
        schedule="EVERY 1 DAY STARTS 2026-01-01 00:00:00",
        enabled=True,
        comment="nightly cleanup",
        definer="admin@localhost",
        event_type="RECURRING",
        dialect="mysql",
    )


def test_event_to_dict_pins_definer_as_top_level_key():
    assert _make_event().to_dict() == {
        "name": "cleanup_evt",
        "schema": "app",
        "object_type": "EVENT",
        "dialect": "mysql",
        "definition": "DELETE FROM logs WHERE ts < NOW()",
        "schedule": "EVERY 1 DAY STARTS 2026-01-01 00:00:00",
        "enabled": True,
        "comment": "nightly cleanup",
        "definer": "admin@localhost",
        "event_type": "RECURRING",
    }


def test_event_from_dict_round_trip():
    evt = _make_event()
    assert Event.from_dict(evt.to_dict()).to_dict() == evt.to_dict()


def test_event_definer_property_reads_back():
    evt = _make_event()
    assert evt.definer == "admin@localhost"
    evt.definer = "root@%"
    assert evt.definer == "root@%"
    assert evt.to_dict()["definer"] == "root@%"


def test_event_definer_default_none():
    evt = Event(name="e", dialect="mysql")
    assert evt.definer is None
    assert evt.to_dict()["definer"] is None


# ---------------------------------------------------------------------------
# Sequence (PostgreSQL)
# ---------------------------------------------------------------------------


def _make_sequence() -> Sequence:
    return Sequence(
        name="order_seq",
        schema="app",
        start_with=10,
        increment_by=2,
        min_value=1,
        max_value=999,
        cycle=True,
        cache=20,
        dialect="postgresql",
        temp=True,
        owned_by_table="orders",
        owned_by_column="id",
    )


def test_sequence_to_dict_pins_pg_keys():
    assert _make_sequence().to_dict() == {
        "name": "order_seq",
        "schema": "app",
        "object_type": "SEQUENCE",
        "dialect": "postgresql",
        "start_with": 10,
        "increment_by": 2,
        "min_value": 1,
        "max_value": 999,
        "cycle": True,
        "cache": 20,
        "temp": True,
        "owned_by_table": "orders",
        "owned_by_column": "id",
    }


def test_sequence_from_dict_round_trip():
    seq = _make_sequence()
    assert Sequence.from_dict(seq.to_dict()).to_dict() == seq.to_dict()


def test_sequence_temp_defaults_false():
    seq = Sequence(name="s", dialect="postgresql")
    assert seq.temp is False
    assert seq.owned_by_table is None
    assert seq.owned_by_column is None
    d = seq.to_dict()
    assert d["temp"] is False
    assert d["owned_by_table"] is None
    assert d["owned_by_column"] is None


def test_sequence_create_statement_temp_no_dialect():
    # No registered dialect -> quirks DDL path; temp keyword gated on quirks.
    seq = Sequence(name="s", schema="app", temp=True, start_with=5)
    stmt = seq.create_statement
    assert "CREATE" in stmt and "SEQUENCE" in stmt
    assert "START WITH 5" in stmt


def test_sequence_drop_statement_renders():
    seq = _make_sequence()
    drop = seq.drop_statement
    assert "DROP SEQUENCE" in drop
    assert "order_seq" in drop


# ---------------------------------------------------------------------------
# Trigger (MySQL)
# ---------------------------------------------------------------------------


def _make_trigger() -> Trigger:
    return Trigger(
        name="audit_trg",
        table_name="orders",
        schema="app",
        timing="AFTER",
        events=["INSERT", "UPDATE"],
        orientation="ROW",
        definition="BEGIN INSERT INTO audit VALUES (NEW.id); END",
        enabled=True,
        dialect="mysql",
        definer="admin@localhost",
        execution_order=5,
        follows_trigger="other_trg",
        precedes_trigger="next_trg",
    )


def test_trigger_to_dict_pins_keys():
    assert _make_trigger().to_dict() == {
        "name": "audit_trg",
        "table_name": "orders",
        "schema": "app",
        "object_type": "TRIGGER",
        "dialect": "mysql",
        "timing": "AFTER",
        "events": ["INSERT", "UPDATE"],
        "orientation": "ROW",
        "definition": "BEGIN INSERT INTO audit VALUES (NEW.id); END",
        "enabled": True,
        "function_schema": None,
        "function_name": None,
        "function_arguments": None,
        "when_clause": None,
        "is_constraint_trigger": False,
        "constraint_deferrable": None,
        "constraint_initially_deferred": None,
        "definer": "admin@localhost",
        "execution_order": 5,
        "follows_trigger": "other_trg",
        "precedes_trigger": "next_trg",
    }


def test_trigger_from_dict_round_trip():
    trg = _make_trigger()
    assert Trigger.from_dict(trg.to_dict()).to_dict() == trg.to_dict()


def test_trigger_eq_discriminates_on_definer():
    a = _make_trigger()
    b = _make_trigger()
    assert a == b
    b.definer = "different@host"
    assert a != b


def test_trigger_execution_order_int():
    trg = _make_trigger()
    assert trg.execution_order == 5
    assert isinstance(trg.execution_order, int)


def test_trigger_defaults_none():
    trg = Trigger(name="t", table_name="tbl", dialect="mysql")
    assert trg.definer is None
    assert trg.execution_order is None
    assert trg.follows_trigger is None
    assert trg.precedes_trigger is None


# ---------------------------------------------------------------------------
# Procedure (MySQL + PostgreSQL)
# ---------------------------------------------------------------------------


def _make_procedure() -> Procedure:
    return Procedure(
        name="do_thing",
        schema="app",
        body="SELECT 1;",
        language="SQL",
        dialect="mysql",
        comment="a proc",
        volatility="STABLE",
        security_definer=True,
        definer="admin@localhost",
        data_access="READS SQL DATA",
    )


def test_procedure_to_dict_pins_keys():
    assert _make_procedure().to_dict() == {
        "name": "do_thing",
        "schema": "app",
        "object_type": "PROCEDURE",
        "dialect": "mysql",
        "parameters": [],
        "body": "SELECT 1;",
        "language": "SQL",
        "is_function": False,
        "return_type": None,
        "comment": "a proc",
        "definition": None,
        "volatility": "STABLE",
        "security_definer": True,
        "definer": "admin@localhost",
        "data_access": "READS SQL DATA",
    }


def test_procedure_from_dict_round_trip():
    proc = _make_procedure()
    assert Procedure.from_dict(proc.to_dict()).to_dict() == proc.to_dict()


def test_procedure_security_definer_and_definer_reads():
    proc = _make_procedure()
    assert proc.security_definer is True
    assert proc.definer == "admin@localhost"
    assert proc.data_access == "READS SQL DATA"


def test_procedure_defaults_none():
    proc = Procedure(name="p", dialect="postgresql")
    assert proc.security_definer is None
    assert proc.definer is None
    assert proc.data_access is None


def test_procedure_drop_statement_renders():
    proc = _make_procedure()
    drop = proc.drop_statement
    assert "DROP PROCEDURE" in drop
    assert "do_thing" in drop


# ---------------------------------------------------------------------------
# Index (MySQL + PostgreSQL + Oracle)
# ---------------------------------------------------------------------------


def _make_index() -> Index:
    return Index(
        name="idx_orders",
        table_name="orders",
        columns=["a", "b"],
        schema="app",
        unique=True,
        type="BTREE",
        dialect="oracle",
        online=True,
        concurrently=True,
        tablespace="users_ts",
        is_local=True,
    )


def test_index_to_dict_pins_keys():
    assert _make_index().to_dict() == {
        "name": "idx_orders",
        "schema": "app",
        "object_type": "INDEX",
        "dialect": "oracle",
        "table_name": "orders",
        "table_schema": "app",
        "columns": ["a", "b"],
        "unique": True,
        "type": "BTREE",
        "condition": None,
        "include_columns": [],
        "sort_directions": [],
        "online": True,
        "concurrently": True,
        "tablespace": "users_ts",
        "is_local": True,
        "expression_flags": [False, False],
        "fillfactor": None,
        "compression": None,
        "comment": None,
    }


def test_index_from_dict_round_trip():
    idx = _make_index()
    assert Index.from_dict(idx.to_dict()).to_dict() == idx.to_dict()


def test_index_concurrently_defaults_false():
    idx = Index(name="i", table_name="t", columns=["c"], dialect="postgresql")
    assert idx.concurrently is False
    assert idx.online is None
    assert idx.tablespace is None
    assert idx.is_local is None
    d = idx.to_dict()
    assert d["concurrently"] is False
    assert d["online"] is None
    assert d["tablespace"] is None
    assert d["is_local"] is None


def test_index_drop_statement_renders():
    idx = _make_index()
    drop = idx.drop_statement
    assert "DROP INDEX" in drop
    assert "idx_orders" in drop


# ---------------------------------------------------------------------------
# View (MySQL + PostgreSQL + Oracle)
# ---------------------------------------------------------------------------


def _make_view() -> View:
    return View(
        name="active_orders",
        schema="app",
        query="SELECT * FROM orders WHERE active",
        columns=["id", "total"],
        materialized=False,
        dialect="mysql",
        is_updatable=True,
        check_option="CASCADED",
        unlogged=True,
        algorithm="MERGE",
        sql_security="DEFINER",
        definer="admin@localhost",
        force=True,
        security_definer=True,
        security_invoker=False,
    )


def test_view_to_dict_pins_conditional_keys():
    assert _make_view().to_dict() == {
        "name": "active_orders",
        "schema": "app",
        "object_type": "VIEW",
        "dialect": "mysql",
        "query": "SELECT * FROM orders WHERE active",
        "columns": ["id", "total"],
        "materialized": False,
        "is_updatable": True,
        "check_option": "CASCADED",
        "security_definer": True,
        "security_invoker": False,
        "algorithm": "MERGE",
        "sql_security": "DEFINER",
        "definer": "admin@localhost",
        "force": True,
        "unlogged": True,
    }


def test_view_to_dict_omits_unset_keys():
    view = View(name="v", schema="s", query="SELECT 1", dialect="mysql")
    d = view.to_dict()
    # Conditional keys absent when unset/falsey (matches existing to_dict logic).
    assert "algorithm" not in d
    assert "sql_security" not in d
    assert "definer" not in d
    assert "force" not in d
    assert "unlogged" not in d
    assert "security_definer" not in d
    assert "security_invoker" not in d


def test_view_from_dict_round_trip():
    view = _make_view()
    assert View.from_dict(view.to_dict()).to_dict() == view.to_dict()


def test_view_eq_discriminates_on_dialect_options():
    a = _make_view()
    b = _make_view()
    assert a == b
    b.algorithm = "TEMPTABLE"
    assert a != b
    b.algorithm = "MERGE"
    assert a == b
    b.force = False
    assert a != b


def test_view_to_options_round_trip():
    view = _make_view()
    opts = view.to_options()
    assert opts.mysql.algorithm == "MERGE"
    assert opts.mysql.sql_security == "DEFINER"
    assert opts.mysql.definer == "admin@localhost"
    assert opts.oracle.force is True
    assert opts.postgres.unlogged is True
    assert opts.postgres.security_definer is True
    assert opts.postgres.security_invoker is False


def test_view_defaults_none():
    view = View(name="v", dialect="mysql")
    assert view.algorithm is None
    assert view.sql_security is None
    assert view.definer is None
    assert view.force is None
    assert view.unlogged is None
    assert view.security_definer is None
    assert view.security_invoker is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

"""Contract for distinct trigger and subject-table namespaces."""

import json

from dblift.core.sql_model.trigger import Trigger


def test_trigger_keeps_object_and_subject_owners_separate():
    trigger = Trigger("orders_changed", "orders", schema="audit", table_schema="data")

    assert trigger.schema == "audit"
    assert trigger.name == "orders_changed"
    assert trigger.table_schema == "data"
    assert trigger.qualified_table_name == "data.orders"


def test_trigger_can_have_an_unqualified_object_and_qualified_subject():
    trigger = Trigger("orders_changed", "orders", table_schema="data")

    assert trigger.schema is None
    assert trigger.name == "orders_changed"
    assert trigger.qualified_table_name == "data.orders"


def test_subject_qualification_and_object_identifiers_use_existing_escaping():
    trigger = Trigger(
        'change"name',
        'order"items',
        schema='audit"x',
        table_schema='data"y',
        dialect="postgresql",
    )

    assert trigger.format_identifier(trigger.schema) == '"audit""x"'
    assert trigger.format_identifier(trigger.name) == '"change""name"'
    assert trigger.qualified_table_name == '"data""y"."order""items"'


def test_subject_owner_participates_in_trigger_equality():
    left = Trigger("orders_changed", "orders", schema="audit", table_schema="data_a")
    right = Trigger("orders_changed", "orders", schema="audit", table_schema="data_b")
    same = Trigger("orders_changed", "orders", schema="audit", table_schema="data_a")

    assert left != right
    assert left == same


def test_trigger_dict_and_json_round_trip_keep_both_owners():
    original = Trigger("orders_changed", "orders", schema="audit", table_schema="data")

    payload = original.to_dict()
    assert payload["schema"] == "audit"
    assert payload["table_schema"] == "data"

    restored = Trigger.from_dict(json.loads(json.dumps(payload)))
    assert restored.schema == "audit"
    assert restored.name == "orders_changed"
    assert restored.table_schema == "data"
    assert restored.qualified_table_name == "data.orders"
    assert restored.to_dict() == payload


def test_legacy_positional_constructor_keeps_existing_argument_order():
    trigger = Trigger(
        "orders_changed",
        "orders",
        "audit",
        "AFTER",
        ["UPDATE"],
        "ROW",
        "BEGIN END",
        False,
        "postgresql",
        "functions",
        "log_change",
        "",
        "NEW.id IS NOT NULL",
        True,
        True,
        False,
        "writer@localhost",
        2,
        "previous_trigger",
        "next_trigger",
    )

    assert trigger.name == "orders_changed"
    assert trigger.schema == "audit"
    assert trigger.table_schema == "audit"
    assert trigger.timing == "AFTER"
    assert trigger.events == ["UPDATE"]
    assert trigger.orientation == "ROW"
    assert trigger.definition == "BEGIN END"
    assert trigger.enabled is False
    assert trigger.dialect == "postgresql"
    assert trigger.function_schema == "functions"
    assert trigger.function_name == "log_change"
    assert trigger.function_arguments == ""
    assert trigger.when_clause == "NEW.id IS NOT NULL"
    assert trigger.is_constraint_trigger is True
    assert trigger.constraint_deferrable is True
    assert trigger.constraint_initially_deferred is False
    assert trigger.definer == "writer@localhost"
    assert trigger.execution_order == 2
    assert trigger.follows_trigger == "previous_trigger"
    assert trigger.precedes_trigger == "next_trigger"


def test_legacy_dict_without_subject_owner_uses_historical_schema():
    trigger = Trigger.from_dict(
        {"name": "orders_changed", "table_name": "orders", "schema": "audit"}
    )

    assert trigger.schema == "audit"
    assert trigger.name == "orders_changed"
    assert trigger.table_schema == "audit"
    assert trigger.qualified_table_name == "audit.orders"


def test_explicit_null_subject_owner_survives_dictionary_round_trip():
    payload = {
        "name": "orders_changed",
        "table_name": "orders",
        "schema": "audit",
        "table_schema": None,
    }
    trigger = Trigger.from_dict(payload)

    assert trigger.schema == "audit"
    assert trigger.table_schema is None
    assert trigger.qualified_table_name == "orders"
    restored = Trigger.from_dict(json.loads(json.dumps(trigger.to_dict())))
    assert restored.table_schema is None
    assert restored.qualified_table_name == "orders"


def test_constructor_none_keeps_legacy_same_owner_default():
    trigger = Trigger("orders_changed", "orders", schema="audit", table_schema=None)

    assert trigger.table_schema == "audit"
    assert trigger.qualified_table_name == "audit.orders"

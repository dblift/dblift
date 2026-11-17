"""A pre-existing Trigger extension inherits the public dictionary codec."""

from dblift.core.sql_model.trigger import Trigger


def _legacy_subclass(base):
    class ExistingTriggerExtension(base):
        def __init__(
            self,
            name,
            table_name,
            schema=None,
            timing=None,
            events=None,
            orientation=None,
            definition=None,
            enabled=True,
            dialect=None,
            function_schema=None,
            function_name=None,
            function_arguments=None,
            when_clause=None,
            is_constraint_trigger=None,
            constraint_deferrable=None,
            constraint_initially_deferred=None,
            definer=None,
            execution_order=None,
            follows_trigger=None,
            precedes_trigger=None,
        ):
            super().__init__(
                name,
                table_name,
                schema,
                timing,
                events,
                orientation,
                definition,
                enabled,
                dialect,
                function_schema,
                function_name,
                function_arguments,
                when_clause,
                is_constraint_trigger,
                constraint_deferrable,
                constraint_initially_deferred,
                definer,
                execution_order,
                follows_trigger,
                precedes_trigger,
            )

    return ExistingTriggerExtension


def test_existing_trigger_subclass_keeps_inherited_legacy_dictionary_codec():
    extension = _legacy_subclass(Trigger)
    restored = extension.from_dict(
        {
            "name": "orders_changed",
            "table_name": "orders",
            "schema": "audit",
            "timing": "AFTER",
            "events": ["UPDATE"],
        }
    )

    assert type(restored) is extension
    assert restored.schema == "audit"
    assert restored.table_name == "orders"
    assert restored.timing == "AFTER"
    assert restored.events == ["UPDATE"]
    assert restored.qualified_table_name == "audit.orders"


def test_existing_trigger_subclass_direct_construction_control():
    extension = _legacy_subclass(Trigger)
    trigger = extension("orders_changed", "orders", schema="audit")

    assert trigger.schema == "audit"
    assert trigger.qualified_table_name == "audit.orders"

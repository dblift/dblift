from dblift.core.sql_model.trigger import Trigger


class TestTriggerSqlModel:
    def test_trigger_serialization_round_trip_preserves_metadata(self):
        trigger = Trigger(
            name="audit_users_change",
            table_name="users",
            schema="public",
            timing="AFTER",
            events=["INSERT", "UPDATE"],
            orientation="ROW",
            definition="EXECUTE FUNCTION public.audit_user_change()",
            enabled=True,
            dialect="postgresql",
            function_schema="public",
            function_name="audit_user_change",
            function_arguments="integer, text",
            when_clause="OLD.updated_at IS DISTINCT FROM NEW.updated_at",
            is_constraint_trigger=True,
            constraint_deferrable=True,
            constraint_initially_deferred=False,
        )

        serialized = trigger.to_dict()
        assert serialized["function_schema"] == "public"
        assert serialized["function_name"] == "audit_user_change"
        assert serialized["function_arguments"] == "integer, text"
        assert serialized["when_clause"] == "OLD.updated_at IS DISTINCT FROM NEW.updated_at"
        assert serialized["is_constraint_trigger"] is True
        assert serialized["constraint_deferrable"] is True
        assert serialized["constraint_initially_deferred"] is False

        restored = Trigger.from_dict(serialized)
        assert restored == trigger
        assert restored.function_schema == "public"
        assert restored.function_name == "audit_user_change"
        assert restored.function_arguments == "integer, text"
        assert restored.when_clause == "OLD.updated_at IS DISTINCT FROM NEW.updated_at"
        assert restored.is_constraint_trigger is True
        assert restored.constraint_deferrable is True
        assert restored.constraint_initially_deferred is False

"""Regression test: dry-run must fall back to SchemaIntrospector when a
provider's ``get_clean_preview`` raises at runtime.

Guards against the cursor-bot finding where a failing ``get_clean_preview``
was caught and logged at debug level, but the ``else`` branch containing the
introspector fallback was never reached. The user saw
``"(schema appears empty or objects could not be enumerated)"`` instead of a
best-effort listing, making the dry-run output silently misleading.
"""

from unittest.mock import MagicMock

import pytest

from core.migration.clean_summary import CleanedObjectInfo, CleanExecutionSummary
from core.migration.commands.clean_command import CleanCommand


def _make_command(provider):
    config = MagicMock()
    config.database.schema = "myschema"
    log = MagicMock()
    cmd = CleanCommand(
        config=config,
        log=log,
        provider=provider,
        script_manager=MagicMock(),
        history_manager=MagicMock(),
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )
    return cmd, log


@pytest.mark.unit
class TestCleanCommandDryRunIntrospectorFallback:
    """When the provider's ``get_clean_preview`` raises, the introspector path must run."""

    def test_preview_raising_triggers_introspector_fallback(self, monkeypatch):
        """get_clean_preview raises → SchemaIntrospector is instantiated and queried."""
        provider = MagicMock()
        provider.get_clean_preview.side_effect = RuntimeError("preview boom")
        cmd, log = _make_command(provider)

        # Mock the SchemaIntrospector class that CleanCommand imports inline.
        introspector_instance = MagicMock()
        introspector_instance.get_tables.return_value = [MagicMock(name="tbl_a")]
        introspector_instance.get_tables.return_value[0].name = "tbl_a"
        introspector_instance.get_views.return_value = []
        introspector_instance.get_sequences.return_value = []
        introspector_instance.get_functions.return_value = []
        introspector_instance.get_triggers.return_value = []
        udt = MagicMock()
        udt.name = "EmailType"
        introspector_instance.get_user_defined_types.return_value = [udt]

        introspector_cls = MagicMock(return_value=introspector_instance)
        monkeypatch.setattr(
            "core.introspection.schema_introspector.SchemaIntrospector",
            introspector_cls,
        )

        result = cmd.execute(dry_run=True)

        assert result.success is True
        # Fallback was actually reached — the introspector was instantiated and queried.
        introspector_cls.assert_called_once()
        introspector_instance.get_tables.assert_called_once_with("myschema")

        # User saw at least one "Would drop" line from the fallback, not the
        # misleading "schema appears empty" message.
        info_calls = [str(c) for c in log.info.call_args_list]
        assert any("Would drop table: tbl_a" in c for c in info_calls), info_calls
        assert any("Would drop type: EmailType" in c for c in info_calls), info_calls
        assert not any("schema appears empty" in c for c in info_calls), info_calls
        introspector_instance.get_user_defined_types.assert_called_once_with("myschema")

    def test_preview_success_skips_introspector(self, monkeypatch):
        """get_clean_preview succeeds → introspector is NOT touched (preferred path)."""
        provider = MagicMock()
        preview = MagicMock()
        obj = MagicMock()
        obj.object_type = "table"
        obj.name = "preview_tbl"
        preview.objects = [obj]
        provider.get_clean_preview.return_value = preview
        cmd, log = _make_command(provider)

        introspector_cls = MagicMock()
        monkeypatch.setattr(
            "core.introspection.schema_introspector.SchemaIntrospector",
            introspector_cls,
        )

        result = cmd.execute(dry_run=True)

        assert result.success is True
        introspector_cls.assert_not_called()

        info_calls = [str(c) for c in log.info.call_args_list]
        assert any("Would drop table: preview_tbl" in c for c in info_calls), info_calls

    def test_provider_preview_does_not_log_fallback_triggers(self, monkeypatch):
        """Provider preview output is authoritative for dry-run object logging."""
        provider = MagicMock()
        provider.get_clean_preview.return_value = CleanExecutionSummary(
            objects=[CleanedObjectInfo(object_type="table", name="employees", schema="myschema")]
        )
        cmd, log = _make_command(provider)

        introspector_cls = MagicMock()
        monkeypatch.setattr(
            "core.introspection.schema_introspector.SchemaIntrospector",
            introspector_cls,
        )

        result = cmd.execute(dry_run=True)

        assert result.success is True
        introspector_cls.assert_not_called()

        info_calls = [str(c) for c in log.info.call_args_list]
        assert any("Would drop table: employees" in c for c in info_calls), info_calls
        assert not any("Would drop trigger" in c for c in info_calls), info_calls

    def test_no_preview_method_uses_introspector(self, monkeypatch):
        """Provider without get_clean_preview → introspector path runs (pre-existing behaviour)."""
        provider = MagicMock(spec=[])  # no get_clean_preview attribute
        # _ensure_connected() checks for _ensure_connection; add it so the
        # connection step succeeds and doesn't raise in dry-run mode.
        provider._ensure_connection = MagicMock()
        cmd, log = _make_command(provider)

        introspector_instance = MagicMock()
        introspector_instance.get_tables.return_value = []
        introspector_instance.get_views.return_value = []
        introspector_instance.get_sequences.return_value = []
        introspector_instance.get_functions.return_value = []
        introspector_instance.get_triggers.return_value = []
        introspector_instance.get_user_defined_types.return_value = []

        introspector_cls = MagicMock(return_value=introspector_instance)
        monkeypatch.setattr(
            "core.introspection.schema_introspector.SchemaIntrospector",
            introspector_cls,
        )

        result = cmd.execute(dry_run=True)

        assert result.success is True
        introspector_cls.assert_called_once()

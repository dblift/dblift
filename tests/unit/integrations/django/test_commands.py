"""Django management commands + system check, per-test settings via override."""

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

pytestmark = pytest.mark.filterwarnings("ignore:Overriding setting DATABASES:UserWarning")


def _settings(tmp_path: Path) -> dict:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1_0_0__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    return {
        "DATABASES": {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": str(tmp_path / "db.sqlite"),
            }
        },
        "DBLIFT_MIGRATIONS_DIR": str(migrations),
    }


def _memory_settings(tmp_path: Path) -> dict:
    settings = _settings(tmp_path)
    settings["DATABASES"]["default"]["NAME"] = ":memory:"
    return settings


def test_migrate_command_applies(tmp_path):
    with override_settings(**_settings(tmp_path)):
        call_command("dblift_migrate")
        from dblift.integrations.django.checks import pending_migrations_check

        assert pending_migrations_check(None) == []


def test_migrate_command_applies_in_memory_sqlite(tmp_path):
    with override_settings(**_memory_settings(tmp_path)):
        call_command("dblift_migrate")
        from dblift.integrations.django.checks import pending_migrations_check

        assert pending_migrations_check(None) == []


def test_check_reports_pending_before_migrate(tmp_path):
    with override_settings(**_settings(tmp_path)):
        from dblift.integrations.django.checks import pending_migrations_check

        messages = pending_migrations_check(None)
        assert messages and messages[0].id == "dblift.W001"


def test_check_reports_failure_instead_of_staying_silent(tmp_path, monkeypatch):
    """A broken configuration must not be reported as "no pending migrations".

    The check used to swallow every exception and return ``[]``, so a bad
    connection or a missing migrations directory rendered as a clean bill of
    health — the one outcome an operator must not be given falsely.
    """
    with override_settings(**_settings(tmp_path)):
        import dblift.integrations.django._client as client_module
        from dblift.integrations.django.checks import pending_migrations_check

        def _boom():
            raise RuntimeError("could not connect")

        monkeypatch.setattr(client_module, "get_client", _boom)

        messages = pending_migrations_check(None)

        assert messages, "a failed check must report something"
        assert messages[0].id == "dblift.W002"
        assert "could not connect" in str(messages[0].msg)


def test_check_masks_credentials_in_the_failure_message(tmp_path, monkeypatch):
    """A driver error often echoes the DSN back, credentials included."""
    with override_settings(**_settings(tmp_path)):
        import dblift.integrations.django._client as client_module
        from dblift.integrations.django.checks import pending_migrations_check

        def _boom():
            raise RuntimeError("could not connect to postgresql://admin:secret123@h/db")

        monkeypatch.setattr(client_module, "get_client", _boom)

        messages = pending_migrations_check(None)

        assert messages and "secret123" not in str(messages[0].msg)


def test_info_command_runs(tmp_path):
    with override_settings(**_settings(tmp_path)):
        call_command("dblift_info")


def _info_result(*migrations):
    from dblift.core.logger.results import InfoResult, MigrationInfo

    result = InfoResult()
    for script, version, status in migrations:
        result.add_migration(MigrationInfo(script, version=version, status=status))
    return result


def _run_info_with_result(tmp_path, monkeypatch, info):
    with override_settings(**_settings(tmp_path)):
        from dblift.integrations.django.management.commands import dblift_info as info_cmd

        class _Client:
            def info(self):
                return info

            def close(self):
                pass

        monkeypatch.setattr(info_cmd, "get_client", lambda: _Client())
        out = StringIO()
        call_command("dblift_info", stdout=out)
        return out.getvalue()


def test_info_command_clean_history_shows_zero_pending_and_failed(tmp_path, monkeypatch):
    text = _run_info_with_result(
        tmp_path,
        monkeypatch,
        _info_result(("V1__ok.sql", "1", "SUCCESS")),
    )
    assert "0 pending" in text
    assert "0 failed" in text


def test_info_command_pending_only_does_not_imply_failure(tmp_path, monkeypatch):
    text = _run_info_with_result(
        tmp_path,
        monkeypatch,
        _info_result(("V1__next.sql", "1", "PENDING")),
    )
    assert "1 pending" in text
    assert "V1__next.sql" in text
    assert "0 failed" in text


def test_info_command_failed_only_is_visible_with_zero_pending(tmp_path, monkeypatch):
    text = _run_info_with_result(
        tmp_path,
        monkeypatch,
        _info_result(("V1__ok.sql", "1", "SUCCESS"), ("V2__bad.sql", "2", "FAILED")),
    )
    assert "0 pending" in text
    assert "1 failed" in text
    assert "V2__bad.sql" in text


def test_info_command_failed_and_pending_are_both_listed(tmp_path, monkeypatch):
    text = _run_info_with_result(
        tmp_path,
        monkeypatch,
        _info_result(("V2__bad.sql", "2", "FAILED"), ("V3__next.sql", "3", "PENDING")),
    )
    assert "1 pending" in text
    assert "1 failed" in text
    assert "V2__bad.sql" in text
    assert "V3__next.sql" in text


def test_info_command_surfaces_failed_history_after_bad_migrate(tmp_path):
    """Customer path: failed V2 is attempted (0 pending) but must not look clean."""
    settings = _settings(tmp_path)
    migrations = Path(settings["DBLIFT_MIGRATIONS_DIR"])
    (migrations / "V2_0_0__bad.sql").write_text("CREATE TABLE typo_oops (")

    with override_settings(**settings):
        with pytest.raises(CommandError):
            call_command("dblift_migrate")
        out = StringIO()
        call_command("dblift_info", stdout=out)
        text = out.getvalue()
        assert "0 pending" in text
        assert "failed" in text.lower()
        assert "V2_0_0__bad.sql" in text or "1 failed" in text


def test_dblift_commands_skip_system_checks():
    from dblift.integrations.django.management.commands.dblift_info import Command as InfoCommand
    from dblift.integrations.django.management.commands.dblift_migrate import (
        Command as MigrateCommand,
    )
    from dblift.integrations.django.management.commands.dblift_validate import (
        Command as ValidateCommand,
    )

    assert MigrateCommand.requires_system_checks == []
    assert ValidateCommand.requires_system_checks == []
    assert InfoCommand.requires_system_checks == []


def test_get_client_reuses_engine_for_same_settings(tmp_path):
    with override_settings(**_settings(tmp_path)):
        from dblift.integrations.django._client import get_client

        first = get_client()
        second = get_client()
        try:
            assert first.provider._external_engine is second.provider._external_engine
        finally:
            first.close()
            second.close()

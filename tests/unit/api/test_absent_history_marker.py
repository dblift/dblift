"""``info`` and ``migrate --dry-run`` say so when the schema-history table does not exist.

Without a marker, a role that can read but not create saw every migration Pending and
no schema version, with no hint that nothing was ever applied here.
"""

import pytest

from dblift.api import DBLiftClient
from dblift.cli.handlers.info import _info_result_to_dict
from dblift.cli.handlers.migrate import _migrate_result_to_dict
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog
from dblift.core.logger.results import InfoResult, MigrateResult

pytestmark = pytest.mark.unit


class _Recorder(NullLog):
    def __init__(self):
        self.warnings = []

    def warning(self, message, *, dedupe=True):
        self.warnings.append(message)


@pytest.fixture
def client_factory(tmp_path):
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    (scripts / "V1__create_items.sql").write_text("CREATE TABLE items (id INTEGER);")
    clients = []

    def make(logger=None, directory=scripts):
        config = DbliftConfig.from_dict(
            {
                "database": {"type": "sqlite", "url": f"sqlite:///{tmp_path / 'db.sqlite'}"},
                "migrations": {"directory": str(directory)},
            }
        )
        client = DBLiftClient.from_config(config, logger=logger or NullLog())
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


def test_info_flags_a_missing_history_table(client_factory):
    log = _Recorder()
    result = client_factory(log).info()

    assert result.success, result.error_message
    assert result.history_table_exists is False
    assert [m.status for m in result.migrations] == ["PENDING"]
    assert any("dblift_schema_history" in w and "does not exist yet" in w for w in log.warnings)


def test_dry_run_flags_a_missing_history_table(client_factory):
    log = _Recorder()
    result = client_factory(log).migrate(dry_run=True)

    assert result.success, result.error_message
    assert result.history_table_exists is False
    assert result.dry_run_count == 1
    assert any("dblift_schema_history" in w and "does not exist yet" in w for w in log.warnings)


def test_dry_run_with_nothing_pending_still_flags_a_missing_history_table(client_factory, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    log = _Recorder()
    result = client_factory(log, directory=empty).migrate(dry_run=True)

    assert result.success, result.error_message
    assert result.history_table_exists is False
    assert result.dry_run_count == 0
    [warning] = log.warnings
    assert "does not exist yet" in warning
    assert "pending" not in warning


def test_dry_run_flags_a_missing_history_table_when_a_filter_leaves_nothing(client_factory):
    log = _Recorder()
    result = client_factory(log).migrate(dry_run=True, versions=["99"])

    assert result.success, result.error_message
    assert result.history_table_exists is False
    assert any("does not exist yet" in w for w in log.warnings)


def test_dry_run_with_pending_scripts_keeps_the_effect_sentence(client_factory):
    log = _Recorder()
    client_factory(log).migrate(dry_run=True)

    [warning] = log.warnings
    assert "every migration is listed as pending" in warning


def test_dry_run_with_a_history_table_and_nothing_pending_is_not_flagged(client_factory):
    assert client_factory().migrate().success
    log = _Recorder()
    result = client_factory(log).migrate(dry_run=True)

    assert result.history_table_exists is True
    assert result.dry_run_count == 0
    assert not log.warnings


def test_a_dialect_that_cannot_tell_missing_from_unreadable_says_so(client_factory, monkeypatch):
    """Oracle answers ORA-00942 for both, so the text must not claim the table is missing."""
    log = _Recorder()
    client = client_factory(log)
    monkeypatch.setattr(
        client.provider.quirks, "unreadable_table_looks_missing", True, raising=False
    )

    client.info()

    assert any("does not exist or cannot be read by this account" in w for w in log.warnings)


def test_oracle_cannot_tell_missing_from_unreadable():
    from dblift.db.plugins.oracle.quirks import OracleQuirks

    assert OracleQuirks.unreadable_table_looks_missing is True


def test_a_history_table_with_rows_is_not_flagged(client_factory):
    client = client_factory()
    assert client.migrate().success
    log = _Recorder()
    info = client_factory(log).info()

    assert info.history_table_exists is True
    assert not log.warnings


def test_an_empty_history_table_is_not_flagged(client_factory, tmp_path):
    """The table exists but no migration was applied: not the same as a missing table."""
    empty = tmp_path / "empty"
    empty.mkdir()
    assert client_factory(directory=empty).migrate().success
    log = _Recorder()
    info = client_factory(log).info()

    assert info.history_table_exists is True
    assert not any("does not exist" in w for w in log.warnings)


def test_json_payloads_carry_the_marker(client_factory):
    client = client_factory()
    info, dry_run = client.info(), client.migrate(dry_run=True)

    assert _info_result_to_dict(info)["history_table_exists"] is False
    assert _migrate_result_to_dict(dry_run, True)["history_table_exists"] is False


def test_results_default_to_an_existing_history_table():
    assert InfoResult().history_table_exists is True
    assert MigrateResult().history_table_exists is True

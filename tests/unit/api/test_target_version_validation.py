"""The Python API refuses a ``target_version`` that no migration script carries."""

from __future__ import annotations

import pytest

from dblift.api.client import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.exceptions import InvalidTargetVersionError

pytestmark = [pytest.mark.unit]


@pytest.fixture
def client(tmp_path):
    scripts = tmp_path / "m"
    scripts.mkdir()
    for version in (1, 2, 3):
        (scripts / f"V{version}__t.sql").write_text(f"CREATE TABLE t{version} (id INTEGER);\n")
        (scripts / f"U{version}__t.sql").write_text(f"DROP TABLE t{version};\n")
    config = DbliftConfig.from_dict(
        {
            "database": {"url": f"sqlite:///{tmp_path / 'tv.db'}", "type": "sqlite"},
            "migrations": {"directory": str(scripts)},
        }
    )
    return DBLiftClient.from_config(config)


def _applied(client):
    return [str(r.version) for r in client.executor.history_manager.get_applied_migration_records()]


@pytest.mark.parametrize("bad", ["v1", "V1", "abc", "", "99", "-1", "1a", "1.5", "0"])
@pytest.mark.parametrize("method", ["migrate", "validate", "info"])
def test_bad_target_version_raises_typed_error(client, tmp_path, method, bad):
    with pytest.raises(InvalidTargetVersionError) as raised:
        getattr(client, method)(target_version=bad)
    assert raised.value.available_versions == ["1", "2", "3"]
    assert "Available versions: 1, 2, 3" in str(raised.value)
    assert not (tmp_path / "tv.db").exists()


@pytest.mark.parametrize("bad", ["v1", "abc", "", "99"])
def test_bad_undo_target_version_raises_typed_error(client, tmp_path, bad):
    with pytest.raises(InvalidTargetVersionError):
        client.undo(target_version=bad)
    assert not (tmp_path / "tv.db").exists()


def test_error_is_a_value_error(client):
    with pytest.raises(ValueError):
        client.migrate(target_version="abc")


@pytest.mark.parametrize("good,expected", [("1", ["1"]), ("2", ["1", "2"]), ("2.0.0", ["1", "2"])])
def test_valid_target_version_applies_up_to_it(client, good, expected):
    assert client.migrate(target_version=good).success
    assert _applied(client) == expected


def test_target_at_or_below_head_applies_nothing(client):
    assert client.migrate().success
    result = client.migrate(target_version="2")
    assert result.success
    assert _applied(client) == ["1", "2", "3"]


def test_undo_accepts_zero_and_known_versions(client):
    client.migrate()
    assert client.undo(target_version="2").success
    assert client.undo(target_version="0").success

"""An unrecognized key under ``database:`` is a typo waiting to be silent.

``_instantiate_config`` filters the config dict down to the dataclass's fields
and drops the rest with no signal, so a near-miss of a real field (``srvice``
for ``service_name``, ``databse`` for ``database``) is ignored and the value
silently falls back to a default. It must still not raise (a genuine
driver-specific option belongs under ``extra_params`` and must keep working),
but the drop should be visible as a warning naming the key.
"""

from __future__ import annotations

import logging

import pytest

from dblift.config.database_config import BaseDatabaseConfig, _instantiate_config
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.plugins.sqlserver.config import SqlServerConfig


@pytest.mark.unit
def test_unrecognized_database_key_warns_and_is_ignored(caplog):
    with caplog.at_level(logging.WARNING):
        cfg = _instantiate_config(
            PostgreSqlConfig,
            {"type": "postgresql", "host": "localhost", "srvice": "typo-of-service"},
        )

    assert cfg.type == "postgresql"  # still constructs; the key is ignored, not fatal
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("srvice" in message for message in warnings), warnings


@pytest.mark.unit
def test_a_clean_config_warns_about_nothing(caplog):
    with caplog.at_level(logging.WARNING):
        _instantiate_config(
            PostgreSqlConfig,
            {
                "type": "postgresql",
                "host": "localhost",
                "port": 5432,
                "username": "u",
                "password": "p",
                "schema": "s",
                "database": "d",
                "extra_params": {"sslmode": "require"},
            },
        )

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


@pytest.mark.unit
def test_sqlserver_fail_on_fixed_dbo_is_a_recognized_key(caplog):
    """The opt-in guard must not trip the unrecognized-key warning."""
    with caplog.at_level(logging.WARNING):
        cfg = _instantiate_config(
            SqlServerConfig,
            {
                "type": "sqlserver",
                "host": "localhost",
                "username": "sa",
                "password": "pw",
                "fail_on_fixed_dbo": True,
            },
        )

    assert isinstance(cfg, SqlServerConfig)
    assert cfg.fail_on_fixed_dbo is True
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


@pytest.mark.unit
def test_sqlserver_fail_on_fixed_dbo_defaults_to_false():
    cfg = BaseDatabaseConfig.create(
        {
            "type": "sqlserver",
            "host": "localhost",
            "username": "sa",
            "password": "pw",
            "database": "app",
        }
    )
    assert isinstance(cfg, SqlServerConfig)
    assert cfg.fail_on_fixed_dbo is False

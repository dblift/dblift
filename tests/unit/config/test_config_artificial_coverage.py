from dataclasses import replace
from unittest.mock import mock_open, patch

import pytest
import yaml

pytestmark = [pytest.mark.unit]

from dblift.config.database_config import BaseDatabaseConfig
from dblift.config.dblift_config import DbliftConfig


def test_dbliftconfig_load_yaml_file_none(monkeypatch):
    """Test handling of None return from _load_yaml_file."""
    # Mock yaml.safe_load to return None and open to avoid file error
    with (
        patch("yaml.safe_load", return_value=None),
        patch("builtins.open", mock_open(read_data="")),
    ):
        with pytest.raises(yaml.YAMLError, match="Empty or invalid YAML file"):
            DbliftConfig.from_file("fake.yaml")


def test_dbliftconfig_load_yaml_file_empty(monkeypatch):
    """Test handling of empty configuration file."""
    # Mock yaml.safe_load to return empty dict and open to avoid file error
    with (
        patch("yaml.safe_load", return_value={}),
        patch("builtins.open", mock_open(read_data="{}")),
    ):
        # The empty dict causes an error when trying to create database config
        with pytest.raises((ValueError, yaml.YAMLError)):
            DbliftConfig.from_file("fake.yaml")


def test_dbliftconfig_from_dict_malformed(monkeypatch):
    """Test handling of malformed configuration dictionaries."""
    # Test with non-dict database value
    d = {"database": 123}
    with pytest.raises(AttributeError):
        DbliftConfig.from_dict(d)

    # Test with None database value
    d = {"database": None}
    with pytest.raises(AttributeError):
        DbliftConfig.from_dict(d)

    # Test with invalid database type - this fails at connection identifier validation first
    d = {"database": {"type": "invalid"}}
    with pytest.raises(ValueError, match="Database URL not specified"):
        DbliftConfig.from_dict(d)

    # Test with missing required fields
    d = {"database": {"type": "postgresql"}}
    with pytest.raises(
        ValueError, match="PostgreSQL connection requires url or host/database fields"
    ):
        DbliftConfig.from_dict(d)


def test_basedatabaseconfig_registry_missing_type(monkeypatch):
    """Test handling of missing or invalid database type in registry.

    Roadmap action #11 added a second resolution path on
    ``PluginInfo.config_class``; clearing only ``_registry`` no longer
    triggers the unsupported-type error because the postgresql plugin's
    ``config_class`` covers it. Patch the registered postgresql plugin's
    ``config_class`` to None too so this test keeps exercising the
    ValueError branch its name implies.

    Pass ``type`` explicitly to bypass URL-driven dialect inference,
    which also consults ``ProviderRegistry`` and would race the patch.
    """
    from dblift.db.provider_registry import ProviderRegistry

    # Test with empty legacy registry, and force the postgresql plugin's
    # config_class field to None so neither resolution path satisfies.
    plugins_without_config_class = {
        name: replace(pi, config_class=None) for name, pi in ProviderRegistry._plugins.items()
    }
    with patch.object(BaseDatabaseConfig, "_registry", {}):
        with patch.object(ProviderRegistry, "_plugins", plugins_without_config_class):
            with patch.object(ProviderRegistry, "_discovered", True):
                with pytest.raises(ValueError, match="Unsupported database type: postgresql"):
                    BaseDatabaseConfig.create(
                        {
                            "type": "postgresql",
                            "url": "postgresql+psycopg://localhost:5432/db",
                            "username": "pg",
                            "password": "pw",
                        }
                    )

    # Test with missing URL
    with pytest.raises(ValueError, match="Database URL is required \(use --db-url\)"):
        BaseDatabaseConfig.create({"username": "pg", "password": "pw"})

    # Test with invalid URL format
    with pytest.raises(ValueError, match="Unsupported database type"):
        BaseDatabaseConfig.create({"url": "invalid:url", "username": "pg", "password": "pw"})


def test_basedatabaseconfig_create_invalid_types():
    """Test handling of invalid property types and values."""
    # Test with non-dict properties and extra_params
    d = {
        "url": "postgresql+psycopg://localhost:5432/db",
        "username": "pg",
        "password": "pw",
        "properties": 123,
        "extra_params": 456,
    }
    cfg = BaseDatabaseConfig.create(d)
    # Verify that invalid types are converted to empty dicts
    assert isinstance(cfg.properties, dict)
    assert len(cfg.properties) == 0
    assert isinstance(cfg.extra_params, dict)
    assert len(cfg.extra_params) == 0

    # Test with non-int port string (port from URL takes precedence)
    d = {
        "url": "postgresql+psycopg://localhost:5432/db",
        "username": "pg",
        "password": "pw",
        "port": "notanint",
    }
    cfg = BaseDatabaseConfig.create(d)
    # Verify that port from URL (5432) is used instead of invalid port string
    assert cfg.port == 5432

    # Test with invalid property value types (properties remain as lists, not converted to strings)
    d = {
        "url": "postgresql+psycopg://localhost:5432/db",
        "username": "pg",
        "password": "pw",
        "properties": {"key": ["not", "a", "string"]},
    }
    cfg = BaseDatabaseConfig.create(d)
    # Verify that invalid property values remain as lists (no conversion happens in current impl)
    assert isinstance(cfg.properties["key"], list)
    assert cfg.properties["key"] == ["not", "a", "string"]


def test_basedatabaseconfig_to_dict_with_none_fields():
    """Test handling of None values in optional fields during serialization."""
    # Create config with minimal required fields
    d = {"url": "postgresql+psycopg://localhost:5432/db", "username": "pg", "password": "pw"}
    cfg = BaseDatabaseConfig.create(d)

    # Test with None values in optional fields
    cfg.extra_params = None
    cfg.properties = None
    cfg.port = None
    cfg.database = None
    cfg.host = None

    # Verify that None values are handled correctly in serialization
    d2 = cfg.to_dict()
    # The to_dict() method behavior: check what's actually returned
    assert isinstance(d2["extra_params"], dict) or d2["extra_params"] is None
    assert isinstance(d2["properties"], dict) or d2["properties"] is None

    # Database, host, and port may retain parsed values from URL or be None
    assert "database" in d2
    assert "host" in d2
    assert "port" in d2

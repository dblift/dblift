"""Tests for BaseDatabaseConfig.build_connection_string (default + subclasses)."""

from dataclasses import dataclass

import pytest

from dblift.config.database_config import BaseDatabaseConfig, DummyDatabaseConfig

pytestmark = [pytest.mark.unit]


class TestBaseDatabaseConfigBuildConnectionString:
    """Subclasses stay instantiable; native string without url requires override."""

    def test_build_connection_string_is_abstract(self):
        """build_connection_string is an @abstractmethod in the base (LSP-02)."""
        assert "build_connection_string" in BaseDatabaseConfig.__abstractmethods__

    def test_subclass_without_override_cannot_be_instantiated(self):
        """A subclass that does not override build_connection_string cannot be instantiated (LSP-02)."""

        @dataclass
        class MinimalConfig(BaseDatabaseConfig):
            pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            MinimalConfig(
                type="postgresql",
                username="u",
                password="p",
                host="localhost",
                port=5432,
                database="db",
            )

    def test_subclass_with_override_can_be_instantiated(self):
        """A subclass that overrides build_connection_string can be instantiated."""

        @dataclass
        class MinimalConfig(BaseDatabaseConfig):
            def build_connection_string(self) -> str:
                return self.url or "minimal://"

        cfg = MinimalConfig(type="postgresql", url="postgresql+psycopg://localhost/db")
        assert cfg.build_connection_string() == cfg.url
        assert cfg.build_database_url().startswith("postgresql+psycopg://")

    def test_dummy_database_config_instantiates(self):
        config = DummyDatabaseConfig(type="dummy")
        assert config is not None
        assert config.build_connection_string() == "dummy://"

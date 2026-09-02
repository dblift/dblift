"""Dummy ``BaseDatabaseConfig`` subclass used by tests."""

from dataclasses import dataclass

from dblift.config.database_config import BaseDatabaseConfig, register_database_type


@register_database_type("dummy")
@dataclass(repr=False)  # keep BaseDatabaseConfig.__repr__ (credential-masked)
class DummyDatabaseConfig(BaseDatabaseConfig):
    """Dummy database configuration for testing."""

    def __post_init__(self) -> None:
        super().__post_init__()
        self.type = "dummy"

    def build_connection_string(self) -> str:
        """Stub implementation for testing."""
        return "dummy://"

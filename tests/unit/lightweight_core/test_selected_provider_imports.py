"""A selected SQLite provider should leave other engines unloaded."""

from tests.unit.lightweight_core._support import run_python

FOREIGN_PROVIDERS = (
    "dblift.db.plugins.oracle.provider",
    "dblift.db.plugins.postgresql.provider",
    "dblift.db.plugins.mongodb.provider",
    "dblift.db.plugins.snowflake.provider",
)


def test_sqlite_quirks_resolve_without_foreign_providers():
    result = run_python("""
        import sys
        from dblift.db.provider_registry import ProviderRegistry
        assert ProviderRegistry.get_quirks('sqlite').dialect_name == 'sqlite'
        for module in %r:
            assert module not in sys.modules, module
        """ % (FOREIGN_PROVIDERS,))
    assert result.returncode == 0, result.stderr


def test_silent_sqlite_client_resolves_without_foreign_providers():
    result = run_python("""
        import sys
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from dblift.api.client import DBLiftClient
        from dblift.config import DbliftConfig
        from dblift.extensions.logging import NullLog
        with TemporaryDirectory() as directory:
            config = DbliftConfig.from_dict({
                'database': {'type': 'sqlite', 'path': str(Path(directory) / 'db.sqlite')},
            })
            with DBLiftClient.from_config(config, migrations_dir=Path(directory), logger=NullLog()):
                pass
        for module in %r:
            assert module not in sys.modules, module
        """ % (FOREIGN_PROVIDERS,))
    assert result.returncode == 0, result.stderr

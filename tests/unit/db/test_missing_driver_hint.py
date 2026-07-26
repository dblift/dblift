"""A missing optional driver must name the extra that installs it.

`pip install dblift` deliberately pulls no database drivers: the plugins all
import without them (that is what keeps a bare install from crashing). The
cost is that the *first* real command fails, and until now it failed with
SQLAlchemy's raw ``No module named 'psycopg'`` — accurate, and useless to
someone who does not already know the extra is spelled ``dblift[postgresql]``.

The registry already knew the answer: every ``PluginInfo`` declares its
``native_driver_module``, and ``validate_driver_for_type`` composes a decent
message from it. That check simply was never reached — SQLAlchemy imports the
DBAPI itself, deep inside ``create_engine``, and raises first.
"""

from __future__ import annotations

import pytest

from db.provider_registry import NativeDriverManager, PluginInfo, ProviderRegistry


@pytest.fixture(autouse=True)
def _discovered() -> None:
    ProviderRegistry.discover_plugins()


class TestPluginsDeclareTheirInstallExtra:
    @pytest.mark.parametrize(
        "dialect, extra",
        [
            ("postgresql", "postgresql"),
            ("mysql", "mysql"),
            ("oracle", "oracle"),
            ("sqlserver", "sqlserver"),
            ("db2", "db2"),
            ("duckdb", "duckdb"),
        ],
    )
    def test_the_extra_is_declared(self, dialect: str, extra: str) -> None:
        plugin = ProviderRegistry.get_plugin_info(dialect)
        assert plugin is not None
        assert plugin.install_extra == extra

    def test_a_driverless_plugin_declares_no_extra(self) -> None:
        """SQLite needs nothing installed, so there is nothing to suggest."""
        plugin = ProviderRegistry.get_plugin_info("sqlite")
        assert plugin is not None
        assert plugin.install_extra is None

    def test_every_plugin_with_a_driver_declares_an_extra(self) -> None:
        """A driver with no extra leaves the user with nothing actionable."""
        for plugin in ProviderRegistry.list_plugins():
            if plugin.native_driver_module:
                assert plugin.install_extra, f"{plugin.name} declares a driver but no extra"


class TestTheMessageIsActionable:
    def test_validate_names_the_pip_command(self) -> None:
        plugin = ProviderRegistry.get_plugin_info("postgresql")
        ok, message = NativeDriverManager.validate_driver_for_type("postgresql", plugin)
        # The driver *is* installed here, so force the negative branch.
        missing = PluginInfo(
            name="postgresql",
            version=plugin.version,
            description=plugin.description,
            dialects=["postgresql"],
            provider_class=plugin.provider_class,
            native_driver_module="definitely_not_installed_xyz",
            install_extra="postgresql",
        )
        ok, message = NativeDriverManager.validate_driver_for_type("postgresql", missing)
        assert ok is False
        assert message is not None
        assert 'pip install "dblift[postgresql]"' in message
        assert "definitely_not_installed_xyz" in message

    def test_a_plugin_without_an_extra_still_reports_the_module(self) -> None:
        plugin = ProviderRegistry.get_plugin_info("postgresql")
        assert plugin is not None
        missing = PluginInfo(
            name="custom",
            version="1.0.0",
            description="a third-party plugin declaring no install extra",
            dialects=["custom"],
            provider_class=plugin.provider_class,
            native_driver_module="nope_xyz",
            install_extra=None,
        )
        ok, message = NativeDriverManager.validate_driver_for_type("custom", missing)
        assert ok is False
        assert "nope_xyz" in str(message)
        assert "pip install" not in str(message)


class TestTheHintReachesTheUser:
    def test_a_driver_import_failure_is_translated(self) -> None:
        """SQLAlchemy raises first, so the hint has to wrap that failure.

        Without this the user sees ``No module named 'psycopg'`` from deep
        inside SQLAlchemy's dialect loader and has to guess the extra.
        """
        from db.native_connection_manager import describe_missing_driver

        message = describe_missing_driver(
            "postgresql", ModuleNotFoundError("No module named 'psycopg'")
        )
        assert message is not None
        assert 'pip install "dblift[postgresql]"' in message

    def test_an_unrelated_import_error_is_not_claimed(self) -> None:
        """Only the declared driver's absence should be reinterpreted."""
        from db.native_connection_manager import describe_missing_driver

        assert (
            describe_missing_driver("postgresql", ModuleNotFoundError("No module named 'yaml'"))
            is None
        )

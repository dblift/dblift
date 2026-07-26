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

from typing import Any, Iterator

import pytest

import db.native_connection_manager as connection_manager_module
from db.native_connection_manager import NativeConnectionManager, describe_missing_driver
from db.provider_registry import NativeDriverManager, PluginInfo, ProviderRegistry


@pytest.fixture(autouse=True)
def _discovered() -> None:
    ProviderRegistry.discover_plugins()


@pytest.fixture
def _undiscovered_registry(_discovered: None) -> Iterator[None]:
    """Snapshot + restore ``ProviderRegistry`` global state, rewound to pre-discovery.

    Same snapshot/restore shape as ``tests/unit/db/test_provider_registry_entry_points.py``.
    It depends on the module's autouse ``_discovered`` fixture so the ordering is
    explicit: discovery runs, *then* this rewinds it — otherwise the autouse
    fixture could re-populate the registry after the rewind and the test would
    silently assert nothing.
    """
    saved_plugins = dict(ProviderRegistry._plugins)
    saved_quirks_cache = dict(ProviderRegistry._quirks_cache)
    saved_discovered = ProviderRegistry._discovered
    ProviderRegistry._plugins.clear()
    ProviderRegistry._quirks_cache.clear()
    ProviderRegistry._discovered = False
    yield
    ProviderRegistry._plugins.clear()
    ProviderRegistry._plugins.update(saved_plugins)
    ProviderRegistry._quirks_cache.clear()
    ProviderRegistry._quirks_cache.update(saved_quirks_cache)
    ProviderRegistry._discovered = saved_discovered


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
        message = describe_missing_driver(
            "postgresql", ModuleNotFoundError("No module named 'psycopg'")
        )
        assert message is not None
        assert 'pip install "dblift[postgresql]"' in message

    def test_an_unrelated_import_error_is_not_claimed(self) -> None:
        """Only the declared driver's absence should be reinterpreted."""
        assert (
            describe_missing_driver("postgresql", ModuleNotFoundError("No module named 'yaml'"))
            is None
        )

    def test_a_plain_import_error_is_not_claimed(self) -> None:
        """``ImportError`` is not proof the module is absent.

        A driver that *is* installed but raises ``ImportError`` on import (a
        broken C extension — this repo has one, see the ``cryptography``
        note in CLAUDE.md) must not be reported as "not installed": the
        suggested ``pip install`` would be a no-op and the real failure would
        be buried. The message here is deliberately the one that *would*
        match, so the test pins the type check rather than the text.
        """
        assert (
            describe_missing_driver("postgresql", ImportError("No module named 'psycopg'")) is None
        )

    def test_a_driverless_dialect_gets_no_hint(self) -> None:
        """SQLite ships with CPython, so there is no extra to name.

        Composing a message anyway would produce "Native driver module
        'unknown' is not installed for sqlite" — an invented fact about the
        user's environment.
        """
        plugin = ProviderRegistry.get_plugin_info("sqlite")
        assert plugin is not None
        assert plugin.native_driver_module is None  # the precondition this test rests on
        assert (
            describe_missing_driver("sqlite", ModuleNotFoundError("No module named 'sqlite3'"))
            is None
        )

    def test_a_driverless_nosql_dialect_gets_no_hint(self) -> None:
        """Cosmos DB declares no ``native_driver_module`` either."""
        plugin = ProviderRegistry.get_plugin_info("cosmosdb")
        assert plugin is not None
        assert plugin.native_driver_module is None
        assert (
            describe_missing_driver("cosmosdb", ModuleNotFoundError("No module named 'azure'"))
            is None
        )

    def test_an_unregistered_dialect_gets_no_hint(self) -> None:
        """Nothing is known about an unregistered dialect, so nothing is claimed."""
        assert ProviderRegistry.get_plugin_info("no_such_dialect_xyz") is None
        assert (
            describe_missing_driver(
                "no_such_dialect_xyz", ModuleNotFoundError("No module named 'psycopg'")
            )
            is None
        )

    def test_a_dotted_driver_module_is_matched_on_the_message(self) -> None:
        """Snowflake declares ``snowflake.connector``, so the match must span the dot.

        ``ModuleNotFoundError.name`` is the module Python gave up on, which for
        a dotted target is not necessarily the string the plugin declared. The
        message text carries the full dotted path when the parent package is
        present and the submodule is not, which is the case a user hits after
        ``pip install snowflake-sqlalchemy`` without the connector.

        Bounded deliberately to that case. When the *root* package is absent
        too, CPython reports only the root (``No module named 'snowflake'``,
        ``name='snowflake'``) and neither the message nor ``.name`` contains
        the declared ``snowflake.connector``, so no hint is produced. That is
        current behaviour, not an intended guarantee — a test asserting it
        would freeze the gap.
        """
        plugin = ProviderRegistry.get_plugin_info("snowflake")
        assert plugin is not None
        assert plugin.native_driver_module == "snowflake.connector"
        message = describe_missing_driver(
            "snowflake",
            ModuleNotFoundError(
                "No module named 'snowflake.connector'", name="snowflake.connector"
            ),
        )
        assert message is not None
        assert "snowflake.connector" in message
        assert 'pip install "dblift[snowflake]"' in message


class _Database:
    """Minimal stand-in for a dblift database config section."""

    def __init__(self, db_type: str) -> None:
        self.type = db_type


class _Config:
    def __init__(self, db_type: str) -> None:
        self.database = _Database(db_type)


def _engine_raising(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    """Make ``create_engine`` fail the way SQLAlchemy's dialect loader does."""

    def _create_engine(url: str, **kwargs: Any) -> Any:
        raise exc

    monkeypatch.setattr(
        connection_manager_module.ProviderRegistry,
        "build_sqlalchemy_url",
        lambda database: "postgresql+psycopg://u:p@localhost:5432/db",
    )
    monkeypatch.setattr(connection_manager_module, "create_engine", _create_engine)


class TestTheHintSurfacesFromTheEngineProperty:
    """The translation is only worth anything where a user actually meets it.

    ``describe_missing_driver`` composing a good string is necessary but not
    sufficient — ``NativeConnectionManager.engine`` is the only caller, and it
    is the caller that decides whether the user sees the hint, the raw error,
    or a hint with the original failure thrown away.
    """

    def test_a_missing_driver_reaches_the_caller_as_the_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _engine_raising(monkeypatch, ModuleNotFoundError("No module named 'psycopg'"))
        manager = NativeConnectionManager(_Config("postgresql"))

        with pytest.raises(ModuleNotFoundError) as excinfo:
            manager.engine

        assert "psycopg" in str(excinfo.value)
        assert 'pip install "dblift[postgresql]"' in str(excinfo.value)

    def test_the_original_failure_is_kept_as_the_cause(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Replacing the message must not cost the traceback that located it.

        The point of the hint is to make a driver problem *easier* to
        diagnose. Raising a bare ``ModuleNotFoundError(hint)`` would drop the
        frames inside SQLAlchemy's dialect loader, so a user whose failure is
        not actually the declared driver — a shadowed module, a broken
        namespace package — would be left with a confident, wrong pip command
        and no evidence.
        """
        original = ModuleNotFoundError("No module named 'psycopg'")
        _engine_raising(monkeypatch, original)
        manager = NativeConnectionManager(_Config("postgresql"))

        with pytest.raises(ModuleNotFoundError) as excinfo:
            manager.engine

        assert excinfo.value is not original
        assert excinfo.value.__cause__ is original

    def test_an_unrelated_module_error_reaches_the_caller_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The feature must not reinterpret failures it cannot explain.

        ``create_engine`` imports plenty besides the DBAPI. A missing
        ``yaml`` surfacing as ``pip install "dblift[postgresql]"`` would send
        the user to install a driver they already have.
        """
        original = ModuleNotFoundError("No module named 'yaml'")
        _engine_raising(monkeypatch, original)
        manager = NativeConnectionManager(_Config("postgresql"))

        with pytest.raises(ModuleNotFoundError) as excinfo:
            manager.engine

        assert excinfo.value is original  # same object, re-raised
        assert excinfo.value.__cause__ is None
        assert "pip install" not in str(excinfo.value)
        assert str(excinfo.value) == "No module named 'yaml'"


class TestTheHintDoesNotNeedDiscoveryToHaveHappened:
    """The hint fires on the *first* command after a bare ``pip install dblift``.

    That is exactly the moment when nothing has forced plugin discovery yet,
    so ``get_plugin_info`` has to trigger it. If it did not, the lookup would
    return ``None``, ``describe_missing_driver`` would decline to explain,
    and the feature would be dead precisely in the scenario it was built for.
    """

    def test_get_plugin_info_discovers_on_demand(self, _undiscovered_registry: None) -> None:
        assert ProviderRegistry._plugins == {}
        assert ProviderRegistry._discovered is False

        plugin = ProviderRegistry.get_plugin_info("postgresql")

        assert plugin is not None
        assert plugin.name == "postgresql"
        assert ProviderRegistry._discovered is True

    def test_the_hint_is_composed_before_anything_forced_discovery(
        self, _undiscovered_registry: None
    ) -> None:
        assert ProviderRegistry._discovered is False

        message = describe_missing_driver(
            "postgresql", ModuleNotFoundError("No module named 'psycopg'")
        )

        assert message is not None
        assert 'pip install "dblift[postgresql]"' in message

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

import importlib
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest
from sqlalchemy.exc import NoSuchModuleError

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

        This is the narrow case: the ``snowflake`` package is present (say
        ``snowflake-sqlalchemy`` was installed on its own) and only the
        connector submodule is absent, so CPython names the declared module
        exactly.
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

    def test_a_missing_root_package_names_the_extra(self) -> None:
        """The common case for a dotted driver: the distribution is absent entirely.

        Snowflake is the only plugin declaring a dotted
        ``native_driver_module``, and a user who ran ``pip install dblift``
        without the extra has no ``snowflake`` package at all. CPython then
        reports the missing *ancestor* — ``No module named 'snowflake'`` — and
        never mentions ``snowflake.connector``, so matching only the declared
        string missed the single scenario this feature exists for and left
        snowflake users with SQLAlchemy's raw error.
        """
        message = describe_missing_driver(
            "snowflake", ModuleNotFoundError("No module named 'snowflake'", name="snowflake")
        )
        assert message is not None
        assert 'pip install "dblift[snowflake]"' in message

    def test_the_hint_does_not_depend_on_the_name_attribute(self) -> None:
        """A hand-constructed ``ModuleNotFoundError`` carries ``name=None``.

        ``name`` is keyword-only, so ``ModuleNotFoundError("No module named
        'snowflake'")`` — what every caller in this suite builds, and what
        ``NativeConnectionManager.engine`` itself raises when it substitutes
        the hint — reports ``name is None``. Deciding on ``.name`` alone would
        make the translation depend on who constructed the exception rather
        than on what is missing.
        """
        exc = ModuleNotFoundError("No module named 'snowflake'")
        assert exc.name is None  # the precondition this test rests on
        assert describe_missing_driver("snowflake", exc) is not None

    def test_a_not_a_package_suffix_does_not_defeat_the_match(self) -> None:
        """CPython appends a clause when an ancestor is a module, not a package.

        ``No module named 'snowflake.connector'; 'snowflake' is not a
        package`` is what a stray ``snowflake.py`` on the path produces. The
        declared driver is still what is missing, so the hint still applies —
        the trailing clause must not be read as part of the module name.
        """
        message = describe_missing_driver(
            "snowflake",
            ModuleNotFoundError(
                "No module named 'snowflake.connector'; 'snowflake' is not a package",
                name="snowflake.connector",
            ),
        )
        assert message is not None
        assert 'pip install "dblift[snowflake]"' in message

    @pytest.mark.parametrize(
        "missing",
        [
            # An unrelated distribution that merely starts with the driver
            # package's name. A ``startswith`` on the declared module's first
            # component claims it and sends the user to install the snowflake
            # extra for something with no relation to the driver.
            "snowflake_utils",
            # A textual prefix of the declared module that stops mid-component.
            # ``snowflake.connect`` is a different submodule, so its absence
            # says nothing about ``snowflake.connector``: only a dot boundary
            # makes one module name an ancestor of another.
            "snowflake.connect",
        ],
    )
    def test_a_name_sharing_a_prefix_without_a_dot_boundary_is_not_claimed(
        self, missing: str
    ) -> None:
        assert (
            describe_missing_driver(
                "snowflake", ModuleNotFoundError(f"No module named '{missing}'", name=missing)
            )
            is None
        )

    def test_an_unrelated_submodule_of_the_driver_package_is_not_claimed(self) -> None:
        """The ``snowflake`` package is importable and something else under it is not.

        Nothing here proves the declared driver is absent — the package is
        installed — so ``pip install "dblift[snowflake]"`` would be a no-op
        that hides whatever actually failed.
        """
        assert (
            describe_missing_driver(
                "snowflake",
                ModuleNotFoundError(
                    "No module named 'snowflake.other_subpackage'",
                    name="snowflake.other_subpackage",
                ),
            )
            is None
        )

    def test_an_unrelated_import_error_is_not_claimed_for_a_dotted_driver(self) -> None:
        """Widening the match for dotted modules must not widen it to everything."""
        assert (
            describe_missing_driver("snowflake", ModuleNotFoundError("No module named 'yaml'"))
            is None
        )

    @pytest.mark.parametrize(
        "dialect, missing",
        [
            # A different driver distribution that happens to start with the
            # declared one's name: psycopg2 is the legacy driver, psycopg_pool
            # a separate package. Neither absence says psycopg is missing.
            ("postgresql", "psycopg2"),
            ("postgresql", "psycopg_pool"),
            # A descendant: psycopg imported fine and one of its own
            # submodules did not, which is a broken install, not a missing one.
            ("postgresql", "psycopg.pq"),
            ("mysql", "pymysql2"),
            ("mysql", "pymysql.cursors"),
        ],
    )
    def test_a_single_module_driver_matches_only_itself(self, dialect: str, missing: str) -> None:
        """Plugins declaring an undotted module keep their exact-match behaviour."""
        assert (
            describe_missing_driver(dialect, ModuleNotFoundError(f"No module named '{missing}'"))
            is None
        )

    @pytest.mark.parametrize(
        "dialect, module",
        [("postgresql", "psycopg"), ("mysql", "pymysql"), ("oracle", "oracledb")],
    )
    def test_a_single_module_driver_still_matches_itself(self, dialect: str, module: str) -> None:
        plugin = ProviderRegistry.get_plugin_info(dialect)
        assert plugin is not None
        assert plugin.native_driver_module == module  # the precondition
        assert (
            describe_missing_driver(dialect, ModuleNotFoundError(f"No module named '{module}'"))
            is not None
        )


class TestOnlyOnePluginDeclaresADottedDriver:
    def test_snowflake_is_the_only_dotted_declaration(self) -> None:
        """The ancestor rule only changes behaviour for dotted modules.

        If a second plugin ever declares one, this test is the reminder that
        the reasoning above (and the snowflake-specific cases) now applies to
        it too.
        """
        dotted = sorted(
            plugin.name
            for plugin in ProviderRegistry.list_plugins()
            if plugin.native_driver_module and "." in plugin.native_driver_module
        )
        assert dotted == ["snowflake"]


class TestTheCPythonBehaviourTheRuleRestsOn:
    """The declared-module-or-ancestor rule is right because of how imports fail.

    CPython names the *first* component of a dotted chain it could not find —
    so an ancestor being named proves the declared module is unreachable,
    while a descendant being named proves it was reachable. It reports that
    component identically in ``.name`` and in the message text. Neither fact
    is dblift's to guarantee, and the previous implementation carried a
    comment asserting the opposite (that ``.name`` holds only the missing
    leaf), so they are measured here instead of described.
    """

    @pytest.fixture
    def _package_on_the_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> Iterator[None]:
        """Put a real two-level package on ``sys.path`` so imports really fail."""
        package = tmp_path / "dblift_fake_pkg"
        (package / "present").mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "present" / "__init__.py").write_text("")
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()
        yield
        for name in [n for n in sys.modules if n.startswith("dblift_fake_pkg")]:
            del sys.modules[name]

    @staticmethod
    def _failed_import(target: str) -> ModuleNotFoundError:
        with pytest.raises(ModuleNotFoundError) as excinfo:
            importlib.import_module(target)
        return excinfo.value

    def test_an_absent_root_is_named_alone(self, _package_on_the_path: None) -> None:
        """Nothing installed: the ancestor is reported, the declared path never appears."""
        exc = self._failed_import("dblift_absent_pkg_xyz.connector")
        assert exc.name == "dblift_absent_pkg_xyz"
        assert str(exc) == "No module named 'dblift_absent_pkg_xyz'"

    def test_an_absent_leaf_is_named_in_full(self, _package_on_the_path: None) -> None:
        exc = self._failed_import("dblift_fake_pkg.missing_sub")
        assert exc.name == "dblift_fake_pkg.missing_sub"
        assert str(exc) == "No module named 'dblift_fake_pkg.missing_sub'"

    def test_a_three_level_import_names_the_missing_ancestor_not_the_leaf(
        self, _package_on_the_path: None
    ) -> None:
        """``a.b.c`` with ``a.b`` absent reports ``a.b`` — never ``c`` on its own."""
        exc = self._failed_import("dblift_fake_pkg.missing_sub.deeper")
        assert exc.name == "dblift_fake_pkg.missing_sub"
        assert str(exc) == "No module named 'dblift_fake_pkg.missing_sub'"

    def test_a_three_level_import_names_the_full_path_when_only_the_leaf_is_absent(
        self, _package_on_the_path: None
    ) -> None:
        exc = self._failed_import("dblift_fake_pkg.present.missing_leaf")
        assert exc.name == "dblift_fake_pkg.present.missing_leaf"
        assert str(exc) == "No module named 'dblift_fake_pkg.present.missing_leaf'"

    def test_name_is_always_the_module_the_message_quotes(self, _package_on_the_path: None) -> None:
        """The two never disagree, so reading either loses nothing."""
        for target in (
            "dblift_absent_pkg_xyz.connector",
            "dblift_fake_pkg.missing_sub",
            "dblift_fake_pkg.missing_sub.deeper",
            "dblift_fake_pkg.present.missing_leaf",
        ):
            exc = self._failed_import(target)
            assert exc.name is not None
            assert str(exc).startswith(f"No module named '{exc.name}'")


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

    def test_an_absent_driver_package_reaches_the_caller_as_the_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The dotted-driver case, end to end through the only caller.

        ``create_engine`` reports the missing ancestor (``No module named
        'snowflake'``) rather than the declared ``snowflake.connector``
        whenever the package chain is broken above the driver, and the user
        still has to be told which extra to install.
        """
        _engine_raising(
            monkeypatch, ModuleNotFoundError("No module named 'snowflake'", name="snowflake")
        )
        manager = NativeConnectionManager(_Config("snowflake"))

        with pytest.raises(ModuleNotFoundError) as excinfo:
            manager.engine

        assert 'pip install "dblift[snowflake]"' in str(excinfo.value)

    def test_a_dialect_sqlalchemy_cannot_load_is_not_translated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A remaining gap, recorded rather than implied to be closed.

        Snowflake's SQLAlchemy *dialect* lives in ``snowflake-sqlalchemy``,
        which is what ``dblift[snowflake]`` installs. With nothing snowflake
        installed at all, ``create_engine("snowflake://...")`` therefore fails
        while resolving the dialect entry point — ``NoSuchModuleError: Can't
        load plugin: sqlalchemy.dialects:snowflake`` — which is an
        ``ArgumentError``, not a ``ModuleNotFoundError``, so neither
        ``describe_missing_driver`` nor ``engine``'s except clause sees it and
        the raw error still reaches that user.

        Closing that is a separate decision: a dialect SQLAlchemy cannot load
        is not in general a missing dblift driver (every built-in dialect
        resolves without an extra), so it needs its own reasoning rather than a
        widened except clause. This test exists so the boundary is visible and
        a future widening has to change a test that states why.
        """
        original = NoSuchModuleError("Can't load plugin: sqlalchemy.dialects:snowflake")
        _engine_raising(monkeypatch, original)
        manager = NativeConnectionManager(_Config("snowflake"))

        with pytest.raises(NoSuchModuleError) as excinfo:
            manager.engine

        assert excinfo.value is original
        assert "pip install" not in str(excinfo.value)

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

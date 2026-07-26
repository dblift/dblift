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
from sqlalchemy import create_engine
from sqlalchemy.dialects import registry as dialect_registry
from sqlalchemy.exc import ArgumentError, NoSuchModuleError

import db.native_connection_manager as connection_manager_module
import db.plugins
from db.native_connection_manager import (
    NativeConnectionManager,
    describe_missing_driver,
    describe_unloadable_dialect,
)
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

        This is the narrow case: the ``snowflake`` package is present and only
        the connector submodule is absent, so CPython names the declared module
        exactly. Reaching it takes deliberate effort — ``dblift[snowflake]``
        installs ``snowflake-sqlalchemy``, which depends on
        ``snowflake-connector-python``, so the connector arrives transitively.
        It takes a ``pip install --no-deps snowflake-sqlalchemy``, or
        uninstalling the connector afterwards, to leave a tree in this state.
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
        """A missing *ancestor* of the declared module still names the extra.

        Snowflake is the only first-party plugin declaring a dotted
        ``native_driver_module``. Whenever the package chain breaks above the
        driver, CPython reports ``No module named 'snowflake'`` and never
        mentions ``snowflake.connector``, so matching only the declared string
        returned ``None`` and the raw error reached the user.

        Reachable when a ``*.dist-info`` still registers snowflake's dialect
        entry point but the package directory is gone — a partial or broken
        install — and for any future dotted declaration. It is deliberately
        *not* the claim that this rescues a bare ``pip install dblift``: with
        nothing snowflake installed the dialect does not resolve at all and
        ``create_engine`` raises ``NoSuchModuleError`` before any of this runs.
        That failure is translated by its own rule, with its own message —
        see ``TestAnUnloadableDialectNamesTheExtraThatInstallsIt``.
        """
        message = describe_missing_driver(
            "snowflake", ModuleNotFoundError("No module named 'snowflake'", name="snowflake")
        )
        assert message is not None
        assert 'pip install "dblift[snowflake]"' in message

    def test_the_hint_does_not_depend_on_the_name_attribute(self) -> None:
        """A ``ModuleNotFoundError`` built without ``name=`` carries ``name=None``.

        ``name`` is keyword-only, so ``ModuleNotFoundError("No module named
        'snowflake'")`` — the form most of this suite builds — reports ``name
        is None``. Passing it does populate it, so the reason to read the
        message is not that ``.name`` is unavailable: it is that deciding on
        ``.name`` would make the translation depend on how the exception was
        constructed rather than on what is missing.
        """
        exc = ModuleNotFoundError("No module named 'snowflake'")
        assert exc.name is None  # the precondition this test rests on
        # Keyword-only is not the same as unavailable, so "``.name`` is always
        # ``None`` on a hand-constructed exception" would be false.
        assert ModuleNotFoundError("No module named 'snowflake'", name="snowflake").name == (
            "snowflake"
        )
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


class TestOnlyOneFirstPartyPluginDeclaresADottedDriver:
    """A reminder for dblift maintainers, so it reads dblift's own plugins only.

    Scoped to the ``PLUGIN`` constants under ``db/plugins/*/plugin.py``, not to
    ``ProviderRegistry.list_plugins()``. The registry also returns plugins
    registered through the ``dblift.providers`` entry-point group — the
    documented extension path (``pip install dblift-snowflake``, see
    ``ProviderRegistry._discover_via_entry_points``). A third-party plugin is
    entitled to declare a dotted ``native_driver_module``, and reading the
    registry would let it turn dblift's own suite red with nothing wrong in
    dblift.
    """

    @staticmethod
    def _first_party_plugins() -> list[PluginInfo]:
        """Read every first-party ``plugin.py:PLUGIN`` straight off the filesystem."""
        plugins_dir = Path(db.plugins.__file__).parent
        return [
            importlib.import_module(f"db.plugins.{plugin_file.parent.name}.plugin").PLUGIN
            for plugin_file in sorted(plugins_dir.glob("*/plugin.py"))
        ]

    def test_the_first_party_plugins_are_actually_found(self) -> None:
        """Guard the guard: a glob matching nothing would make the tripwire vacuous."""
        plugins = self._first_party_plugins()
        names = {plugin.name for plugin in plugins}
        assert len(plugins) >= 15
        assert {"snowflake", "postgresql", "mysql", "sqlite"} <= names

    def test_snowflake_is_the_only_first_party_dotted_declaration(self) -> None:
        """The ancestor rule only changes behaviour for dotted modules.

        If a second first-party plugin ever declares one, this test is the
        reminder that the reasoning in ``describe_missing_driver`` (and the
        snowflake-specific cases above) now applies to it too.
        """
        dotted = sorted(
            plugin.name
            for plugin in self._first_party_plugins()
            if plugin.native_driver_module and "." in plugin.native_driver_module
        )
        assert dotted == ["snowflake"]

    def test_a_third_party_dotted_declaration_does_not_fail_this_suite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Registering one must leave the tripwire above green.

        The registry reports it — that is the extension path working — but it is
        not dblift's to police, so the maintainer reminder must not fire on it.
        """
        host = ProviderRegistry.get_plugin_info("postgresql")
        assert host is not None
        third_party = PluginInfo(
            name="acme-warehouse",
            version="1.0.0",
            description="a third-party plugin declaring a dotted driver module",
            dialects=["acme_warehouse"],
            provider_class=host.provider_class,
            native_driver_module="acme.connector",
            install_extra=None,
        )
        monkeypatch.setitem(ProviderRegistry._plugins, "acme-warehouse", third_party)

        assert any(
            plugin.native_driver_module == "acme.connector"
            for plugin in ProviderRegistry.list_plugins()
        ), "precondition: the registry must actually see the third-party plugin"
        self.test_snowflake_is_the_only_first_party_dotted_declaration()


class TestTheCPythonBehaviourTheRuleRestsOn:
    """The declared-module-or-ancestor rule is right because of how imports fail.

    On a failed ``a.b.c`` CPython names the dotted prefix *through* the first
    component it could not find — ``a.b`` when ``a.b`` is absent, neither ``b``
    on its own nor the full ``a.b.c``. So an ancestor being named proves the
    declared module is unreachable, while a descendant being named proves it
    was reachable. For these not-found imports it reports the same string in
    ``.name`` and in the message text.

    Neither fact is dblift's to guarantee, and the previous implementation
    carried a comment asserting the opposite (that ``.name`` holds only the
    missing leaf), so they are measured here instead of described — including
    the forms where the message and ``.name`` part company.
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

    def test_a_not_found_import_quotes_in_the_message_what_name_holds(
        self, _package_on_the_path: None
    ) -> None:
        """For these four imports the message and ``.name`` agree.

        Bounded to imports that fail because a module could not be *found*.
        That is not a general property of ``ModuleNotFoundError`` — see
        ``test_a_blocked_import_reports_no_quoted_module_though_name_holds_one``
        for the form where the two part company — so this claims only what it
        measures.
        """
        for target in (
            "dblift_absent_pkg_xyz.connector",
            "dblift_fake_pkg.missing_sub",
            "dblift_fake_pkg.missing_sub.deeper",
            "dblift_fake_pkg.present.missing_leaf",
        ):
            exc = self._failed_import(target)
            assert exc.name is not None
            assert str(exc).startswith(f"No module named '{exc.name}'")

    def test_a_blocked_import_reports_no_quoted_module_though_name_holds_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CPython's third form: ``None`` in ``sys.modules`` blocks the import.

        The message is ``import of x halted; None in sys.modules`` — it quotes
        no module — while ``.name`` is still ``'x'``. It is one of the shapes
        where reading the message and reading ``.name`` disagree (the other
        being the apostrophe case below), and it is pinned here because the
        docstring of ``_missing_module`` asserts it.

        Consequence, deliberately recorded rather than fixed: with snowflake's
        root blocked, ``.name`` *is* an ancestor of the declared
        ``snowflake.connector``, yet no hint is composed. The substring check
        this replaced behaved identically, so this is not a regression — and a
        deliberately blocked import is not evidence that a distribution is
        absent, so translating it into ``pip install`` would be a new and
        wrong claim about the user's environment.
        """
        monkeypatch.setitem(sys.modules, "snowflake", None)
        with pytest.raises(ModuleNotFoundError) as excinfo:
            importlib.import_module("snowflake")
        exc = excinfo.value

        assert str(exc) == "import of snowflake halted; None in sys.modules"
        assert exc.name == "snowflake"
        assert connection_manager_module._missing_module(exc) is None
        # ``.name`` would have matched, which is exactly why the docstring may
        # not claim the two always agree.
        assert connection_manager_module._is_module_or_ancestor(exc.name, "snowflake.connector")
        assert describe_missing_driver("snowflake", exc) is None

    def test_an_apostrophe_in_the_name_is_double_quoted_in_the_message(self) -> None:
        """The message interpolates the name with ``{!r}``, so quoting flips.

        ``No module named "wei'rd_xyz"`` does not match a regex looking for a
        single-quoted name, so ``_missing_module`` declines. Pinned because
        ``_missing_module``'s docstring says so; harmless in practice because
        such a name is not an identifier, so only ``importlib`` called with a
        string can even attempt it.
        """
        with pytest.raises(ModuleNotFoundError) as excinfo:
            importlib.import_module("wei'rd_xyz")
        exc = excinfo.value

        assert str(exc) == 'No module named "wei\'rd_xyz"'
        assert exc.name == "wei'rd_xyz"
        assert connection_manager_module._missing_module(exc) is None


class _Database:
    """Minimal stand-in for a dblift database config section."""

    def __init__(self, db_type: str) -> None:
        self.type = db_type


class _Config:
    def __init__(self, db_type: str) -> None:
        self.database = _Database(db_type)


def _engine_raising(
    monkeypatch: pytest.MonkeyPatch,
    exc: BaseException,
    url: str = "postgresql+psycopg://u:p@localhost:5432/db",
) -> None:
    """Make ``create_engine`` fail the way SQLAlchemy's dialect loader does.

    *url* is what ``build_sqlalchemy_url`` is made to return. The dialect-load
    rule decides on it (the plugin key is derived from its drivername), so
    those tests have to choose it; the driver-import rule ignores it, which is
    why the default keeps the older tests reading as they did.
    """

    def _create_engine(url_: str, **kwargs: Any) -> Any:
        raise exc

    monkeypatch.setattr(
        connection_manager_module.ProviderRegistry,
        "build_sqlalchemy_url",
        lambda database: url,
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

    def test_the_driver_import_hint_wording_is_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pin the ``ModuleNotFoundError`` path's message in full.

        The dialect-load rule added alongside it composes a *different*
        message, on purpose, and shares no composer with this one. Asserting
        equality rather than a substring is what makes a drift in either
        wording visible here instead of silently changing what users read.
        """
        _engine_raising(monkeypatch, ModuleNotFoundError("No module named 'psycopg'"))
        manager = NativeConnectionManager(_Config("postgresql"))

        with pytest.raises(ModuleNotFoundError) as excinfo:
            manager.engine

        assert str(excinfo.value) == (
            "Native driver module 'psycopg' is not installed for postgresql. "
            'Install it with: pip install "dblift[postgresql]"'
        )

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


class TestTheSQLAlchemyBehaviourTheDialectRuleRestsOn:
    """Four extras ship a SQLAlchemy *dialect*, not just a DBAPI, and fail earlier.

    ``dblift[snowflake]`` installs ``snowflake-sqlalchemy``,
    ``dblift[redshift]`` installs ``sqlalchemy-redshift``, ``dblift[db2]``
    ``ibm_db_sa``, ``dblift[duckdb]`` ``duckdb_engine``. Each registers a
    ``sqlalchemy.dialects`` entry point, so with the extra absent
    ``create_engine`` never reaches the DBAPI import: it cannot resolve the
    dialect at all and raises ``NoSuchModuleError``.

    The translation rule keys on two facts about SQLAlchemy — the entry-point
    key it derives from a URL's drivername, and the message its plugin loader
    composes when that key resolves to nothing. Neither is dblift's to
    guarantee, so both are measured here against the installed SQLAlchemy
    rather than described. The dialect names used are deliberately synthetic:
    nothing can ever register them, so these tests say the same thing whatever
    extras the environment happens to have.
    """

    @staticmethod
    def _failed_load(url: str) -> NoSuchModuleError:
        with pytest.raises(NoSuchModuleError) as excinfo:
            create_engine(url)
        return excinfo.value

    def test_a_bare_drivername_is_the_plugin_key_verbatim(self) -> None:
        """``snowflake`` — the shape snowflake and duckdb URLs use."""
        url = "dblift_absent_dialect_xyz://"
        exc = self._failed_load(url)

        # The preconditions the whole rule rests on, and the reason ``engine``
        # needs a second ``except`` clause rather than a widened first one:
        # ``NoSuchModuleError`` is an ``ArgumentError``, so the driver-import
        # clause never saw this and the raw message reached the user.
        assert isinstance(exc, ArgumentError)
        assert not isinstance(exc, ModuleNotFoundError)

        assert connection_manager_module._dialect_plugin_key(url) == "dblift_absent_dialect_xyz"
        assert str(exc) == "Can't load plugin: sqlalchemy.dialects:dblift_absent_dialect_xyz"

    def test_a_plus_driver_drivername_maps_the_plus_to_a_dot(self) -> None:
        """``redshift+redshift_connector`` → ``redshift.redshift_connector``.

        The shape redshift and db2 URLs use, and the reason the key cannot
        simply be the drivername.
        """
        url = "dblift_absent_dialect_xyz+some_driver://"
        exc = self._failed_load(url)

        assert connection_manager_module._dialect_plugin_key(url) == (
            "dblift_absent_dialect_xyz.some_driver"
        )
        assert str(exc) == (
            "Can't load plugin: sqlalchemy.dialects:dblift_absent_dialect_xyz.some_driver"
        )

    @pytest.mark.parametrize(
        "url",
        ["dblift_absent_dialect_xyz://", "dblift_absent_dialect_xyz+some_driver://"],
    )
    def test_the_message_dblift_expects_is_the_message_sqlalchemy_composes(self, url: str) -> None:
        """The rule compares whole messages, so the expected form must be measured.

        If SQLAlchemy ever rewords ``Can't load plugin: %s:%s`` this test goes
        red. That matters: the comparison fails closed, so without this the
        translation would quietly stop happening while every test that
        monkeypatches the exception in still passed.
        """
        # The loader dblift reads the group off is the one ``URL._get_entrypoint``
        # calls, so the group half of the message is not a literal either.
        assert dialect_registry.group == "sqlalchemy.dialects"
        key = connection_manager_module._dialect_plugin_key(url)
        assert key is not None
        assert str(self._failed_load(url)) == connection_manager_module._unloadable_plugin_message(
            key
        )

    def test_an_unparseable_url_yields_no_plugin_key(self) -> None:
        """``make_url`` raises rather than returning ``None``, and that must not escape.

        Not reachable through ``create_engine`` — it parses the URL before it
        looks a dialect up, so an unparseable URL raises ``ArgumentError``
        long before any ``NoSuchModuleError``. Pinned because the rule runs
        *inside* an except block, where an unexpected raise would replace the
        real failure with a parse error.
        """
        with pytest.raises(ArgumentError):
            connection_manager_module.make_url("not a sqlalchemy url")
        assert connection_manager_module._dialect_plugin_key("not a sqlalchemy url") is None


class TestAnUnloadableDialectNamesTheExtraThatInstallsIt:
    """The behaviour change: this failure used to reach the user raw.

    A previous revision of this file recorded it as a known gap
    (``test_a_dialect_sqlalchemy_cannot_load_is_not_translated``), on the
    grounds that a dialect SQLAlchemy cannot load is not in general a missing
    dblift driver — every built-in dialect resolves without an extra, so a
    widened ``except`` clause would have claimed things it could not know.

    What closes it is a rule narrow enough to know: translate only when the
    plugin SQLAlchemy failed to load is *exactly* the one dblift's own URL
    named. dblift built that URL from its own registry, so an entry point it
    named resolving to nothing means the extra providing it is absent — and
    the registry already knows which extra that is. A ``NoSuchModuleError``
    about any other plugin still reaches the user untouched.

    These tests build the engine for real — no monkeypatched
    ``create_engine`` — because the failure is genuinely reproducible: the
    snowflake and redshift extras are installed neither here nor in CI, so
    ``NativeConnectionManager.engine`` really does fail this way.
    """

    @staticmethod
    def _engine_failure(dialect: str) -> NoSuchModuleError:
        """Return the real failure from building *dialect*'s engine.

        Skips rather than fails when the environment happens to have the
        dialect package installed, since then there is nothing to reproduce.
        """
        manager = NativeConnectionManager(_Config(dialect))
        try:
            manager.engine
        except NoSuchModuleError as exc:
            return exc
        manager.close()
        pytest.skip(f"the SQLAlchemy dialect for {dialect} is installed in this environment")

    def test_the_message_names_the_extra_that_installs_the_dialect(self) -> None:
        exc = self._engine_failure("snowflake")

        assert 'pip install "dblift[snowflake]"' in str(exc)

    def test_the_message_does_not_claim_the_native_driver_module_is_missing(self) -> None:
        """What is absent is the dialect package, and the message may only say that.

        Reusing ``missing_driver_message`` would have read "Native driver
        module 'snowflake.connector' is not installed for snowflake" — a claim
        nothing here establishes. SQLAlchemy never got as far as importing a
        DBAPI, so the only proven absence is the dialect entry point
        ``dblift[snowflake]`` supplies.
        """
        message = str(self._engine_failure("snowflake"))

        assert 'pip install "dblift[snowflake]"' in message  # a hint was composed at all
        assert "Native driver module" not in message
        assert "snowflake.connector" not in message

    def test_the_message_names_the_dialect_plugin_that_could_not_be_loaded(self) -> None:
        """A user who reads it should be able to tell what SQLAlchemy looked for."""
        exc = self._engine_failure("redshift")

        assert "redshift.redshift_connector" in str(exc)
        assert 'pip install "dblift[redshift]"' in str(exc)

    def test_the_original_failure_is_kept_as_the_cause(self) -> None:
        """Same reason as the driver-import path: the hint must not cost the evidence."""
        exc = self._engine_failure("snowflake")
        cause = exc.__cause__

        assert isinstance(cause, NoSuchModuleError)
        assert str(cause) == "Can't load plugin: sqlalchemy.dialects:snowflake"

    def test_the_exception_type_is_preserved(self) -> None:
        """Callers catching ``NoSuchModuleError`` / ``ArgumentError`` must keep working.

        Raising a ``ModuleNotFoundError`` carrying the hint — the shape the
        driver-import path uses — would turn a documented SQLAlchemy error
        into an unrelated builtin for anyone handling it.
        """
        exc = self._engine_failure("snowflake")

        assert 'pip install "dblift[snowflake]"' in str(exc)  # the re-raised one, not the original
        assert type(exc) is NoSuchModuleError
        assert isinstance(exc, ArgumentError)

    def test_a_plus_driver_dialect_is_recognised_through_its_dotted_key(self) -> None:
        """Redshift's URL is ``redshift+redshift_connector://``.

        Comparing against the drivername rather than the derived key would
        look for ``redshift+redshift_connector``, never match the
        ``redshift.redshift_connector`` SQLAlchemy reports, and leave this
        user with the raw error.
        """
        exc = self._engine_failure("redshift")
        cause = exc.__cause__

        assert isinstance(cause, NoSuchModuleError)
        assert str(cause) == "Can't load plugin: sqlalchemy.dialects:redshift.redshift_connector"
        assert 'pip install "dblift[redshift]"' in str(exc)


class TestTheDialectRuleClaimsNothingItCannotProve:
    """Everything the narrow rule must decline, and why each would be a wrong claim."""

    @pytest.fixture
    def _quirks_cache_restored(self, _discovered: None) -> Iterator[None]:
        """Undo the ``BaseQuirks`` entry a synthetic dialect leaves in the cache."""
        saved = dict(ProviderRegistry._quirks_cache)
        yield
        ProviderRegistry._quirks_cache.clear()
        ProviderRegistry._quirks_cache.update(saved)

    def test_a_failure_naming_another_plugin_propagates_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``NoSuchModuleError`` is raised for lookups that are not dblift's.

        ``DialectKWArgs._kw_reg_for_dialect`` loads a dialect out of the same
        group by the prefix of a kwarg (``mysql_engine=``), and a third-party
        dialect can fail to find something of its own. Claiming
        ``dblift[snowflake]`` fixes that would send the user to install a
        package unrelated to what failed and bury the plugin actually missing.
        """
        original = NoSuchModuleError("Can't load plugin: sqlalchemy.dialects:some_other_plugin")
        _engine_raising(monkeypatch, original, url="snowflake://")
        manager = NativeConnectionManager(_Config("snowflake"))

        with pytest.raises(NoSuchModuleError) as excinfo:
            manager.engine

        assert excinfo.value is original  # same object, re-raised
        assert excinfo.value.__cause__ is None
        assert "pip install" not in str(excinfo.value)

    def test_a_failure_from_a_different_entry_point_group_propagates_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``sqlalchemy.plugins`` is a different group sharing the message format.

        ``?plugin=`` in a URL, or ``create_engine(plugins=[...])``, loads from
        it through the same ``PluginLoader``. A plugin there named after the
        dialect is not the dialect, so the extra would be the wrong fix.
        """
        original = NoSuchModuleError("Can't load plugin: sqlalchemy.plugins:snowflake")
        _engine_raising(monkeypatch, original, url="snowflake://")
        manager = NativeConnectionManager(_Config("snowflake"))

        with pytest.raises(NoSuchModuleError) as excinfo:
            manager.engine

        assert excinfo.value is original
        assert "pip install" not in str(excinfo.value)

    def test_a_dialect_declaring_no_install_extra_propagates_untouched(
        self, monkeypatch: pytest.MonkeyPatch, _quirks_cache_restored: None
    ) -> None:
        """A third-party plugin owes dblift no extra, and none may be invented.

        Registered the way the documented ``dblift.providers`` entry point
        registers one, with a real URL builder, so this runs the whole
        ``engine`` path against a dialect SQLAlchemy genuinely cannot load.
        There is no ``dblift[acme_absent_dialect_xyz]`` to install, so the only
        honest outcome is the raw error.
        """
        host = ProviderRegistry.get_plugin_info("postgresql")
        assert host is not None
        third_party = PluginInfo(
            name="acme_absent_dialect_xyz",
            version="1.0.0",
            description="a third-party plugin shipping its own SQLAlchemy dialect",
            dialects=["acme_absent_dialect_xyz"],
            provider_class=host.provider_class,
            sqlalchemy_url_builder=lambda database: "acme_absent_dialect_xyz://host/db",
            install_extra=None,
        )
        monkeypatch.setitem(ProviderRegistry._plugins, "acme_absent_dialect_xyz", third_party)
        manager = NativeConnectionManager(_Config("acme_absent_dialect_xyz"))

        with pytest.raises(NoSuchModuleError) as excinfo:
            manager.engine

        assert str(excinfo.value) == (
            "Can't load plugin: sqlalchemy.dialects:acme_absent_dialect_xyz"
        )
        assert excinfo.value.__cause__ is None
        assert "pip install" not in str(excinfo.value)

    def test_an_unregistered_dialect_propagates_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no ``PluginInfo`` at all there is no extra to name."""
        original = NoSuchModuleError("Can't load plugin: sqlalchemy.dialects:no_such_dialect_xyz")
        _engine_raising(monkeypatch, original, url="no_such_dialect_xyz://host/db")
        manager = NativeConnectionManager(_Config("no_such_dialect_xyz"))

        with pytest.raises(NoSuchModuleError) as excinfo:
            manager.engine

        assert ProviderRegistry.get_plugin_info("no_such_dialect_xyz") is None
        assert excinfo.value is original
        assert "pip install" not in str(excinfo.value)

    @pytest.mark.parametrize("exc_type", [ArgumentError, ModuleNotFoundError])
    def test_only_the_no_such_module_subclass_is_translated(
        self, exc_type: type[Exception]
    ) -> None:
        """The exception *type* decides, not the message text.

        ``ArgumentError`` is what ``create_engine`` raises for URL problems
        that imply nothing about installed packages; only the
        ``NoSuchModuleError`` subclass means "no entry point by that name". A
        ``ModuleNotFoundError`` belongs to ``describe_missing_driver``, and
        answering it here would report the dialect package absent when it in
        fact loaded and only the DBAPI did not.

        Both messages are deliberately the one that *would* match, so each
        parameter pins the type check rather than the text — the same shape as
        ``test_a_plain_import_error_is_not_claimed`` above.
        """
        assert (
            describe_unloadable_dialect(
                "snowflake",
                "snowflake://",
                exc_type("Can't load plugin: sqlalchemy.dialects:snowflake"),
            )
            is None
        )

    def test_an_unparseable_url_leaves_the_failure_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A URL that will not parse must not become a parse error from the handler.

        Defensive: ``create_engine`` parses before it resolves a plugin, so it
        cannot itself produce this pairing. What the test pins is that the rule
        fails closed — the original failure reaches the caller — rather than
        raising ``ArgumentError`` from inside the ``except`` block and losing
        it.
        """
        original = NoSuchModuleError("Can't load plugin: sqlalchemy.dialects:snowflake")
        _engine_raising(monkeypatch, original, url="not a sqlalchemy url")
        manager = NativeConnectionManager(_Config("snowflake"))

        with pytest.raises(NoSuchModuleError) as excinfo:
            manager.engine

        assert excinfo.value is original
        assert "pip install" not in str(excinfo.value)

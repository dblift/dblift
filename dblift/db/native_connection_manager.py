"""Owns a SQLAlchemy Engine and hands out Connections."""

import re
from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.dialects import registry as _dialect_registry
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.exc import ArgumentError, NoSuchModuleError

from dblift.core.logger import Log, NullLog
from dblift.db.provider_registry import NativeDriverManager, ProviderRegistry

# Matches the module name CPython quotes at the start of a ``ModuleNotFoundError``
# message. Deliberately a prefix match, not a full one: the message can carry a
# trailing clause (``No module named 'a.b'; 'a' is not a package``) that is not
# part of the module name.
_MISSING_MODULE_RE = re.compile(r"No module named '([^']+)'")


def _missing_module(exc: ModuleNotFoundError) -> Optional[str]:
    """Return the module name *exc* reports as missing, or ``None`` if it reports none.

    Read from the message text rather than ``exc.name``. ``name`` is
    keyword-only, so it holds nothing unless a caller passes it:
    ``ModuleNotFoundError("No module named 'snowflake'")`` reports
    ``name is None``, while ``ModuleNotFoundError("...", name="snowflake")``
    reports ``'snowflake'``. Interpreter-raised failures do populate it, but
    most of this suite constructs the exception without it, so deciding on
    ``.name`` would tie the translation to how the exception was built rather
    than to what is missing.

    The two are not interchangeable. For an ordinary not-found import they
    agree, which ``tests/unit/db/test_missing_driver_hint.py`` measures rather
    than assumes, but CPython has forms where they do not:

    * ``sys.modules['x'] = None`` blocks an import, and importing ``x`` then
      raises ``ModuleNotFoundError`` whose message is ``import of x halted;
      None in sys.modules`` while ``.name`` is still ``'x'``. This returns
      ``None`` there, so no hint is composed even where ``.name`` would have
      named the declared driver's ancestor. That is also what the substring
      check this replaced did, so it is behaviour recorded by a test rather
      than a regression: a deliberately blocked import is not evidence that a
      distribution is absent.
    * The message interpolates the name with ``{!r}``, so one containing an
      apostrophe is double-quoted (``No module named "wei'rd_xyz"``) and this
      regex does not match. Such a name is not a Python identifier, so no
      ``import`` statement can produce it — only ``importlib`` by string.
    """
    match = _MISSING_MODULE_RE.match(str(exc))
    return match.group(1) if match else None


def _is_module_or_ancestor(candidate: str, module: str) -> bool:
    """Report whether *candidate* is *module* itself or one of its dot-boundary ancestors."""
    return candidate == module or module.startswith(f"{candidate}.")


def describe_missing_driver(dialect: str, exc: BaseException) -> Optional[str]:
    """Translate a driver-import failure raised from ``create_engine`` into an actionable hint.

    ``pip install dblift`` deliberately pulls no DB drivers, so every plugin
    imports without one. The gap this closes: ``create_engine`` imports the
    DBAPI itself, deep inside SQLAlchemy's dialect loader
    (``sqlalchemy.engine.create.default.DefaultDialect.import_dbapi``), and
    that import failure surfaces *before* dblift's own
    ``NativeDriverManager.validate_driver_for_type`` is ever consulted. The
    user would otherwise see a raw ``No module named 'psycopg'`` with no clue
    that the fix is ``pip install "dblift[postgresql]"``.

    Only reinterprets the failure when *exc* names the module the registered
    plugin declares as its ``native_driver_module`` for *dialect*, or a
    dot-boundary ancestor of it (``snowflake`` for a declared
    ``snowflake.connector``) — an unrelated ``ModuleNotFoundError`` (a typo'd
    YAML import, a missing unrelated package, a submodule of the driver package
    that is not the driver) must surface unchanged, so this returns ``None``
    whenever the failure isn't provably the declared driver's absence.
    """
    if not isinstance(exc, ModuleNotFoundError):
        return None
    plugin_info = ProviderRegistry.get_plugin_info(dialect)
    if plugin_info is None or not plugin_info.native_driver_module:
        return None
    module = plugin_info.native_driver_module
    # For a dotted declaration such as ``snowflake.connector``, the failure does
    # not necessarily name the declared module. On a failed ``a.b.c`` CPython
    # names the dotted prefix *through* the first component it could not find —
    # ``a.b`` when ``a.b`` is absent, neither ``b`` on its own nor the full
    # ``a.b.c`` — so a message that never contains the declared string can still
    # prove the declared module unreachable.
    #
    # What actually arrives here that way, for a dotted declaration: a broken or
    # partial install, where a ``*.dist-info`` still registers the dialect entry
    # point but the package directory is gone, so SQLAlchemy resolves the dialect
    # and the ensuing import raises ``No module named 'snowflake'``; and any
    # future dotted declaration whose chain breaks above the driver.
    #
    # Not a bare ``pip install dblift``, despite appearances. The extras that
    # ship a SQLAlchemy *dialect* rather than only a DBAPI (snowflake, redshift,
    # db2, duckdb) fail earlier there: ``create_engine`` cannot resolve the
    # dialect entry point at all and raises ``NoSuchModuleError``, an
    # ``ArgumentError`` this function still declines. ``engine`` does now handle
    # it, in a second ``except`` clause with its own rule and its own message
    # (``describe_unloadable_dialect``).
    #
    # Engines on SQLAlchemy's built-in dialects (the PostgreSQL family,
    # MySQL, MariaDB, Oracle, SQL Server, SQLite) do raise
    # ``ModuleNotFoundError`` for an absent driver and the hint reaches them —
    # but every one of those declares an undotted module, so the widening below
    # changes nothing for them.
    #
    # Hence "the declared module or a dot-boundary ancestor of it": an ancestor
    # being missing proves the declared module is unreachable, so naming the
    # extra is right. A *descendant* being missing (``snowflake.other``) proves
    # the opposite — the declared package was importable — so suggesting
    # ``pip install`` would be a no-op hiding the real failure. The dot boundary
    # is what makes this an ancestor test rather than a string-prefix one:
    # ``snowflake_utils`` is an unrelated distribution.
    missing = _missing_module(exc)
    if missing is None or not _is_module_or_ancestor(missing, module):
        return None
    return NativeDriverManager.missing_driver_message(dialect, plugin_info)


def _dialect_plugin_key(url: str) -> Optional[str]:
    """Return the ``sqlalchemy.dialects`` entry-point key *url*'s drivername resolves to.

    SQLAlchemy does not look a dialect up under the drivername verbatim:
    ``URL._get_entrypoint`` turns every ``+`` into a ``.``, so
    ``redshift+redshift_connector://`` resolves ``redshift.redshift_connector``
    while a bare drivername is used as-is. Comparing a failure against the
    drivername would therefore never match the key SQLAlchemy names for the
    ``+driver`` shape, so the derivation is reproduced here rather than guessed
    at — and measured against the installed SQLAlchemy, for both shapes, in
    ``tests/unit/db/test_missing_driver_hint.py``
    (``TestTheSQLAlchemyBehaviourTheDialectRuleRestsOn``).

    Returns ``None`` for a URL ``make_url`` cannot parse rather than letting its
    ``ArgumentError`` escape: the only caller runs inside an ``except`` block,
    where a parse error raised from here would replace the failure being
    explained with an unrelated one.
    """
    try:
        drivername = make_url(url).drivername
    except ArgumentError:
        return None
    return drivername.replace("+", ".")


def _unloadable_plugin_message(plugin_key: str) -> str:
    """Compose the message SQLAlchemy raises when *plugin_key* resolves to no dialect.

    ``PluginLoader.load`` formats ``Can't load plugin: <group>:<name>`` for an
    entry point it cannot find. The group half is read off the very loader
    ``URL._get_entrypoint`` consults — ``sqlalchemy.dialects.registry`` — rather
    than spelled out, so it cannot drift from the loader whose message it is
    compared against.

    ``tests/unit/db/test_missing_driver_hint.py`` asserts this equals what a
    real ``create_engine`` failure stringifies to. That matters because the
    comparison in ``describe_unloadable_dialect`` fails closed: were SQLAlchemy
    to reword the message, the translation would quietly stop happening, and
    this is the test that would go red instead.
    """
    return f"Can't load plugin: {_dialect_registry.group}:{plugin_key}"


def describe_unloadable_dialect(dialect: str, url: str, exc: BaseException) -> Optional[str]:
    """Translate "SQLAlchemy has no such dialect" into the extra that supplies it.

    Some extras ship a SQLAlchemy *dialect*, not merely a DBAPI. With one of
    them absent ``create_engine`` never reaches the DBAPI import at all: it
    cannot resolve the dialect entry point and raises ``NoSuchModuleError``,
    which subclasses ``ArgumentError`` rather than ``ModuleNotFoundError``.
    Neither ``describe_missing_driver`` nor ``engine``'s driver-import
    ``except`` clause sees that, so the raw ``Can't load plugin: ...`` used to
    reach the user.

    A dialect SQLAlchemy cannot load is not in general a missing dblift driver —
    its built-in dialects all resolve with nothing extra installed — so this
    translates only when the plugin that failed to load is *exactly* the one
    dblift's own URL named. It declines unless all three hold:

    * *exc* is a ``NoSuchModuleError``. A plain ``ArgumentError`` carrying the
      same text is declined, because only the subclass means "no entry point by
      that name"; ``create_engine`` raises the base class for URL problems that
      imply nothing about installed packages. A ``ModuleNotFoundError`` is
      declined too — that is ``describe_missing_driver``'s failure, and it would
      have the dialect package reported absent when it in fact loaded fine.
    * ``str(exc)`` equals ``_unloadable_plugin_message`` for the key derived
      from *url*. Comparing the whole message is deliberate, because
      ``NoSuchModuleError`` is raised for lookups that are not this one and
      says so only in its text. Two exist in SQLAlchemy 2.0.51: a second
      loader over the ``sqlalchemy.plugins`` group, which ``?plugin=`` in the
      URL and ``create_engine(plugins=[...])`` resolve through the same
      ``PluginLoader`` and the same message format
      (``URL._instantiate_plugins``, which runs *before* the dialect is looked
      up); and ``DialectKWArgs._kw_reg_for_dialect``, which loads a dialect by
      the prefix of a kwarg such as ``mysql_engine=`` — a different key from
      the same group. Checking the group and the key together tells all three
      apart. It fails closed — an unparseable URL yields no key and so no
      hint, never a wrong one.
    * the registry holds a ``PluginInfo`` for *dialect* declaring an
      ``install_extra``. A third-party plugin registered through
      ``dblift.providers`` owes dblift no extra, and composing
      ``pip install "dblift[...]"`` for an extra that may not exist is worse
      than the error it would replace.

    The message shares no composer with
    ``NativeDriverManager.missing_driver_message``, on purpose. "Native driver
    module 'X' is not installed" would assert something nothing here
    establishes: no DBAPI import was attempted, so this says only what is
    proven — that no installed package provides the dialect SQLAlchemy looked
    for, and that the registry declares this extra for *dialect*. It names no
    distribution, since ``PluginInfo`` records none.
    """
    if not isinstance(exc, NoSuchModuleError):
        return None
    key = _dialect_plugin_key(url)
    if key is None or str(exc) != _unloadable_plugin_message(key):
        return None
    plugin_info = ProviderRegistry.get_plugin_info(dialect)
    if plugin_info is None or not plugin_info.install_extra:
        return None
    return (
        f"SQLAlchemy has no dialect registered for '{key}', which dblift's {dialect} "
        f"connection URL requires: no installed package provides that dialect. "
        f'Install it with: pip install "dblift[{plugin_info.install_extra}]"'
    )


class NativeConnectionManager:
    """Manages a SQLAlchemy Engine lifecycle and hands out Connections."""

    def __init__(
        self,
        config: Any,
        log: Optional[Log] = None,
        *,
        engine: Optional[Engine] = None,
        owns_engine: bool = True,
    ) -> None:
        """Initialise with a dblift config object and an optional logger.

        External engine injection (for from_sqlalchemy etc.) is supported via
        the ``engine`` / ``owns_engine`` kwargs. When an external engine is
        supplied, ``close()`` must not dispose it (``owns_engine=False``).
        """
        self.config = config
        self.log = log if log is not None else NullLog()
        self._engine = engine
        self._owns_engine = owns_engine
        self._connection: Optional[Connection] = None

    @property
    def engine(self) -> Engine:
        """Return the shared Engine, creating it on first access if not injected."""
        if self._engine is None:
            url = ProviderRegistry.build_sqlalchemy_url(self.config.database)
            self.log.debug(f"Creating SQLAlchemy engine for {self.config.database.type}")
            dialect = str(getattr(self.config.database, "type", ""))
            try:
                self._engine = create_engine(url, **self._engine_options())
            except ModuleNotFoundError as exc:
                hint = describe_missing_driver(dialect, exc)
                if hint is not None:
                    raise ModuleNotFoundError(hint) from exc
                raise
            except NoSuchModuleError as exc:
                hint = describe_unloadable_dialect(dialect, url, exc)
                if hint is not None:
                    raise NoSuchModuleError(hint) from exc
                raise
            self._owns_engine = True
        return self._engine

    def _engine_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {"pool_pre_ping": True, "future": True}
        dialect = str(getattr(self.config.database, "type", ""))
        options.update(ProviderRegistry.get_quirks(dialect).engine_pool_options())
        return options

    def create_connection(self) -> Connection:
        """Open and return a new Connection from the engine's pool.

        Closes any previously-held connection first so repeated calls do not
        leak connections back to the pool unclosed.
        """
        if self._connection is not None and not self._connection.closed:
            self._connection.close()
        self._connection = self.engine.connect()
        return self._connection

    def close(self) -> None:
        """Close the active connection and dispose of the engine (only if owned)."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._engine is not None and self._owns_engine:
            self._engine.dispose()
            self._engine = None

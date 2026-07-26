"""Owns a SQLAlchemy Engine and hands out Connections."""

import re
from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

from core.logger import Log, NullLog
from db.provider_registry import NativeDriverManager, ProviderRegistry

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
    # ``ArgumentError`` that neither this function nor ``engine``'s except clause
    # sees. Engines on SQLAlchemy's built-in dialects (the PostgreSQL family,
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

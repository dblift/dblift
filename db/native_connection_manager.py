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

    Read from the message text rather than ``exc.name``: ``name`` is
    keyword-only, so it is ``None`` on every hand-constructed
    ``ModuleNotFoundError`` — including the one ``NativeConnectionManager.engine``
    raises to carry the hint. Nothing is lost by preferring the message: for
    interpreter-raised failures the two always agree, which
    ``tests/unit/db/test_missing_driver_hint.py`` measures rather than assumes.
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
    # For a dotted declaration such as ``snowflake.connector``, CPython does not
    # necessarily name the declared module: it names the *first* component of the
    # dotted chain it could not find. With no ``snowflake`` package installed at
    # all — the common case after a bare ``pip install dblift`` — the failure is
    # ``No module named 'snowflake'``, and the declared string never appears.
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

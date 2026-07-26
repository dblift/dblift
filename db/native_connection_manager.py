"""Owns a SQLAlchemy Engine and hands out Connections."""

from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

from core.logger import Log, NullLog
from db.provider_registry import NativeDriverManager, ProviderRegistry


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

    Only reinterprets the failure when *exc* names the exact module the
    registered plugin declares as its ``native_driver_module`` for *dialect* —
    an unrelated ``ModuleNotFoundError`` (a typo'd YAML import, a missing
    unrelated package) must surface unchanged, so this returns ``None``
    whenever the failure isn't provably the declared driver's absence.
    """
    if not isinstance(exc, ModuleNotFoundError):
        return None
    plugin_info = ProviderRegistry.get_plugin_info(dialect)
    if plugin_info is None or not plugin_info.native_driver_module:
        return None
    module = plugin_info.native_driver_module
    # ``ModuleNotFoundError`` for a dotted module (e.g. ``snowflake.connector``)
    # names only the missing leaf in ``.name`` (``"connector"``), so match on
    # the message text SQLAlchemy/Python actually raises rather than ``.name``.
    if f"No module named '{module}'" not in str(exc):
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

"""Owns a SQLAlchemy Engine and hands out Connections."""

from typing import Any, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

from core.logger import Log, NullLog
from db.provider_registry import ProviderRegistry


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
            self._engine = create_engine(url, pool_pre_ping=True, future=True)
            self._owns_engine = True
        return self._engine

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

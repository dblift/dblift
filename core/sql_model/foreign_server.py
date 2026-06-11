"""Foreign Server SQL model class (PostgreSQL-specific)."""

from typing import Any, Dict, Optional

from core.sql_model.base import SqlObject, SqlObjectType


class ForeignServer(SqlObject):
    """
    Represents a foreign server (PostgreSQL-specific).

    Foreign Servers define connection parameters for specific remote data sources
    accessed through Foreign Data Wrappers. Multiple foreign tables can reference
    the same foreign server.
    """

    def __init__(
        self,
        name: str,
        fdw_name: str,
        host: Optional[str] = None,
        port: Optional[int] = None,
        dbname: Optional[str] = None,
        options: Optional[Dict[str, str]] = None,
        schema: Optional[str] = None,
        dialect: Optional[str] = None,
    ):
        """Initialize a foreign server.

        Args:
            name: Foreign server name
            fdw_name: Name of the foreign data wrapper to use
            host: Remote host address (optional)
            port: Remote port number (optional)
            dbname: Remote database name (optional)
            options: Server-specific options as key-value pairs (optional)
            schema: Schema (typically 'public')
            dialect: SQL dialect (typically 'postgresql')
        """
        super().__init__(
            name,
            SqlObjectType.FOREIGN_SERVER,
            schema,
            dialect or "postgresql",  # lint: allow-dialect-string: FDW server PG-only
        )
        self.fdw_name = fdw_name
        self.host = host
        self.port = port
        self.dbname = dbname
        # Create a copy of options to avoid mutating caller's dictionary
        self.options = dict(options) if options else {}

        # Merge host, port, dbname into options if provided
        if self.host:
            self.options["host"] = self.host
        if self.port:
            self.options["port"] = str(self.port)
        if self.dbname:
            self.options["dbname"] = self.dbname

    @property
    def create_statement(self) -> str:
        """Generate a basic CREATE SERVER statement."""
        return self._generate_basic_create_statement()

    def _generate_basic_create_statement(self) -> str:
        """Generate a basic CREATE SERVER statement as fallback."""
        server_name = self.format_identifier(self.name)
        fdw_name = self.format_identifier(self.fdw_name)

        stmt = f"CREATE SERVER {server_name}\n  FOREIGN DATA WRAPPER {fdw_name}"

        # Add options if specified
        if self.options:
            options_str = ", ".join([f"{k} '{v}'" for k, v in self.options.items()])
            stmt += f"\n  OPTIONS ({options_str})"

        stmt += ";"
        return stmt

    @property
    def drop_statement(self) -> str:
        """
        Generate DROP SERVER statement.

        Returns:
            PostgreSQL DROP SERVER statement
        """
        server_name = self.format_identifier(self.name)
        return f"DROP SERVER IF EXISTS {server_name} CASCADE;"

    def __str__(self) -> str:
        """Return string representation of the foreign server."""
        info = f"FOREIGN SERVER {self.name} (FDW: {self.fdw_name})"
        if self.host:
            info += f" -> {self.host}"
            if self.port:
                info += f":{self.port}"
        if self.dbname:
            info += f"/{self.dbname}"
        return info

    def __eq__(self, other: Any) -> bool:
        """Check if two foreign servers are equal."""
        if not isinstance(other, ForeignServer):
            return False
        return (
            super().__eq__(other)
            and self.fdw_name.lower() == other.fdw_name.lower()
            and (self.host or "").lower() == (other.host or "").lower()
            and self.port == other.port
            and (self.dbname or "").lower() == (other.dbname or "").lower()
            and self.options == other.options
        )

    def __hash__(self) -> int:
        """Return hash of the foreign server."""
        return hash(
            (
                self.name.lower(),
                self.object_type,
                (self.schema or "").lower(),
                self.fdw_name.lower(),
                (self.host or "").lower(),
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize foreign server to dictionary."""
        return {
            "name": self.name,
            "schema": self.schema,
            "dialect": self.dialect,
            "fdw_name": self.fdw_name,
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "options": self.options,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ForeignServer":
        """Deserialize foreign server from dictionary."""
        return cls(
            name=data.get("name", ""),
            fdw_name=data.get("fdw_name", ""),
            host=data.get("host"),
            port=data.get("port"),
            dbname=data.get("dbname"),
            options=data.get("options"),
            schema=data.get("schema"),
            dialect=data.get("dialect"),
        )

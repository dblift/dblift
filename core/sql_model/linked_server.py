"""Linked Server SQL model class (SQL Server-specific)."""

from typing import Any, Dict, Optional

from core.sql_model.base import SqlObject, SqlObjectType


class LinkedServer(SqlObject):
    """
    Represents a linked server (SQL Server-specific).

    Linked servers allow SQL Server to execute commands against remote
    databases (SQL Server, Oracle, MySQL, etc.) using distributed queries.
    Similar to Oracle Database Links.
    """

    def __init__(
        self,
        name: str,
        product: Optional[str] = None,
        provider: Optional[str] = None,
        data_source: Optional[str] = None,
        catalog: Optional[str] = None,
        username: Optional[str] = None,
        schema: Optional[str] = None,
        dialect: Optional[str] = None,
    ):
        """Initialize a linked server.

        Args:
            name: Linked server name
            product: Product name (e.g., 'SQL Server', 'Oracle', 'MySQL')
            provider: OLE DB provider name (e.g., 'SQLNCLI', 'OraOLEDB.Oracle')
            data_source: Network name/IP address of remote server
            catalog: Default database/catalog on remote server
            username: Login name for remote connection
            schema: Schema owner (typically dbo)
            dialect: SQL dialect (typically 'sqlserver')
        """
        # Linked servers are a SQL Server-specific feature
        super().__init__(name, SqlObjectType.DATABASE_LINK, schema, dialect)
        self.product = product
        self.provider = provider
        self.data_source = data_source
        self.catalog = catalog
        self.username = username

    @property
    def create_statement(self) -> str:
        """
        Generate CREATE LINKED SERVER statement using sp_addlinkedserver.

        Note: For security reasons, passwords are not stored or generated.
        Login mappings must be configured separately with sp_addlinkedsrvlogin.

        Returns:
            SQL Server EXEC sp_addlinkedserver statement (without password)
        """
        server_name = self.format_identifier(self.name)

        # Build the sp_addlinkedserver call
        stmt = f"EXEC sp_addlinkedserver\n  @server = {server_name}"

        if self.product:
            stmt += f",\n  @srvproduct = '{self.product}'"

        if self.provider:
            stmt += f",\n  @provider = '{self.provider}'"

        if self.data_source:
            stmt += f",\n  @datasrc = '{self.data_source}'"

        if self.catalog:
            stmt += f",\n  @catalog = '{self.catalog}'"

        stmt += ";"

        # Add login mapping note (not actual credentials)
        if self.username:
            stmt += "\n\n-- Configure login mapping:\n"
            stmt += "-- EXEC sp_addlinkedsrvlogin\n"
            stmt += f"--   @rmtsrvname = {server_name},\n"
            stmt += "--   @useself = 'FALSE',\n"
            stmt += f"--   @rmtuser = '{self.username}',\n"
            stmt += "--   @rmtpassword = '<password>';"

        return stmt

    @property
    def drop_statement(self) -> str:
        """
        Generate DROP LINKED SERVER statement using sp_dropserver.

        Returns:
            SQL Server EXEC sp_dropserver statement
        """
        server_name = self.format_identifier(self.name)
        return f"EXEC sp_dropserver @server = {server_name}, @droplogins = 'droplogins';"

    def __str__(self) -> str:
        """Return string representation of the linked server."""
        info = f"LINKED SERVER {self.name}"
        if self.product:
            info += f" ({self.product})"
        if self.data_source:
            info += f" -> {self.data_source}"
        if self.catalog:
            info += f".{self.catalog}"
        if self.username:
            info += f" (user: {self.username})"
        return info

    def __eq__(self, other: Any) -> bool:
        """Check if two linked servers are equal.

        Note: We compare connection parameters but not passwords for security.
        """
        if not isinstance(other, LinkedServer):
            return False
        return (
            super().__eq__(other)
            and (self.product or "").lower() == (other.product or "").lower()
            and (self.provider or "").lower() == (other.provider or "").lower()
            and (self.data_source or "").lower() == (other.data_source or "").lower()
            and (self.catalog or "").lower() == (other.catalog or "").lower()
            and (self.username or "").lower() == (other.username or "").lower()
        )

    def __hash__(self) -> int:
        """Return hash of the linked server."""
        return hash(
            (
                self.name.lower(),
                self.object_type,
                (self.schema or "").lower(),
                (self.data_source or "").lower(),
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize linked server to dictionary."""
        return {
            "name": self.name,
            "schema": self.schema,
            "dialect": self.dialect,
            "product": self.product,
            "provider": self.provider,
            "data_source": self.data_source,
            "catalog": self.catalog,
            "username": self.username,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LinkedServer":
        """Deserialize linked server from dictionary."""
        return cls(
            name=data.get("name", ""),
            product=data.get("product"),
            provider=data.get("provider"),
            data_source=data.get("data_source"),
            catalog=data.get("catalog"),
            username=data.get("username"),
            schema=data.get("schema"),
            dialect=data.get("dialect"),
        )

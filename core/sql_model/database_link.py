"""Database Link SQL model class (Oracle-specific)."""

from typing import Any, Dict, Optional

from core.sql_model.base import SqlObject, SqlObjectType


class DatabaseLink(SqlObject):
    """
    Represents a database link (Oracle-specific).

    Database links are named connections from one Oracle database to another,
    allowing distributed queries across multiple databases. They are essential
    for enterprise applications with multi-database architectures.
    """

    def __init__(
        self,
        name: str,
        host: Optional[str] = None,
        username: Optional[str] = None,
        connect_string: Optional[str] = None,
        public: bool = False,
        schema: Optional[str] = None,
        dialect: Optional[str] = None,
    ):
        """Initialize a database link.

        Args:
            name: Database link name
            host: Remote host name or TNS name (optional)
            username: Username for remote connection (optional)
            connect_string: Complete connection string/TNS name (optional)
            public: Whether this is a public database link
            schema: Schema owner (for private links)
            dialect: SQL dialect (typically 'oracle')
        """
        # Database links are an Oracle-specific feature
        super().__init__(name, SqlObjectType.DATABASE_LINK, schema, dialect)
        self.host = host
        self.username = username
        self.connect_string = connect_string
        self.public = public

    @property
    def create_statement(self) -> str:
        """
        Generate CREATE DATABASE LINK statement.

        Note: For security reasons, passwords are not stored or generated.
        The CREATE statement will need to be completed with credentials.

        Returns:
            Oracle CREATE DATABASE LINK statement (without password)
        """
        # Public or private link
        link_type = "PUBLIC " if self.public else ""
        link_name = self.format_identifier(self.name)

        stmt = f"CREATE {link_type}DATABASE LINK {link_name}"

        # Add CONNECT TO clause if username is specified
        if self.username:
            stmt += f"\n  CONNECT TO {self.username} IDENTIFIED BY <password>"

        # Add USING clause if connect string is specified
        if self.connect_string:
            stmt += f"\n  USING '{self.connect_string}'"

        return stmt

    @property
    def drop_statement(self) -> str:
        """
        Generate DROP DATABASE LINK statement.

        Returns:
            Oracle DROP DATABASE LINK statement
        """
        link_type = "PUBLIC " if self.public else ""
        link_name = self.format_identifier(self.name)
        return f"DROP {link_type}DATABASE LINK {link_name}"

    def __str__(self) -> str:
        """Return string representation of the database link."""
        link_type = "PUBLIC " if self.public else ""
        info = f"{link_type}DATABASE LINK {self.name}"
        if self.host:
            info += f" -> {self.host}"
        elif self.connect_string:
            info += f" -> {self.connect_string}"
        if self.username:
            info += f" (user: {self.username})"
        return info

    def __eq__(self, other: Any) -> bool:
        """Check if two database links are equal.

        Note: We compare connection parameters but not passwords for security.
        """
        if not isinstance(other, DatabaseLink):
            return False
        return (
            super().__eq__(other)
            and (self.host or "").lower() == (other.host or "").lower()
            and (self.username or "").lower() == (other.username or "").lower()
            and (self.connect_string or "").lower() == (other.connect_string or "").lower()
            and self.public == other.public
        )

    def __hash__(self) -> int:
        """Return hash of the database link."""
        return hash(
            (
                self.name.lower(),
                self.object_type,
                (self.schema or "").lower(),
                (self.host or "").lower(),
                self.public,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize database link to dictionary."""
        return {
            "name": self.name,
            "schema": self.schema,
            "dialect": self.dialect,
            "host": self.host,
            "username": self.username,
            "connect_string": self.connect_string,
            "public": self.public,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatabaseLink":
        """Deserialize database link from dictionary."""
        return cls(
            name=data.get("name", ""),
            host=data.get("host"),
            username=data.get("username"),
            connect_string=data.get("connect_string"),
            public=data.get("public", False),
            schema=data.get("schema"),
            dialect=data.get("dialect"),
        )

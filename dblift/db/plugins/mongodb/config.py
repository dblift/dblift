"""MongoDB-specific ``BaseDatabaseConfig`` subclass."""

from dataclasses import dataclass
from typing import Any, Dict
from urllib.parse import quote_plus

from dblift.config.database_config import BaseDatabaseConfig, register_database_type

#: MongoDB's default listening port, used when the host form omits one.
DEFAULT_MONGODB_PORT = 27017


# lint: allow-dialect-string: config type registration
@register_database_type("mongodb")
@dataclass(repr=False)  # keep BaseDatabaseConfig.__repr__ (credential-masked)
class MongoDbConfig(BaseDatabaseConfig):
    """Configuration for MongoDB connections.

    Two input shapes are accepted and ``url`` wins when both are present:

    * ``url`` — a full ``mongodb://`` or ``mongodb+srv://`` URI. Atlas,
      TLS, replica sets and auth sources all live here, because in MongoDB
      they are all URI query parameters.
    * ``host`` / ``port`` / ``username`` / ``password`` — assembled into a
      URI for callers that prefer discrete fields.

    Deliberately no ``tls`` / ``replica_set`` / ``auth_source`` fields:
    duplicating URI parameters as dataclass attributes gives two ways to
    say one thing and a second surface to keep current with driver releases.
    """

    def __post_init__(self) -> None:
        """Validate that a target and a database name are both reachable."""
        super().__post_init__()

        if not self.url and not self.host:
            raise ValueError("Either url or host must be provided for MongoDB")

        if not self.database:
            raise ValueError("database must be provided for MongoDB")

    def build_connection_string(self) -> str:
        """Return the MongoDB URI, assembling one from the host form if needed.

        Credentials are percent-encoded: a password containing ``@`` or
        ``/`` otherwise produces a URI the driver parses as a different
        host.
        """
        if self.url:
            return self.url

        port = self.port or DEFAULT_MONGODB_PORT
        if self.username:
            credentials = quote_plus(self.username)
            if self.password:
                credentials = f"{credentials}:{quote_plus(self.password)}"
            return f"mongodb://{credentials}@{self.host}:{port}"
        return f"mongodb://{self.host}:{port}"

    def build_database_url(self) -> str:
        """Return the URI with any password replaced by ``***``.

        Used wherever a connection target is displayed or logged.
        """
        uri = self.build_connection_string()
        scheme, _, remainder = uri.partition("://")
        if "@" not in remainder:
            return uri
        credentials, _, host_part = remainder.rpartition("@")
        user, sep, _password = credentials.partition(":")
        if not sep:
            return uri
        return f"{scheme}://{user}:***@{host_part}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary with the resolved URI included."""
        result = super().to_dict()
        result["uri"] = self.build_connection_string()
        return result

    def get_connection_props(self) -> Dict[str, str]:
        """Get connection properties for the MongoDB connection."""
        return {
            "uri": self.build_connection_string(),
            "database": str(self.database or ""),
        }

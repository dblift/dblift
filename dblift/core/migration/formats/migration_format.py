"""
Migration format enumeration.

Defines the different migration file formats supported by DBLIFT.
"""

from enum import Enum


class MigrationFormat(Enum):
    """
    Supported migration file formats.

    Currently only SQL is actively used, but the architecture is ready
    to support additional formats for NoSQL databases in the future.
    """

    SQL = "sql"
    """Standard SQL migrations (.sql files) - Currently supported"""

    PYTHON = "python"
    """Python-based migrations (.py files) - Future support for MongoDB, Redis, etc."""

    JAVASCRIPT = "javascript"
    """JavaScript migrations (.js files) - Future support for MongoDB shell"""

    CYPHER = "cypher"
    """Cypher query language (.cypher files) - Future support for Neo4j"""

    CQL = "cql"
    """Cassandra Query Language (.cql files) - Future support for Cassandra"""

    GREMLIN = "gremlin"
    """Gremlin graph traversal (.gremlin files) - Future support for graph databases"""

    JSON = "json"
    """JSON configuration (.json files) - Future support for declarative migrations"""

    YAML = "yaml"
    """YAML configuration (.yaml/.yml files) - Future support for declarative migrations"""

    UNKNOWN = "unknown"
    """Unknown or unsupported format"""

    def __str__(self) -> str:
        """String representation of the format."""
        return self.value

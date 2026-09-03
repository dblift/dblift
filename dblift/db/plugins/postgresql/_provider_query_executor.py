"""Query-executor adapter for PostgreSQL native provider schema operations."""

from typing import Any, List, Optional


class ProviderQueryExecutor:
    """Adapt native provider methods to the schema-operations query API."""

    def __init__(self, provider: Any) -> None:
        """Store the native provider being adapted."""
        self.provider = provider

    def execute_query(
        self, _connection: Any, sql: str, params: Optional[List[Any]] = None
    ) -> List[Any]:
        """Execute a query through the native provider."""
        return list(self.provider.execute_query(sql, params))

    def execute_statement(self, _connection: Any, sql: str) -> int:
        """Execute a statement through the native provider."""
        return int(self.provider.execute_statement(sql))

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Return the provider's quoted schema-qualified object name."""
        return str(self.provider.get_schema_qualified_name(schema, object_name))

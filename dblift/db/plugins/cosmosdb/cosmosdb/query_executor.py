"""
Cosmos DB query execution using the SQL API.

The Cosmos DB SQL API is a read-only query language: this module runs
``SELECT`` against containers. Everything that changes state — containers,
documents, throughput, indexing policy, TTL — is an Azure SDK call, not SQL
routed through a translator. That SDK call is made either from a
user-authored Python migration (via ``context.db`` / ``context.raw_client``)
or, for internal callers that are not a migration, through a native escape
hatch exposed here (e.g. ``upsert_native_item``).
"""

import re
from typing import Any, Dict, List, Optional, cast

from dblift.core.exceptions import NoSqlWriteNotSupportedError
from dblift.core.logger import Log, NullLog
from dblift.db.plugins.base_query_executor import BaseQueryExecutor

from .connection_manager import CosmosDbConnectionManager


class CosmosDbQueryExecutor(BaseQueryExecutor):
    """Executes queries against Cosmos DB using SQL API."""

    def __init__(self, connection_manager: CosmosDbConnectionManager, log: Optional[Log] = None):
        """Initialize the query executor.

        Args:
            connection_manager: Cosmos DB connection manager
            log: Optional logger
        """
        self.connection_manager = connection_manager
        self.log = log if log is not None else NullLog()
        self.container_client = None

    def execute_statement(
        self,
        connection: Any,
        sql: str,
        params: Optional[List[Any]] = None,
        return_generated_keys: bool = False,
    ) -> int:
        """Run a native Cosmos DB SQL statement.

        The Cosmos DB SQL API reads; it does not write. Containers and
        documents are changed through the Azure SDK, so a write statement
        reaching here is a mistake to surface rather than something to
        translate. User-authored Python migrations get to the SDK through
        ``context.db`` / ``context.raw_client``; internal, non-migration
        callers that need to write a single document use
        :meth:`upsert_native_item` instead of building SQL for this method
        to reject.

        Returns the number of rows a read produced (``0`` for the scalar
        liveness probe).
        """
        sql = sql.rstrip().rstrip(";").rstrip()
        self.log.debug(f"Executing Cosmos DB statement: {sql[:100]}...")

        sql_no_comments = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
        sql_no_comments = re.sub(r"/\*.*?\*/", "", sql_no_comments, flags=re.DOTALL)
        sql_upper = sql_no_comments.strip().upper()

        # ``SELECT 1`` (and similar) are connectivity probes. Cosmos has no
        # server-side SELECT without a container, so answer without binding
        # to one instead of failing on a container that need not exist.
        if sql_upper.startswith("SELECT") and " FROM " not in f" {sql_upper} ":
            self.log.debug("Short-circuiting scalar SELECT (no FROM) on CosmosDB")
            return 0

        if sql_upper.startswith("SELECT"):
            results = self.execute_query(connection, sql, params)
            return len(results) if results else 0

        raise NoSqlWriteNotSupportedError(
            f"CosmosDB executes SELECT only; received: {sql[:120]}. "
            "Container and document changes go through the Azure SDK. Write a "
            "Python migration exposing 'def migrate(context)' and use "
            "context.db (azure.cosmos.DatabaseProxy) or context.raw_client. "
            "See docs/user-guide/nosql-python-migrations.md."
        )

    def execute_query(
        self, connection: Any, sql: str, params: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute a SELECT query.

        Args:
            sql: SQL query to execute
            params: Optional parameters

        Returns:
            List of dictionaries, each representing a document
        """
        self.log.debug(f"Executing Cosmos DB query: {sql[:100]}...")

        try:
            # BUG-04: same scalar-SELECT short-circuit as execute_statement.
            # ``SELECT 1`` / ``SELECT CURRENT_TIMESTAMP`` have no FROM and
            # cannot bind to any container. Returning ``[]`` keeps callers
            # (liveness probes, smoke tests) working without the misleading
            # "container 'default' not found" fallback.
            stripped_sql = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
            stripped_sql = re.sub(r"/\*.*?\*/", "", stripped_sql, flags=re.DOTALL)
            stripped_upper = stripped_sql.strip().rstrip(";").strip().upper()
            if stripped_upper.startswith("SELECT") and " FROM " not in f" {stripped_upper} ":
                self.log.debug("Short-circuiting scalar SELECT (no FROM) on CosmosDB")
                return []

            # Get container client (need to determine container from query or use default)
            container_name = self._extract_container_from_query(sql)
            if not container_name:
                # Type guard: ensure we have CosmosDbConfig
                from dblift.db.plugins.cosmosdb.config import CosmosDbConfig

                cosmos_config = self.connection_manager.config.database
                if isinstance(cosmos_config, CosmosDbConfig):
                    container_name = cosmos_config.container_name or "default"
                else:
                    container_name = "default"
                self.log.warning(
                    f"No container specified in query, using default: {container_name}"
                )

            container_client = self.connection_manager.get_container_client(container_name)

            # Substitute positional ? placeholders before passing to CosmosDB SQL API.
            # No "?" in sql guard needed: _substitute_params validates count and raises
            # ValueError on mismatch, so stray ? without params surfaces immediately.
            if params is not None:
                sql = self._substitute_params(sql, params)

            # Normalize Cosmos DB SQL query - ensure container reference uses 'c' alias
            # Cosmos DB SQL API requires container alias in WHERE clauses
            normalized_sql = self._normalize_cosmos_sql(sql, container_name)

            # Execute query
            items = container_client.query_items(
                query=normalized_sql, enable_cross_partition_query=True
            )

            # Convert to list of dictionaries
            results = []
            for item in items:
                results.append(dict(item))

            self.log.debug(f"Query returned {len(results)} documents")

            return results

        except Exception as e:
            error_msg = f"Error executing Cosmos DB query: {str(e)}"
            self.log.error(error_msg)
            raise

    def upsert_native_item(self, container_name: str, document: Dict[str, Any]) -> Dict[str, Any]:
        """Upsert a document directly through the Azure SDK, bypassing SQL.

        ``execute_statement`` only accepts ``SELECT`` — the Cosmos DB SQL API
        is read-only, and pretending otherwise (the pseudo-SQL emulator this
        module used to have) was actively wrong, which is why the ADR
        removing pseudo-SQL deleted it. Container *creation* was ported to a
        native SDK call at the time (see
        ``CosmosDbProvider.create_snapshot_table_if_not_exists``, which calls
        ``CosmosDbSchemaOperations.create_container_if_not_exists`` instead of
        rendering ``CREATE TABLE``), but the matching write for a single
        document was missed: an internal caller such as the schema-snapshot
        repository still built a plain SQL ``INSERT`` and routed it through
        ``execute_statement``, which now raises
        ``NoSqlWriteNotSupportedError`` for anything but a ``SELECT``. That
        exception is swallowed by a best-effort event listener, so
        ``migrate`` reports success while the snapshot document silently
        never lands.

        This method provides the native, non-SQL escape hatch a caller needs
        to close that gap: it calls ``azure.cosmos.ContainerProxy.upsert_item``
        directly instead of rendering anything this executor — or its
        SELECT-only ``execute_statement`` — would have to parse as SQL. It is
        meant for internal dblift callers that hold a provider/query-executor
        reference and are not a user-authored migration; migrations already
        reach the SDK through ``context.db`` / ``context.raw_client`` (see
        ``execute_statement``'s docstring). This change adds the primitive
        only — the schema-snapshot repository still needs to be updated to
        call this instead of building an ``INSERT``; until that happens the
        gap above is not yet closed end-to-end.

        Args:
            container_name: Name of the Cosmos DB container to upsert into.
            document: The full document body to upsert. Must include
                whatever field the container's partition key path points at.

        Returns:
            The document as returned by the SDK (typically the input body
            plus Cosmos-assigned system properties such as ``_etag``,
            ``_ts``, ``_self``).
        """
        container_client = self.connection_manager.get_container_client(container_name)
        return cast(Dict[str, Any], container_client.upsert_item(body=document))

    def delete_native_item(self, container_name: str, item_id: str, partition_key: Any) -> None:
        """Delete a single document directly through the Azure SDK, bypassing SQL.

        A ``DELETE`` routed through ``execute_statement`` hits the identical
        ``NoSqlWriteNotSupportedError`` a write does, since Cosmos's SQL API
        is read-only regardless of which DML verb is used. Pruning old
        snapshots removes individual documents by id, and does that today by
        rendering a SQL ``DELETE``; this is the native path for it to use
        instead, the delete-side counterpart to :meth:`upsert_native_item`'s
        write-side fix.

        Args:
            container_name: Name of the Cosmos DB container to delete from.
            item_id: The document's ``id`` property.
            partition_key: The partition key VALUE for this document (not
                necessarily equal to item_id -- it's whatever value lives at
                the container's partition key path for this document).
        """
        container_client = self.connection_manager.get_container_client(container_name)
        container_client.delete_item(item=item_id, partition_key=partition_key)

    def list_native_items(self, container_name: str) -> List[Dict[str, Any]]:
        """Return every document in *container_name* via a native ``SELECT``.

        Cosmos DB's SQL API genuinely executes a ``SELECT``, unlike
        MongoDB's ``find()``-backed equivalent, so this issues
        ``SELECT * FROM c`` directly through the same container-client
        access pattern as :meth:`upsert_native_item` /
        :meth:`delete_native_item` above, rather than routing through
        :meth:`execute_query` (which exists to run caller-supplied SQL, not
        to hardcode this one shape).

        Ordering is not guaranteed: no ``ORDER BY`` is added, matching
        ``DocumentStoreProvider.list_native_items``'s contract that callers
        needing an order impose it themselves.

        The Azure SDK's ``query_items`` iterator can hang indefinitely
        against a container that does not exist, so this checks existence
        with :meth:`table_exists` first and returns an empty list for a
        missing container without ever calling ``query_items`` -- the same
        "no documents" answer MongoDB's ``find()`` gives for a missing
        collection, just reached by a guard instead of by iterating.

        Args:
            container_name: Name of the Cosmos DB container to read.

        Returns:
            Every document in the container, as plain dicts. Empty list if
            the container is empty or does not exist.
        """
        if not self.table_exists(None, "", container_name):
            return []
        container_client = self.connection_manager.get_container_client(container_name)
        items = container_client.query_items(
            query="SELECT * FROM c", enable_cross_partition_query=True
        )
        return [dict(item) for item in items]

    def _normalize_cosmos_sql(self, sql: str, container_name: str) -> str:
        """Normalize Cosmos DB SQL query to use proper container alias.

        Cosmos DB SQL API requires container alias (typically 'c') for all field references.
        This method ensures queries use proper syntax by:
        1. Adding 'c' alias to FROM clause if missing
        2. Adding 'c.' prefix to field references in SELECT list
        3. Adding 'c.' prefix to field references in WHERE clause
        4. Adding 'c.' prefix to field references in ORDER BY clause

        Args:
            sql: Original SQL query
            container_name: Container name

        Returns:
            Normalized SQL query
        """
        sql_upper = sql.upper()

        # Check if query already has container alias
        has_alias = " C." in sql_upper or " C[" in sql_upper
        has_from_alias = (
            "FROM " + container_name.upper() + " C" in sql_upper
            or "FROM " + container_name.upper() + " AS C" in sql_upper
        )

        # If already properly aliased, return as-is
        if has_alias and has_from_alias:
            return sql

        # For SELECT queries, normalize field references
        if sql_upper.strip().startswith("SELECT"):
            # Step 1: Ensure FROM clause has 'c' alias
            from_pattern = re.compile(
                rf"FROM\s+{re.escape(container_name)}\s*(?:\s|$)", re.IGNORECASE
            )
            if not has_from_alias:
                sql = from_pattern.sub(f"FROM {container_name} c ", sql, count=1)
                sql_upper = sql.upper()

            # Step 2: Normalize SELECT field list - add 'c.' prefix to unaliased fields
            # Match: SELECT field1, field2, field3 FROM ...
            select_match = re.search(r"SELECT\s+(.*?)\s+FROM", sql_upper, re.IGNORECASE | re.DOTALL)
            if select_match:
                select_clause = sql[select_match.start(1) : select_match.end(1)]
                # Split by comma, but handle quoted strings and nested parentheses
                fields = []
                current_field = ""
                paren_depth = 0
                in_quotes = False
                quote_char = None

                for char in select_clause:
                    if char in ("'", '"') and (not in_quotes or char == quote_char):
                        in_quotes = not in_quotes
                        quote_char = char if in_quotes else None
                        current_field += char
                    elif char == "(" and not in_quotes:
                        paren_depth += 1
                        current_field += char
                    elif char == ")" and not in_quotes:
                        paren_depth -= 1
                        current_field += char
                    elif char == "," and not in_quotes and paren_depth == 0:
                        fields.append(current_field.strip())
                        current_field = ""
                    else:
                        current_field += char

                if current_field.strip():
                    fields.append(current_field.strip())

                # Normalize each field - add 'c.' prefix if not already present
                normalized_fields = []
                for field in fields:
                    field_stripped = field.strip()
                    # Special case: SELECT * should remain as-is
                    if field_stripped == "*":
                        normalized_fields.append(field)
                    # Skip if already has alias (c.field, c['field'], or aggregate functions)
                    elif (
                        field_stripped.startswith("C.")
                        or field_stripped.startswith("C[")
                        or field_stripped.startswith("c.")
                        or field_stripped.startswith("c[")
                        or any(
                            func in field_stripped.upper()
                            for func in ["COUNT(", "SUM(", "AVG(", "MAX(", "MIN(", "DISTINCT "]
                        )
                    ):
                        normalized_fields.append(field)
                    else:
                        # Add 'c.' prefix
                        normalized_fields.append(f"c.{field_stripped}")

                # Reconstruct SELECT clause
                normalized_select = "SELECT " + ", ".join(normalized_fields)
                sql = sql[: select_match.start()] + normalized_select + sql[select_match.end(1) :]
                sql_upper = sql.upper()

            # Step 3: Normalize ORDER BY clause
            order_by_match = re.search(
                r"ORDER\s+BY\s+(.*?)(?:\s+(?:ASC|DESC))?(?:\s|$)", sql_upper, re.IGNORECASE
            )
            if order_by_match:
                order_by_clause = sql[order_by_match.start() : order_by_match.end()]
                # Add 'c.' prefix to field references in ORDER BY
                # Match field names that aren't already aliased
                order_by_normalized = re.sub(
                    r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b(?=\s*(?:ASC|DESC|,|$))",
                    lambda m: (
                        f"c.{m.group(1)}"
                        if m.group(1).upper() not in ("ASC", "DESC", "C")
                        and "c." not in order_by_clause[: m.start()]
                        else m.group(0)
                    ),
                    order_by_clause,
                    flags=re.IGNORECASE,
                )
                # Simple approach: replace bare field names with c.field.
                order_by_normalized = re.sub(
                    r"(?<!\.)\b([a-zA-Z_][a-zA-Z0-9_]*)\b",
                    lambda m: (
                        m.group(0)
                        if m.group(1).upper() in ("ORDER", "BY", "ASC", "DESC", "C")
                        else f"c.{m.group(1)}"
                    ),
                    order_by_clause,
                    flags=re.IGNORECASE,
                )
                sql = (
                    sql[: order_by_match.start()]
                    + order_by_normalized
                    + sql[order_by_match.end() :]
                )
                sql_upper = sql.upper()

            # Step 4: Normalize WHERE clause (existing logic)
            if "WHERE" in sql_upper:
                where_pos = sql_upper.find("WHERE")
                where_clause = sql[where_pos + 5 :].strip()
                # Extract WHERE clause up to ORDER BY or end
                order_by_pos = sql_upper.find("ORDER BY", where_pos)
                if order_by_pos > 0:
                    where_clause = sql[where_pos + 5 : order_by_pos].strip()
                else:
                    where_clause = sql[where_pos + 5 :].strip()

                if " C." not in sql_upper[where_pos:] and " C[" not in sql_upper[where_pos:]:
                    # Add 'c.' prefix to field references in WHERE clause
                    where_clause_normalized = re.sub(
                        r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b(?=\s*[=<>!])",
                        r"c.\1",
                        where_clause,
                        flags=re.IGNORECASE,
                    )
                    # Reconstruct SQL with normalized WHERE clause
                    if order_by_pos > 0:
                        sql = (
                            sql[: where_pos + 5]
                            + " "
                            + where_clause_normalized
                            + " "
                            + sql[order_by_pos:]
                        )
                    else:
                        sql = sql[: where_pos + 5] + " " + where_clause_normalized

        return sql

    def _extract_container_from_query(self, sql: str) -> Optional[str]:
        """Return the container a ``SELECT`` reads from, or ``None``.

        Only the ``FROM`` clause is inspected: this executor runs reads and
        nothing else, so the ``INTO`` / ``UPDATE`` / ``DELETE FROM`` forms the
        deleted write path needed no longer occur.

        Args:
            sql: Native Cosmos SQL query

        Returns:
            Container name if found, None otherwise (preserves original case)
        """
        sql_upper = sql.upper()
        if "FROM" not in sql_upper:
            return None
        from_pos = sql_upper.find("FROM")
        after_from = sql[from_pos + 4 :].strip()
        if not after_from:
            return None
        return after_from.split()[0].rstrip(";.,") or None

    @staticmethod
    def _substitute_params(sql_fragment: str, params: List[Any]) -> str:
        """Replace ``?`` placeholders with inlined literals.

        CosmosDB's SQL API does not accept positional ``?`` placeholders —
        they must be inlined as literals (or rewritten to ``@named``
        parameters, which we do not use here because callers pass a positional
        list). Strings are single-quoted and escaped; numbers/bools/None are
        rendered verbatim. Raises ``ValueError`` on placeholder/param mismatch
        so repair paths surface a clear error instead of silently deleting
        zero rows (B9-BUG-01).

        Args:
            sql_fragment: SQL text (full query or clause fragment) containing ``?`` placeholders.
            params: Positional parameter values.

        Returns:
            SQL text with placeholders replaced by inlined literals.

        Raises:
            ValueError: If the number of ``?`` placeholders does not match
                ``len(params)``.
        """
        pieces = sql_fragment.split("?")
        placeholder_count = len(pieces) - 1
        if placeholder_count != len(params):
            raise ValueError(
                f"Parameter count mismatch in SQL: "
                f"{placeholder_count} placeholder(s), {len(params)} param(s)"
            )
        if placeholder_count == 0:
            return sql_fragment

        def _lit(v: Any) -> str:
            if v is None:
                return "null"
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, (int, float)):
                return str(v)
            return "'" + str(v).replace("'", "''") + "'"

        rebuilt = pieces[0]
        for value, fragment in zip(params, pieces[1:]):
            rebuilt += _lit(value) + fragment
        return rebuilt

    def table_exists(self, connection: Any, schema: str, table_name: str) -> bool:
        """Check if a container exists in Cosmos DB.

        Args:
            schema: Schema name (not used in Cosmos DB, but kept for compatibility)
            table_name: Container name

        Returns:
            True if container exists, False otherwise
        """
        try:
            container_client = self.connection_manager.get_container_client(table_name)
            container_client.read()
            return True
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "notfound" in error_str or "404" in error_str:
                return False
            # For other errors, assume container doesn't exist
            return False

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Get fully qualified object name for Cosmos DB.

        Args:
            schema: Schema name (not used in Cosmos DB)
            object_name: Object name (container name)

        Returns:
            Object name (Cosmos DB doesn't use schema qualification)
        """
        # Cosmos DB doesn't use schema qualification
        return object_name

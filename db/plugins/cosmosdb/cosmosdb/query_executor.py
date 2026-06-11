"""
Cosmos DB query execution using SQL API.

This module handles SQL query execution against Cosmos DB using the SQL API.
"""

import json
import re
import time
from typing import Any, Dict, List, Optional

from core.logger import Log, NullLog
from db.plugins.base_query_executor import BaseQueryExecutor
from db.plugins.cosmosdb.sdk_translator._parsing import extract_container_name

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

    # Patterns that require SDK translation (not native SQL API)
    SDK_PATTERNS = [
        "DROP CONTAINER",
        "ALTER CONTAINER",
        "UPDATE CONTAINER",
        "SET CONTAINER",
        "SET THROUGHPUT",
        "SET AUTOSCALE",
        "SHOW THROUGHPUT",
        "CREATE INDEX",
        "DROP INDEX",
        "EXCLUDE INDEX",
        "INCLUDE INDEX",
        "SET TTL",
    ]

    @staticmethod
    def _is_transient_cosmos_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "serviceunavailable" in message
            or "service unavailable" in message
            or "503" in message
            or "timeout" in message
            or "timed out" in message
        )

    def _is_emulator_connection(self) -> bool:
        database_config = getattr(self.connection_manager.config, "database", None)
        endpoint = getattr(database_config, "account_endpoint", None) or getattr(
            database_config, "url", None
        )
        if not endpoint:
            return False
        return bool(self.connection_manager._is_emulator_endpoint(endpoint))

    def execute_statement(
        self,
        connection: Any,
        sql: str,
        params: Optional[List[Any]] = None,
        return_generated_keys: bool = False,
    ) -> int:
        """Execute a SQL statement (CREATE CONTAINER, INSERT, UPDATE, DELETE).

        Also handles pseudo-SQL statements that require Azure SDK operations.

        Supported pseudo-SQL syntax:
        - DROP CONTAINER <name>
        - ALTER CONTAINER <name> SET (...)
        - SET THROUGHPUT ON CONTAINER <name> TO <value>
        - SET AUTOSCALE ON CONTAINER <name> MAX <value>
        - SHOW THROUGHPUT ON CONTAINER <name>
        - CREATE INDEX <name> ON <container> (...)
        - DROP INDEX <name> ON <container>
        - EXCLUDE INDEX PATH '<path>' ON CONTAINER <name>
        - INCLUDE INDEX PATH '<path>' ON CONTAINER <name>
        - SET TTL ON CONTAINER <name> TO <value>

        Args:
            sql: SQL statement to execute
            params: Optional parameters (not commonly used in Cosmos DB SQL API)

        Returns:
            Number of rows affected
        """
        # CosmosDB SQL API does not use semicolons as statement terminators.
        # Strip trailing semicolons to avoid syntax errors from the API.
        sql = sql.rstrip().rstrip(";").rstrip()

        self.log.debug(f"Executing Cosmos DB statement: {sql[:100]}...")

        try:
            # Parse SQL to determine operation type
            # Remove comments first to get the actual SQL statement
            # Remove SQL comments (-- ... and /* ... */)
            sql_no_comments = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
            sql_no_comments = re.sub(r"/\*.*?\*/", "", sql_no_comments, flags=re.DOTALL)
            sql_upper = sql_no_comments.strip().upper()

            # BUG-04: short-circuit scalar ``SELECT <expr>`` with no FROM.
            # Callers like ``check_connection`` and migrations issue ``SELECT 1``
            # as a liveness probe. CosmosDB has no server-side SELECT without a
            # container, so we used to route this through ``execute_query`` and
            # fall back to a ``"default"`` container that typically does not
            # exist — producing a misleading "container not found" error for a
            # connectivity check. If parsing ever proved the connection live
            # (we got here), treat scalar SELECTs as a no-op success.
            if sql_upper.startswith("SELECT") and " FROM " not in f" {sql_upper} ":
                self.log.debug("Short-circuiting scalar SELECT (no FROM) on CosmosDB")
                return 0

            # Native SQL API operations
            if sql_upper.startswith("CREATE TABLE"):
                # Translate standard SQL CREATE TABLE to CosmosDB CREATE CONTAINER.
                # Extract the table name and optional PRIMARY KEY for partition key.
                normalized = self._normalize_create_table(sql)
                return self._execute_create_container(normalized)
            elif sql_upper.startswith("CREATE CONTAINER"):
                return self._execute_create_container(sql)
            elif sql_upper.startswith("DROP TABLE"):
                normalized = self._normalize_drop_table(sql)
                return self._execute_sdk_operation(normalized)
            elif sql_upper.startswith("DROP INDEX") and " ON " not in f" {sql_upper} ":
                self.log.warning(
                    "Ignoring DROP INDEX without container on CosmosDB; indexes are managed "
                    "through the container indexing policy."
                )
                return 0
            elif sql_upper.startswith("INSERT"):
                return self._execute_insert(sql, params)
            elif sql_upper.startswith("UPDATE") and not sql_upper.startswith("UPDATE CONTAINER"):
                # Regular UPDATE (not UPDATE CONTAINER which is SDK)
                return self._execute_update(sql, params)
            elif sql_upper.startswith("DELETE"):
                return self._execute_delete(sql, params)

            # SDK operations - route through translator
            elif any(sql_upper.startswith(pattern) for pattern in self.SDK_PATTERNS):
                return self._execute_sdk_operation(sql)

            else:
                # For other operations, try to execute as query
                # Some operations might return results
                results = self.execute_query(connection, sql, params)
                return len(results) if results else 0

        except Exception as e:
            # Transient ServiceUnavailable on emulator first-boot may be retried
            # by callers. Avoid logging an error wall for each retry attempt.
            error_msg = f"Error executing Cosmos DB statement: {str(e)}"
            msg_lower = str(e).lower()
            is_transient = (
                "serviceunavailable" in msg_lower
                or "service unavailable" in msg_lower
                or "503" in msg_lower
                or "timeout" in msg_lower
                or "timed out" in msg_lower
            )
            if is_transient:
                self.log.warning(error_msg)
            else:
                self.log.error(error_msg)
            raise

    def _execute_sdk_operation(self, sql: str) -> int:
        """Execute an operation via the SDK translator.

        Args:
            sql: Pseudo-SQL statement

        Returns:
            1 if successful, 0 otherwise
        """
        from core.state.sql_statement import SqlStatement
        from db.plugins.cosmosdb.sdk_translator import CosmosDbSdkTranslator

        # Create a statement for translation
        statement = SqlStatement(
            sql=sql,
            statement_type="SDK",
            object_type="CONTAINER",
            object_name="",
            dialect="cosmosdb",
            requires_sdk=True,
        )

        # Translate to SDK operation
        translator = CosmosDbSdkTranslator(self.connection_manager, None)
        operation = translator.translate_to_sdk_operation(statement)

        if not operation:
            raise ValueError(f"Could not translate statement to SDK operation: {sql}")

        # Check for parse errors
        if operation.get("operation") == "error":
            raise ValueError(operation.get("warning", f"Invalid statement: {sql}"))

        # Execute SDK operation
        success, error = translator.execute_sdk_operation(operation)
        if not success:
            raise RuntimeError(f"Failed to execute SDK operation: {error}")

        return 1

    # _execute_drop_container_via_sdk / _execute_alter_container_via_sdk
    # removed in Z-4: ``execute_statement`` routes both DROP and ALTER
    # through ``_execute_sdk_operation`` (matched by ``SDK_PATTERNS``);
    # the dedicated methods had zero callers in production or tests.

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
                from config.database_config import CosmosDbConfig

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
                # Simple approach: replace field names with c.field
                order_by_normalized = re.sub(
                    r"\b(item_id|captured_at|checksum|model_data|id|name|value|version|description|type|script|installed_by|installed_on|execution_time|success)\b",
                    r"c.\1",
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
                        r"\b(item_id|captured_at|checksum|model_data|id|name|value|version|description|type|script|installed_by|installed_on|execution_time|success)\b(?=\s*[=<>!])",
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
        """Extract container name from SQL query.

        Args:
            sql: SQL query

        Returns:
            Container name if found, None otherwise (preserves original case)
        """
        # Simple extraction - look for FROM clause (SELECT), INTO clause (INSERT), or UPDATE
        # Use case-insensitive search but preserve original case
        sql_upper = sql.upper()
        if "FROM" in sql_upper:
            # Find position in original string
            from_pos = sql_upper.find("FROM")
            after_from = sql[from_pos + 4 :].strip()
            container_part = after_from.split()[0] if after_from else None
            if container_part:
                # Remove any trailing punctuation
                container_part = container_part.rstrip(";.,")
                return container_part
        elif "INTO" in sql_upper:
            # INSERT INTO container_name ...
            into_pos = sql_upper.find("INTO")
            after_into = sql[into_pos + 4 :].strip()
            # Skip to container name (might have parentheses after)
            container_part = after_into.split()[0] if after_into else None
            if container_part:
                # Remove any trailing punctuation
                container_part = container_part.rstrip(";.,")
                return container_part
        elif "UPDATE" in sql_upper:
            # UPDATE container_name SET ...
            update_pos = sql_upper.find("UPDATE")
            after_update = sql[update_pos + 6 :].strip()
            container_part = after_update.split()[0] if after_update else None
            if container_part:
                # Remove any trailing punctuation
                container_part = container_part.rstrip(";.,")
                return container_part
        elif "DELETE" in sql_upper and "FROM" in sql_upper:
            # DELETE FROM container_name ...
            from_pos = sql_upper.find("FROM")
            after_from = sql[from_pos + 4 :].strip()
            container_part = after_from.split()[0] if after_from else None
            if container_part:
                # Remove any trailing punctuation
                container_part = container_part.rstrip(";.,")
                return container_part
        return None

    def _normalize_create_table(self, sql: str) -> str:
        """Translate ``CREATE TABLE <name> (...)`` to ``CREATE CONTAINER <name> (...)`` syntax.

        Extracts the PRIMARY KEY column (if present) and injects a ``WITH``
        clause so the partition key is set correctly.  Falls back to ``/id``
        when no PRIMARY KEY is found.

        Args:
            sql: Standard SQL ``CREATE TABLE`` statement

        Returns:
            Equivalent ``CREATE CONTAINER`` statement accepted by
            :meth:`_execute_create_container`.
        """
        sql_no_comments = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
        sql_no_comments = re.sub(r"/\*.*?\*/", "", sql_no_comments, flags=re.DOTALL)

        # Replace TABLE keyword with CONTAINER (first occurrence only)
        normalized = re.sub(
            r"\bTABLE\b", "CONTAINER", sql_no_comments, count=1, flags=re.IGNORECASE
        )

        # If a WITH clause is already present, leave it alone
        if re.search(r"\bWITH\s*\(", normalized, re.IGNORECASE):
            return normalized

        # Extract PRIMARY KEY column name from column definitions:
        # e.g. "id VARCHAR(255) PRIMARY KEY" or "PRIMARY KEY (id)"
        pk_col: Optional[str] = None
        # Scope the search to inside the outer parentheses so we don't
        # accidentally capture keywords like CREATE or TABLE.
        first_paren = sql_no_comments.find("(")
        last_paren = sql_no_comments.rfind(")")
        col_defs = (
            sql_no_comments[first_paren + 1 : last_paren]
            if first_paren != -1 and last_paren > first_paren
            else sql_no_comments
        )
        # Split the column-definition list on TOP-LEVEL commas so the
        # inline-PK search stays inside a single column definition.
        # The previous regex included ``,`` in its character class and
        # could span column boundaries, so a CREATE TABLE whose PK
        # was not the first column (e.g. ``name VARCHAR(100), id
        # VARCHAR(255) PRIMARY KEY``) returned the wrong partition
        # key. (PR #240 Bugbot.)
        inline_pk_col: Optional[str] = None
        depth = 0
        start = 0
        items: List[str] = []
        for idx, ch in enumerate(col_defs):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                items.append(col_defs[start:idx])
                start = idx + 1
        items.append(col_defs[start:])

        for item in items:
            stripped = item.strip()
            # Skip table-level ``PRIMARY KEY (col, ...)`` constraints —
            # those are picked up by the table_pk regex below.
            if re.match(r"PRIMARY\s+KEY\b", stripped, re.IGNORECASE):
                continue
            if re.search(r"\bPRIMARY\s+KEY\b", stripped, re.IGNORECASE):
                first_token = re.match(r"(\w+)", stripped)
                if first_token:
                    inline_pk_col = first_token.group(1)
                    break

        table_pk = re.search(
            r"\bPRIMARY\s+KEY\s*\(\s*(\w+)",
            col_defs,
            re.IGNORECASE,
        )
        if inline_pk_col:
            pk_col = inline_pk_col
        elif table_pk:
            pk_col = table_pk.group(1)

        partition_key = f"/{pk_col}" if pk_col else "/id"

        # Append WITH clause before the trailing semicolon (if any)
        normalized = normalized.rstrip().rstrip(";").rstrip()
        normalized = f"{normalized} WITH (partitionKey='{partition_key}')"
        return normalized

    def _normalize_drop_table(self, sql: str) -> str:
        """Translate ``DROP TABLE <name>`` to CosmosDB ``DROP CONTAINER <name>``."""
        sql_no_comments = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
        sql_no_comments = re.sub(r"/\*.*?\*/", "", sql_no_comments, flags=re.DOTALL)
        match = re.search(
            r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?P<name>[^\s(;]+)",
            sql_no_comments,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError(f"Could not parse table name from DROP TABLE statement: {sql}")

        name = match.group("name").rstrip(";.,")
        if "." in name:
            name = name.split(".")[-1]
        if len(name) >= 2:
            if (name[0] == '"' and name[-1] == '"') or (name[0] == "`" and name[-1] == "`"):
                name = name[1:-1]
            elif name[0] == "[" and name[-1] == "]":
                name = name[1:-1]
        return f"DROP CONTAINER {name}"

    def _execute_create_container(self, sql: str) -> int:
        """Execute CREATE CONTAINER statement.

        Args:
            sql: CREATE CONTAINER SQL statement
                Supported syntax:
                CREATE CONTAINER container_name (id STRING) WITH (
                    partitionKey='/id',
                    throughput=400,
                    indexingPolicy='{"indexingMode":"consistent","automatic":true}',
                    uniqueKeyPolicy='{"uniqueKeys":[{"paths":["/id"]}]}',
                    defaultTtl=3600,
                    analyticalStoreTtl=-1
                )

        Returns:
            1 if successful, 0 otherwise
        """
        # Parse CREATE CONTAINER statement with enhanced options
        container_name = self._parse_container_name(sql)
        container_options = self._parse_container_options(sql)

        try:
            from azure.cosmos import PartitionKey

            database = self.connection_manager.database
            if database is None:
                self.connection_manager.create_connection()
                database = self.connection_manager.database

            if database is None:
                raise RuntimeError("Failed to get database connection")

            # Check if container already exists first
            try:
                existing_container = database.get_container_client(container_name)
                existing_container.read()
                self.log.debug(f"Container {container_name} already exists")
                return 0  # Already existed
            except Exception:
                # Intentional: read() throws when container doesn't exist; proceed to create it
                pass

            # Extract partition key (required)
            partition_key = container_options.get("partitionKey", "/id")

            # Build container creation parameters
            create_kwargs: Dict[str, Any] = {
                "id": container_name,
                "partition_key": PartitionKey(path=partition_key),
            }

            # Add optional throughput
            if "throughput" in container_options:
                try:
                    throughput_value = int(container_options["throughput"])
                    # In Azure SDK, throughput can be set directly as an integer
                    # or using offer_throughput parameter
                    create_kwargs["offer_throughput"] = throughput_value
                except (ValueError, TypeError):
                    self.log.warning(
                        f"Invalid throughput value: {container_options['throughput']}, ignoring"
                    )

            # Add optional indexing policy
            # Azure Cosmos DB Python SDK accepts indexing_policy as a dict
            indexing_policy_dict = None
            if "indexingPolicy" in container_options:
                try:
                    indexing_policy_dict = json.loads(container_options["indexingPolicy"])
                    self.log.debug(f"Using custom indexing policy: {indexing_policy_dict}")
                except (json.JSONDecodeError, ValueError) as e:
                    self.log.warning(f"Invalid indexingPolicy JSON: {e}, ignoring")

            # Add optional unique key policy
            # Azure Cosmos DB Python SDK accepts unique_key_policy as a dict
            unique_key_policy_dict = None
            if "uniqueKeyPolicy" in container_options:
                try:
                    unique_key_policy_dict = json.loads(container_options["uniqueKeyPolicy"])
                    self.log.debug(f"Using custom unique key policy: {unique_key_policy_dict}")
                except (json.JSONDecodeError, ValueError) as e:
                    self.log.warning(f"Invalid uniqueKeyPolicy JSON: {e}, ignoring")

            # Add optional default TTL
            if "defaultTtl" in container_options:
                try:
                    default_ttl = int(container_options["defaultTtl"])
                    create_kwargs["default_ttl"] = default_ttl
                except (ValueError, TypeError):
                    self.log.warning(
                        f"Invalid defaultTtl value: {container_options['defaultTtl']}, ignoring"
                    )

            # Add optional analytical store TTL
            if "analyticalStoreTtl" in container_options:
                try:
                    analytical_store_ttl = int(container_options["analyticalStoreTtl"])
                    create_kwargs["analytical_store_ttl"] = analytical_store_ttl
                except (ValueError, TypeError):
                    self.log.warning(
                        "Invalid analyticalStoreTtl value: "
                        f"{container_options['analyticalStoreTtl']}, ignoring"
                    )

            # Create container with proper handling of advanced options
            # The Azure SDK accepts indexing_policy and unique_key_policy as dict parameters
            # We'll build the parameters dict and pass them to create_container_if_not_exists

            # Prepare creation parameters
            create_params = {
                "id": container_name,
                "partition_key": PartitionKey(path=partition_key),
            }

            # Add throughput if specified
            if "offer_throughput" in create_kwargs:
                create_params["offer_throughput"] = create_kwargs["offer_throughput"]

            # Add default TTL if specified (SDK accepts this directly)
            if "default_ttl" in create_kwargs:
                create_params["default_ttl"] = create_kwargs["default_ttl"]

            # Add indexing policy if provided
            # The SDK accepts indexing_policy as a dict
            if indexing_policy_dict:
                create_params["indexing_policy"] = indexing_policy_dict
                self.log.debug(f"Applying indexing policy: {indexing_policy_dict}")

            # Add unique key policy if provided
            # The SDK accepts unique_key_policy as a dict
            if unique_key_policy_dict:
                create_params["unique_key_policy"] = unique_key_policy_dict
                self.log.debug(f"Applying unique key policy: {unique_key_policy_dict}")

            # create_container_if_not_exists may raise CosmosResourceExistsError on conflict.
            # The returned proxy is discarded; the post-create read uses get_container_client.
            max_retries = 5 if self._is_emulator_connection() else 1
            for attempt in range(max_retries):
                try:
                    database.create_container_if_not_exists(**create_params)
                    # Small delay to ensure container is ready for operations
                    time.sleep(0.5)  # Increased delay for emulator

                    # Verify container was created
                    try:
                        verify_container = database.get_container_client(container_name)
                        verify_container.read()
                        self.log.debug(
                            f"Created and verified Cosmos DB container: {container_name}"
                        )
                    except Exception as verify_error:
                        self.log.warning(
                            f"Container {container_name} created but verification failed: "
                            f"{str(verify_error)}"
                        )
                        # Continue anyway - container might be propagating

                    return 1
                except Exception as create_error:
                    # Handle CosmosResourceExistsError specifically
                    error_str = str(create_error).lower()
                    error_type = type(create_error).__name__

                    # Check if it's a CosmosResourceExistsError (import might fail if SDK not available)
                    is_resource_exists_error = False
                    try:
                        from azure.cosmos.exceptions import CosmosResourceExistsError

                        is_resource_exists_error = isinstance(
                            create_error, CosmosResourceExistsError
                        )
                    except ImportError:
                        # SDK not available, check by error type name
                        is_resource_exists_error = (
                            "CosmosResourceExistsError" in error_type
                            or "ResourceExists" in error_type
                        )

                    if (
                        is_resource_exists_error
                        or "conflict" in error_str
                        or "already exists" in error_str
                    ):
                        # Container exists (this is expected), return 0
                        self.log.debug(
                            f"Container {container_name} already exists (handled conflict)"
                        )
                        return 0

                    if attempt < max_retries - 1 and self._is_transient_cosmos_error(create_error):
                        wait = 2.0**attempt
                        self.log.warning(
                            f"Cosmos DB container creation transient failure "
                            f"(attempt {attempt + 1}/{max_retries}): {create_error}. "
                            f"Retrying in {wait:.1f}s"
                        )
                        time.sleep(wait)
                        continue

                    raise
            raise RuntimeError(f"Failed to create Cosmos DB container: {container_name}")

        except Exception as e:
            # Container might already exist
            error_str = str(e).lower()
            if "conflict" in error_str or "already exists" in error_str:
                self.log.debug(f"Container {container_name} already exists")
                return 0
            raise

    def _execute_insert(self, sql: str, params: Optional[List[Any]] = None) -> int:
        """Execute INSERT statement.

        Args:
            sql: INSERT SQL statement
            params: Optional parameters for substitution

        Returns:
            Number of documents inserted
        """
        # Substitute positional ? placeholders first (parameterized queries and other
        # legacy callers use ? positional params). Must run before @paramN
        # substitution because _substitute_params inlines values as SQL literals,
        # which is what the VALUES parser below expects.
        if params is not None and "?" in sql:
            sql = self._substitute_params(sql, params)
            params = []  # consumed — prevent double-substitution below

        # If params are provided, substitute them into the SQL
        if params:
            # Find all @paramN placeholders and replace them with actual values
            param_pattern = re.compile(r"@param(\d+)")

            def replace_param(match: "re.Match[str]") -> str:
                """Substitute a Cosmos DB ``@paramN`` placeholder with its inlined SQL literal.

                ``match`` is the regex match for ``@param<N>``; the
                callback returns the SQL-literal form of ``params[N]``
                (single-quoted with embedded quotes doubled for strings,
                ``NULL`` for ``None``, ``str()`` otherwise) so the
                surrounding ``re.sub`` produces a self-contained query
                string. Out-of-range indices are passed through unchanged.
                """
                param_index = int(match.group(1))
                if param_index < len(params):
                    value = params[param_index]
                    # Quote string values, keep numbers as-is
                    if isinstance(value, str):
                        # Escape single quotes in strings
                        escaped_value = value.replace("'", "''")
                        return f"'{escaped_value}'"
                    elif value is None:
                        return "NULL"
                    else:
                        return str(value)
                return str(match.group(0))  # Keep original if index out of range

            sql = param_pattern.sub(replace_param, sql)

        # Parse INSERT statement and convert to document creation
        container_name = self._extract_container_from_query(sql)
        if not container_name:
            # Try using default container from config
            from config.database_config import CosmosDbConfig

            if isinstance(self.connection_manager.config.database, CosmosDbConfig):
                container_name = (
                    getattr(self.connection_manager.config.database, "container_name", None)
                    or "default"
                )
            else:
                container_name = "default"
            self.log.warning(
                f"No container found in INSERT statement, using default: {container_name}"
            )

        # Parse VALUES clause to extract document data
        # Format: INSERT INTO container_name (field1, field2) VALUES ('value1', value2)
        # Extract column names - match: INSERT INTO container (col1, col2)
        columns_match = re.search(r"INSERT\s+INTO\s+\w+\s*\((.*?)\)", sql, re.IGNORECASE)
        columns = []
        if columns_match:
            columns = [col.strip() for col in columns_match.group(1).split(",")]
        else:
            # Try without parentheses - INSERT INTO container VALUES (...)
            # In this case, we'll infer columns from values
            pass

        # Extract VALUES - match: VALUES ('val1', val2)
        values_match = re.search(r"VALUES\s*\((.*?)\)", sql, re.IGNORECASE | re.DOTALL)
        if not values_match:
            raise ValueError("VALUES clause not found in INSERT statement")

        values_str = values_match.group(1)
        # Simple parsing - split by comma, handle quoted strings
        values = []
        current_value = ""
        in_quotes = False
        quote_char = None

        for char in values_str:
            if char in ("'", '"') and (not in_quotes or char == quote_char):
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                else:
                    in_quotes = False
                    quote_char = None
                current_value += char
            elif char == "," and not in_quotes:
                values.append(current_value.strip())
                current_value = ""
            else:
                current_value += char

        if current_value.strip():
            values.append(current_value.strip())

        # Create document dictionary
        document = {}
        for i, col in enumerate(columns):
            if i < len(values):
                value = values[i].strip()
                # Check if value is quoted (string literal)
                is_quoted = (value.startswith("'") and value.endswith("'")) or (
                    value.startswith('"') and value.endswith('"')
                )

                # Remove quotes if present
                if is_quoted:
                    value = value[1:-1]

                # Special handling for 'id' field - must be a string in Cosmos DB
                if col.lower() == "id":
                    document[col] = str(value)  # Always string for id field
                elif col.lower() in ("model_data", "checksum"):
                    # model_data and checksum should always be strings (base64 encoded data)
                    document[col] = str(value)
                else:
                    # Try to parse as JSON object or array first, then number, then boolean
                    converted_value: Any = value
                    try:
                        # Check if value looks like JSON (starts with { or [)
                        if value.startswith("{") or value.startswith("["):
                            # Try to parse as JSON
                            converted_value = json.loads(value)
                            self.log.debug(
                                f"Parsed JSON value for column {col}: {type(converted_value).__name__}"
                            )
                        elif value.lower() in ("true", "false"):
                            # Handle boolean values (only if not quoted - quoted "true"/"false" are strings)
                            if not is_quoted:
                                converted_value = value.lower() == "true"
                                self.log.debug(
                                    f"Parsed boolean value for column {col}: {converted_value}"
                                )
                            else:
                                # Quoted boolean stays as string
                                converted_value = value
                        elif not is_quoted:
                            # Only try to convert to number if value was NOT quoted
                            # Quoted values should remain as strings
                            if "." in value:
                                converted_value = float(value)
                            else:
                                converted_value = int(value)
                        # If is_quoted is True and it's not JSON/boolean, keep as string
                    except (json.JSONDecodeError, ValueError):
                        # Not valid JSON, not a number, and not a boolean, keep as string
                        pass
                    document[col] = converted_value

        # Ensure 'id' field exists (required for Cosmos DB) and is a string
        if "id" not in document:
            # Use first column value or generate ID
            if columns and columns[0] in document:
                document["id"] = str(document[columns[0]])
            else:
                import uuid

                document["id"] = str(uuid.uuid4())
        else:
            # Ensure id is always a string
            document["id"] = str(document["id"])

        # Insert document with retry logic for container readiness
        max_retries = 3
        retry_delay = 0.5

        for attempt in range(max_retries):
            try:
                container_client = self.connection_manager.get_container_client(container_name)

                # Verify container exists before inserting
                try:
                    container_client.read()
                except Exception as read_error:
                    error_str = str(read_error).lower()
                    if "not found" in error_str or "notfound" in error_str or "404" in error_str:
                        if attempt < max_retries - 1:
                            # Container might not be ready yet, retry
                            self.log.debug(
                                f"Container {container_name} not ready yet, retrying... (attempt {attempt + 1}/{max_retries})"
                            )
                            time.sleep(retry_delay)
                            continue
                        error_msg = f"Container {container_name} does not exist. Create it first with CREATE CONTAINER."
                        self.log.error(error_msg)
                        raise ValueError(error_msg) from read_error
                    raise

                # Container exists, try to insert
                # Use upsert to handle conflicts (if document with same id exists, update it)
                try:
                    container_client.create_item(body=document)
                    self.log.debug(f"Inserted document into container {container_name}")
                    return 1
                except Exception as insert_error:
                    # If document with same ID exists, use upsert instead
                    error_str = str(insert_error).lower()
                    if (
                        "conflict" in error_str
                        or "already exists" in error_str
                        or "id" in error_str
                    ):
                        # Document with same ID exists, use upsert
                        container_client.upsert_item(body=document)
                        self.log.debug(
                            f"Upserted document into container {container_name} (id already existed)"
                        )
                        return 1
                    raise

            except ValueError:
                # Re-raise ValueError as-is
                raise
            except Exception as e:
                error_str = str(e).lower()
                if "not found" in error_str and attempt < max_retries - 1:
                    # Container might not be ready yet, retry
                    self.log.debug(
                        f"Container {container_name} not ready, retrying insert... (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(retry_delay)
                    continue
                error_msg = f"Error inserting document into container {container_name}: {str(e)}"
                self.log.error(error_msg)
                raise ValueError(error_msg) from e

        # Should not reach here, but just in case
        raise ValueError(
            f"Failed to insert document into container {container_name} after {max_retries} attempts"
        )

    def _execute_update(self, sql: str, params: Optional[List[Any]] = None) -> int:
        """Execute UPDATE statement.

        Args:
            sql: UPDATE SQL statement
            params: Optional parameters

        Returns:
            Number of documents updated
        """
        # Parse UPDATE statement
        # Format: UPDATE container_name SET field1=value1, field2=value2 WHERE condition
        sql.upper().strip()

        # Extract container name
        update_match = re.search(r"UPDATE\s+(\w+)", sql, re.IGNORECASE)
        if not update_match:
            raise ValueError("Could not parse container name from UPDATE statement")

        container_name = update_match.group(1)

        # Extract SET clause
        set_match = re.search(r"SET\s+(.+?)(?:\s+WHERE|$)", sql, re.IGNORECASE | re.DOTALL)
        if not set_match:
            raise ValueError("SET clause not found in UPDATE statement")

        set_clause = set_match.group(1).strip()

        # Parse field assignments (field=value, field=value)
        assignments = {}
        for assignment in set_clause.split(","):
            assignment = assignment.strip()
            if "=" in assignment:
                field, value_str = assignment.split("=", 1)
                field = field.strip()
                value_str = value_str.strip()
                # Remove quotes if present
                if (value_str.startswith("'") and value_str.endswith("'")) or (
                    value_str.startswith('"') and value_str.endswith('"')
                ):
                    value_str = value_str[1:-1]
                assignments[field] = value_str

        if not assignments:
            raise ValueError("No field assignments found in SET clause")

        # Extract WHERE clause
        where_clause = None
        where_match = re.search(r"WHERE\s+(.+?)$", sql, re.IGNORECASE | re.DOTALL)
        if where_match:
            where_clause = where_match.group(1).strip()

        # B9-BUG-01: ``?`` placeholders are positional and not supported by
        # CosmosDB SQL API — substitute them with quoted literals before
        # composing the SELECT (same root cause as DELETE).
        if where_clause and params:
            where_clause = self._substitute_params(where_clause, params)

        # Build query to find documents to update
        if where_clause:
            # Normalize WHERE clause for Cosmos DB
            query = f"SELECT * FROM c WHERE {self._normalize_where_clause(where_clause)}"
        else:
            # No WHERE clause - update all documents (use with caution)
            query = "SELECT * FROM c"

        # Execute update
        container_client = self.connection_manager.get_container_client(container_name)

        # Query documents to update
        items = container_client.query_items(query=query, enable_cross_partition_query=True)

        updated_count = 0
        for item in items:
            # Update fields in document
            for field, value_str in assignments.items():
                # Try to convert value to appropriate type
                converted_value: Any = value_str
                try:
                    if "." in value_str:
                        converted_value = float(value_str)
                    else:
                        converted_value = int(value_str)
                except ValueError:
                    pass  # Keep as string

                item[field] = converted_value

            # Update document in Cosmos DB
            try:
                container_client.replace_item(item=item["id"], body=item)
                updated_count += 1
            except Exception as e:
                self.log.warning(f"Error updating document {item.get('id', 'unknown')}: {str(e)}")
                # Continue with next document

        self.log.debug(f"Updated {updated_count} documents in container {container_name}")

        return updated_count

    def _execute_delete(self, sql: str, params: Optional[List[Any]] = None) -> int:
        """Execute DELETE statement.

        Args:
            sql: DELETE SQL statement
            params: Optional parameters

        Returns:
            Number of documents deleted
        """
        # Parse DELETE statement
        # Format: DELETE FROM container_name WHERE condition
        sql.upper().strip()

        # Extract container name
        delete_match = re.search(r"DELETE\s+FROM\s+(\w+)", sql, re.IGNORECASE)
        if not delete_match:
            raise ValueError("Could not parse container name from DELETE statement")

        container_name = delete_match.group(1)

        # Extract WHERE clause
        where_clause = None
        where_match = re.search(r"WHERE\s+(.+?)$", sql, re.IGNORECASE | re.DOTALL)
        if where_match:
            where_clause = where_match.group(1).strip()
        else:
            # No WHERE clause - this is dangerous, but we'll allow it with a warning
            self.log.warning("DELETE statement without WHERE clause - will delete all documents")

        # B9-BUG-01: ``?`` placeholders are positional and are not supported by
        # the CosmosDB SQL API. If ``params`` were passed (e.g. by
        # ``repair_command`` to delete a specific ``script = ?`` row) they
        # used to be silently dropped, the literal ``?`` matched nothing, and
        # repair reported "no rows affected" while the failed migration
        # remained in history. Substitute placeholders with quoted/typed
        # literals before building the SELECT.
        if where_clause and params:
            where_clause = self._substitute_params(where_clause, params)

        # Execute delete
        container_client = self.connection_manager.get_container_client(container_name)

        # Determine the container's actual partition key field so we can SELECT it and
        # pass the correct value to delete_item. c._partitionKey is not a queryable field
        # in CosmosDB SQL; we must read the container's partitionKey path instead.
        try:
            container_props = container_client.read()
            pk_path = container_props.get("partitionKey", {}).get("paths", ["/id"])[0]
        except Exception:
            pk_path = "/id"
        pk_field = pk_path.lstrip("/")

        # Rebuild query to SELECT the real partition key field.
        # When pk_field is "id" the partition key IS the document id — avoid
        # selecting the same property twice which CosmosDB rejects with 400.
        if pk_field == "id":
            select_clause = "c.id"
        else:
            select_clause = f"c.id, c.{pk_field}"

        if where_clause:
            query = (
                f"SELECT {select_clause} FROM c WHERE {self._normalize_where_clause(where_clause)}"
            )
        else:
            query = f"SELECT {select_clause} FROM c"

        # Query documents to delete
        items = container_client.query_items(query=query, enable_cross_partition_query=True)

        deleted_count = 0
        for item in items:
            doc_id = item.get("id")
            if not doc_id:
                continue

            # Get partition key from the actual PK field
            partition_key = item.get(pk_field)

            try:
                # Delete document.
                # BUG-05: when ``_partitionKey`` is absent the document lives
                # in a partition-keyless container (or the repair path for
                # ``dblift_schema_history`` R__ entries). Falling back to
                # ``partition_key=doc_id`` sent deletes to a partition that
                # did not match, so Cosmos returned 404 and repair silently
                # left duplicate history rows behind. Use the SDK's
                # ``PartitionKey.NonePartitionKeyValue`` sentinel when the
                # document has no partition key field.
                if partition_key:
                    container_client.delete_item(item=doc_id, partition_key=partition_key)
                else:
                    from db.plugins.cosmosdb.cosmosdb._sdk import NONE_PARTITION_KEY

                    container_client.delete_item(
                        item=doc_id,
                        partition_key=NONE_PARTITION_KEY,
                    )
                deleted_count += 1
            except Exception as e:
                error_str = str(e)
                if (
                    "NotFound" in error_str
                    or "not found" in error_str.lower()
                    or "404" in error_str
                ):
                    # Document already deleted (e.g. by a prior repair run). Expected.
                    self.log.debug(f"Document {doc_id} already deleted (skipping): {error_str}")
                else:
                    self.log.warning(f"Error deleting document {doc_id}: {error_str}")
                # Continue with next document

        self.log.debug(f"Deleted {deleted_count} documents from container {container_name}")

        return deleted_count

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

    def _normalize_where_clause(self, where_clause: str) -> str:
        """
        Normalize WHERE clause for Cosmos DB SQL API.

        Cosmos DB requires container alias 'c' in WHERE clauses.
        This method adds the alias if missing.

        Args:
            where_clause: Original WHERE clause

        Returns:
            Normalized WHERE clause with container alias
        """
        # If clause already has 'c.' references, return as-is
        if " c." in where_clause.upper() or where_clause.upper().startswith("C."):
            return where_clause

        # Add 'c.' prefix to field references
        # Simple pattern: word boundary, field name, whitespace or operator
        normalized = re.sub(
            r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*([=<>!]+)", r"c.\1 \2", where_clause, flags=re.IGNORECASE
        )
        normalized = re.sub(
            r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s+(IN)\b",
            r"c.\1 \2",
            normalized,
            flags=re.IGNORECASE,
        )

        return normalized

    def _parse_container_name(self, sql: str) -> str:
        """Parse container name from CREATE CONTAINER statement.

        Args:
            sql: CREATE CONTAINER SQL statement

        Returns:
            Container name (preserves original case)
        """
        container_name = extract_container_name(
            sql,
            ("CREATE",),
            allow_if_not_exists=True,
        )
        if not container_name:
            raise ValueError("Could not parse container name from CREATE CONTAINER statement")
        return container_name

    # _parse_partition_key removed in Z-4: no production caller. Tests
    # exercising the function are deleted along with it. The container
    # partition key is parsed inline by ``_parse_container_options``.

    def _parse_container_options(self, sql: str) -> Dict[str, Any]:
        """Parse all container options from CREATE CONTAINER statement.

        Args:
            sql: CREATE CONTAINER SQL statement

        Returns:
            Dictionary of container options
        """
        options = {}

        # Extract WITH clause
        with_match = re.search(r"WITH\s*\((.*?)\)", sql, re.IGNORECASE | re.DOTALL)
        if not with_match:
            # No WITH clause, use defaults
            options["partitionKey"] = "/id"
            return options

        with_clause = with_match.group(1)

        # Parse key-value pairs in WITH clause
        # Pattern: key='value' or key=value
        # Handle both quoted and unquoted values, including JSON strings with nested quotes
        # Use a more sophisticated approach to handle nested quotes in JSON strings
        # Split by commas, but be careful with commas inside quoted strings
        parts = []
        current_part = ""
        in_quotes = False
        quote_char = None
        i = 0
        while i < len(with_clause):
            char = with_clause[i]
            if char in ("'", '"') and (i == 0 or with_clause[i - 1] != "\\"):
                if not in_quotes:
                    in_quotes = True
                    quote_char = char
                elif char == quote_char:
                    in_quotes = False
                    quote_char = None
                current_part += char
            elif char == "," and not in_quotes:
                if current_part.strip():
                    parts.append(current_part.strip())
                current_part = ""
            else:
                current_part += char
            i += 1
        if current_part.strip():
            parts.append(current_part.strip())

        # Now parse each part as key=value
        for part in parts:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            value = value.strip()

            # Remove quotes if present (handle both single and double quotes)
            if len(value) >= 2:
                if (value.startswith("'") and value.endswith("'")) or (
                    value.startswith('"') and value.endswith('"')
                ):
                    value = value[1:-1]

            # Normalize key names
            key_lower = key.lower()
            if key_lower == "partitionkey":
                options["partitionKey"] = value
            elif key_lower == "throughput":
                options["throughput"] = value
            elif key_lower == "indexingpolicy":
                options["indexingPolicy"] = value
            elif key_lower == "uniquekeypolicy":
                options["uniqueKeyPolicy"] = value
            elif key_lower == "defaultttl":
                options["defaultTtl"] = value
            elif key_lower == "analyticalstorettl":
                options["analyticalStoreTtl"] = value

        # Ensure partitionKey is set (default if not specified)
        if "partitionKey" not in options:
            options["partitionKey"] = "/id"

        return options

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

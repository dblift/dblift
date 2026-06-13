"""CosmosDB SDK Translator Mixin — translate_* methods and parser helpers.

This module contains the _CosmosDbTranslatorMixin class which implements
all pseudo-SQL to SDK translation methods for CosmosDB operations.
"""

import json
import re
from typing import Any, Dict, Optional

from core.sql_generator.sql_statement import SqlStatement
from db.plugins.cosmosdb.sdk_translator._parsing import extract_container_name


class _CosmosDbTranslatorMixin:
    """Mixin providing all _translate_* methods and parser helpers."""

    # Must be provided by the concrete class
    connection_manager: Any
    log: Any

    # =========================================================================
    # Container Operations
    # =========================================================================

    def _translate_drop_container(self, statement: SqlStatement) -> Dict[str, Any]:
        """Translate DROP CONTAINER to SDK delete_container operation.

        Args:
            statement: DROP CONTAINER statement

        Returns:
            SDK operation dictionary
        """
        # Parse container name from SQL
        # Format: DROP CONTAINER container_name [IF EXISTS]
        container_name = self._extract_container_name(statement.sql, statement)

        return {
            "operation": "delete_container",
            "container_name": container_name,
            "parameters": {},
            "python_code": f"database.delete_container(container='{container_name}')",
            "description": f"Delete container '{container_name}' and all its data",
            "warning": "This operation will DELETE ALL DATA in the container. This cannot be undone.",
        }

    def _translate_alter_container(self, statement: SqlStatement) -> Dict[str, Any]:
        """Translate ALTER CONTAINER to SDK replace_container operation.

        Args:
            statement: ALTER CONTAINER statement

        Returns:
            SDK operation dictionary
        """
        # Parse container name and properties from SQL
        # Format: ALTER CONTAINER container_name SET (property=value, ...)
        container_name = self._extract_container_name(statement.sql)
        properties = self._parse_container_properties(statement.sql)

        # Build SDK parameters
        sdk_params: Dict[str, Any] = {}
        python_code_parts = []

        # Handle throughput
        if "throughput" in properties:
            throughput = int(properties["throughput"])
            sdk_params["offer_throughput"] = throughput
            python_code_parts.append(f"offer_throughput={throughput}")

        # Handle indexing policy
        if "indexingPolicy" in properties:
            try:
                indexing_policy = json.loads(properties["indexingPolicy"])
                sdk_params["indexing_policy"] = indexing_policy
                python_code_parts.append(f"indexing_policy={json.dumps(indexing_policy)}")
            except json.JSONDecodeError:
                self.log.warning(f"Invalid indexingPolicy JSON in statement: {statement.sql}")

        # Handle unique key policy
        if "uniqueKeyPolicy" in properties:
            try:
                unique_key_policy = json.loads(properties["uniqueKeyPolicy"])
                sdk_params["unique_key_policy"] = unique_key_policy
                python_code_parts.append(f"unique_key_policy={json.dumps(unique_key_policy)}")
            except json.JSONDecodeError:
                self.log.warning(f"Invalid uniqueKeyPolicy JSON in statement: {statement.sql}")

        # Handle default TTL
        if "defaultTtl" in properties:
            default_ttl = int(properties["defaultTtl"])
            sdk_params["default_ttl"] = default_ttl
            python_code_parts.append(f"default_ttl={default_ttl}")

        # Handle analytical store TTL
        if "analyticalStoreTtl" in properties:
            analytical_store_ttl = int(properties["analyticalStoreTtl"])
            sdk_params["analytical_store_ttl"] = analytical_store_ttl
            python_code_parts.append(f"analytical_store_ttl={analytical_store_ttl}")

        # Build Python code
        if python_code_parts:
            python_code = f"container_client.replace_container({', '.join(python_code_parts)})"
        else:
            python_code = f"# No properties to update for container '{container_name}'"

        return {
            "operation": "replace_container",
            "container_name": container_name,
            "parameters": sdk_params,
            "python_code": python_code,
            "description": f"Update container '{container_name}' properties",
            "note": "Note: Partition key cannot be changed after container creation",
        }

    def _translate_set_container(self, statement: SqlStatement) -> Dict[str, Any]:
        """Translate SET CONTAINER to SDK operation (alias for ALTER CONTAINER).

        Args:
            statement: SET CONTAINER statement

        Returns:
            SDK operation dictionary
        """
        return self._translate_alter_container(statement)

    # =========================================================================
    # Throughput Operations
    # =========================================================================

    def _translate_set_throughput(self, statement: SqlStatement) -> Dict[str, Any]:
        """Translate SET THROUGHPUT ON CONTAINER to SDK operation.

        Syntax: SET THROUGHPUT ON CONTAINER <name> TO <value>

        Args:
            statement: SET THROUGHPUT statement

        Returns:
            SDK operation dictionary
        """
        sql = statement.sql
        # Parse: SET THROUGHPUT ON CONTAINER users TO 1000
        match = re.search(
            r"SET\s+THROUGHPUT\s+ON\s+CONTAINER\s+(\w+)\s+TO\s+(\d+)",
            sql,
            re.IGNORECASE,
        )

        if not match:
            return {
                "operation": "error",
                "container_name": "unknown",
                "parameters": {},
                "python_code": "# Error: Could not parse SET THROUGHPUT statement",
                "description": "Failed to parse SET THROUGHPUT statement",
                "warning": f"Invalid syntax: {sql}",
            }

        container_name = match.group(1)
        throughput = int(match.group(2))

        # Get current throughput for undo
        current_throughput = self._get_current_throughput(container_name)
        undo_sql = None
        if current_throughput:
            undo_sql = f"SET THROUGHPUT ON CONTAINER {container_name} TO {current_throughput}"

        return {
            "operation": "set_throughput",
            "container_name": container_name,
            "parameters": {
                "throughput": throughput,
                "throughput_type": "fixed",
            },
            "python_code": f"container_client.replace_throughput({throughput})",
            "description": f"Set fixed throughput on container '{container_name}' to {throughput} RU/s",
            "note": f"This will set a fixed provisioned throughput of {throughput} RU/s",
            "undo_sql": undo_sql,
        }

    def _translate_set_autoscale(self, statement: SqlStatement) -> Dict[str, Any]:
        """Translate SET AUTOSCALE ON CONTAINER to SDK operation.

        Syntax: SET AUTOSCALE ON CONTAINER <name> MAX <max_throughput> [MIN <min_throughput>]

        Args:
            statement: SET AUTOSCALE statement

        Returns:
            SDK operation dictionary
        """
        sql = statement.sql
        # Parse: SET AUTOSCALE ON CONTAINER users MAX 4000 [MIN 400]
        match = re.search(
            r"SET\s+AUTOSCALE\s+ON\s+CONTAINER\s+(\w+)\s+MAX\s+(\d+)(?:\s+MIN\s+(\d+))?",
            sql,
            re.IGNORECASE,
        )

        if not match:
            return {
                "operation": "error",
                "container_name": "unknown",
                "parameters": {},
                "python_code": "# Error: Could not parse SET AUTOSCALE statement",
                "description": "Failed to parse SET AUTOSCALE statement",
                "warning": f"Invalid syntax: {sql}",
            }

        container_name = match.group(1)
        max_throughput = int(match.group(2))
        # Min throughput defaults to 10% of max (Cosmos DB default)
        min_throughput = int(match.group(3)) if match.group(3) else max_throughput // 10

        # Get current throughput for undo
        current_throughput = self._get_current_throughput(container_name)
        undo_sql = None
        if current_throughput:
            undo_sql = f"SET THROUGHPUT ON CONTAINER {container_name} TO {current_throughput}"

        python_code = f"""from azure.cosmos import ThroughputProperties
throughput_properties = ThroughputProperties(auto_scale_max_throughput={max_throughput})
container_client.replace_throughput(throughput_properties)"""

        return {
            "operation": "set_autoscale",
            "container_name": container_name,
            "parameters": {
                "max_throughput": max_throughput,
                "min_throughput": min_throughput,
                "throughput_type": "autoscale",
            },
            "python_code": python_code,
            "description": f"Set autoscale throughput on container '{container_name}' (max: {max_throughput} RU/s)",
            "note": f"Autoscale will automatically adjust between {min_throughput}-{max_throughput} RU/s based on load",
            "undo_sql": undo_sql,
        }

    def _translate_show_throughput(self, statement: SqlStatement) -> Dict[str, Any]:
        """Translate SHOW THROUGHPUT ON CONTAINER to SDK operation.

        Syntax: SHOW THROUGHPUT ON CONTAINER <name>

        Args:
            statement: SHOW THROUGHPUT statement

        Returns:
            SDK operation dictionary
        """
        sql = statement.sql
        # Parse: SHOW THROUGHPUT ON CONTAINER users
        match = re.search(
            r"SHOW\s+THROUGHPUT\s+ON\s+CONTAINER\s+(\w+)",
            sql,
            re.IGNORECASE,
        )

        if not match:
            return {
                "operation": "error",
                "container_name": "unknown",
                "parameters": {},
                "python_code": "# Error: Could not parse SHOW THROUGHPUT statement",
                "description": "Failed to parse SHOW THROUGHPUT statement",
            }

        container_name = match.group(1)

        python_code = """offer = container_client.read_offer()
print(f"Throughput: {offer.offer_throughput} RU/s")
print(f"Type: {'Autoscale' if offer.properties.get('content', {}).get('offerAutopilotSettings') else 'Fixed'}")"""

        return {
            "operation": "show_throughput",
            "container_name": container_name,
            "parameters": {},
            "python_code": python_code,
            "description": f"Show current throughput settings for container '{container_name}'",
            "note": "This is a read-only operation",
        }

    # =========================================================================
    # Index Operations
    # =========================================================================

    def _translate_create_index(self, statement: SqlStatement) -> Dict[str, Any]:
        """Translate CREATE INDEX to SDK operation (composite index).

        Syntax: CREATE INDEX <name> ON <container> (<column> [ASC|DESC], ...)

        Args:
            statement: CREATE INDEX statement

        Returns:
            SDK operation dictionary
        """
        sql = statement.sql
        # Parse: CREATE INDEX idx_name ON users (name ASC, age DESC)
        match = re.search(
            r"CREATE\s+INDEX\s+(\w+)\s+ON\s+(\w+)\s*\(([^)]+)\)",
            sql,
            re.IGNORECASE,
        )

        if not match:
            return {
                "operation": "error",
                "container_name": "unknown",
                "parameters": {},
                "python_code": "# Error: Could not parse CREATE INDEX statement",
                "description": "Failed to parse CREATE INDEX statement",
                "warning": f"Invalid syntax: {sql}",
            }

        index_name = match.group(1)
        container_name = match.group(2)
        columns_str = match.group(3)

        # Parse columns with optional order
        columns = []
        for col_part in columns_str.split(","):
            col_part = col_part.strip()
            parts = col_part.split()
            col_name = parts[0].strip()
            order = "ascending"  # Default
            if len(parts) > 1:
                order = "descending" if parts[1].upper() == "DESC" else "ascending"
            # Cosmos DB uses path notation
            path = f"/{col_name}" if not col_name.startswith("/") else col_name
            columns.append({"path": path, "order": order})

        # Generate undo SQL
        undo_sql = f"DROP INDEX {index_name} ON {container_name}"

        python_code = f"""# Add composite index to container '{container_name}'
container_client = database.get_container_client('{container_name}')
container_props = container_client.read()
indexing_policy = container_props.get('indexingPolicy', {{}})
composite_indexes = indexing_policy.get('compositeIndexes', [])

# New composite index: {index_name}
new_index = {json.dumps(columns, indent=4)}
composite_indexes.append(new_index)
indexing_policy['compositeIndexes'] = composite_indexes

# Update container with new indexing policy
container_client.replace_container(
    partition_key=container_props['partitionKey'],
    indexing_policy=indexing_policy
)"""

        return {
            "operation": "create_composite_index",
            "container_name": container_name,
            "parameters": {
                "index_name": index_name,
                "columns": columns,
            },
            "python_code": python_code,
            "description": f"Create composite index '{index_name}' on container '{container_name}'",
            "note": "Composite indexes improve query performance for queries with multiple ORDER BY clauses",
            "undo_sql": undo_sql,
        }

    def _translate_drop_index(self, statement: SqlStatement) -> Dict[str, Any]:
        """Translate DROP INDEX to SDK operation.

        Syntax: DROP INDEX <name> ON <container>

        Args:
            statement: DROP INDEX statement

        Returns:
            SDK operation dictionary
        """
        sql = statement.sql
        # Parse: DROP INDEX idx_name ON users
        match = re.search(
            r"DROP\s+INDEX\s+(\w+)\s+ON\s+(\w+)",
            sql,
            re.IGNORECASE,
        )

        if not match:
            return {
                "operation": "error",
                "container_name": "unknown",
                "parameters": {},
                "python_code": "# Error: Could not parse DROP INDEX statement",
                "description": "Failed to parse DROP INDEX statement",
                "warning": f"Invalid syntax: {sql}",
            }

        index_name = match.group(1)
        container_name = match.group(2)

        python_code = f"""# Remove composite index from container '{container_name}'
# Note: You need to identify which composite index to remove based on its structure
container_client = database.get_container_client('{container_name}')
container_props = container_client.read()
indexing_policy = container_props.get('indexingPolicy', {{}})
composite_indexes = indexing_policy.get('compositeIndexes', [])

# Remove the index (you may need to identify it by its structure)
# composite_indexes = [idx for idx in composite_indexes if not matches_index(idx, '{index_name}')]
indexing_policy['compositeIndexes'] = composite_indexes

container_client.replace_container(
    partition_key=container_props['partitionKey'],
    indexing_policy=indexing_policy
)"""

        return {
            "operation": "drop_composite_index",
            "container_name": container_name,
            "parameters": {
                "index_name": index_name,
            },
            "python_code": python_code,
            "description": f"Drop composite index '{index_name}' from container '{container_name}'",
            "warning": "Dropping an index may impact query performance",
        }

    def _translate_exclude_index_path(self, statement: SqlStatement) -> Dict[str, Any]:
        """Translate EXCLUDE INDEX PATH to SDK operation.

        Syntax: EXCLUDE INDEX PATH '<path>' ON CONTAINER <name>

        Args:
            statement: EXCLUDE INDEX PATH statement

        Returns:
            SDK operation dictionary
        """
        sql = statement.sql
        # Parse: EXCLUDE INDEX PATH '/largeText/*' ON CONTAINER users
        match = re.search(
            r"EXCLUDE\s+INDEX\s+PATH\s+['\"]([^'\"]+)['\"]\s+ON\s+CONTAINER\s+(\w+)",
            sql,
            re.IGNORECASE,
        )

        if not match:
            return {
                "operation": "error",
                "container_name": "unknown",
                "parameters": {},
                "python_code": "# Error: Could not parse EXCLUDE INDEX PATH statement",
                "description": "Failed to parse EXCLUDE INDEX PATH statement",
                "warning": f"Invalid syntax: {sql}",
            }

        path = match.group(1)
        container_name = match.group(2)

        # Generate undo SQL
        undo_sql = f"INCLUDE INDEX PATH '{path}' ON CONTAINER {container_name}"

        python_code = f"""# Exclude path from indexing on container '{container_name}'
container_client = database.get_container_client('{container_name}')
container_props = container_client.read()
indexing_policy = container_props.get('indexingPolicy', {{}})
excluded_paths = indexing_policy.get('excludedPaths', [])

# Add path to excluded paths
excluded_paths.append({{"path": "{path}"}})
indexing_policy['excludedPaths'] = excluded_paths

container_client.replace_container(
    partition_key=container_props['partitionKey'],
    indexing_policy=indexing_policy
)"""

        return {
            "operation": "exclude_index_path",
            "container_name": container_name,
            "parameters": {
                "path": path,
            },
            "python_code": python_code,
            "description": f"Exclude path '{path}' from indexing on container '{container_name}'",
            "note": "Excluding paths from indexing reduces RU consumption for writes but may impact query performance",
            "undo_sql": undo_sql,
        }

    def _translate_include_index_path(self, statement: SqlStatement) -> Dict[str, Any]:
        """Translate INCLUDE INDEX PATH to SDK operation.

        Syntax: INCLUDE INDEX PATH '<path>' ON CONTAINER <name>

        Args:
            statement: INCLUDE INDEX PATH statement

        Returns:
            SDK operation dictionary
        """
        sql = statement.sql
        # Parse: INCLUDE INDEX PATH '/importantField/*' ON CONTAINER users
        match = re.search(
            r"INCLUDE\s+INDEX\s+PATH\s+['\"]([^'\"]+)['\"]\s+ON\s+CONTAINER\s+(\w+)",
            sql,
            re.IGNORECASE,
        )

        if not match:
            return {
                "operation": "error",
                "container_name": "unknown",
                "parameters": {},
                "python_code": "# Error: Could not parse INCLUDE INDEX PATH statement",
                "description": "Failed to parse INCLUDE INDEX PATH statement",
                "warning": f"Invalid syntax: {sql}",
            }

        path = match.group(1)
        container_name = match.group(2)

        # Generate undo SQL
        undo_sql = f"EXCLUDE INDEX PATH '{path}' ON CONTAINER {container_name}"

        python_code = f"""# Include path in indexing on container '{container_name}'
container_client = database.get_container_client('{container_name}')
container_props = container_client.read()
indexing_policy = container_props.get('indexingPolicy', {{}})
included_paths = indexing_policy.get('includedPaths', [])

# Add path to included paths
included_paths.append({{"path": "{path}"}})
indexing_policy['includedPaths'] = included_paths

# Also remove from excluded paths if present
excluded_paths = indexing_policy.get('excludedPaths', [])
excluded_paths = [p for p in excluded_paths if p.get('path') != "{path}"]
indexing_policy['excludedPaths'] = excluded_paths

container_client.replace_container(
    partition_key=container_props['partitionKey'],
    indexing_policy=indexing_policy
)"""

        return {
            "operation": "include_index_path",
            "container_name": container_name,
            "parameters": {
                "path": path,
            },
            "python_code": python_code,
            "description": f"Include path '{path}' in indexing on container '{container_name}'",
            "note": "Including paths ensures they are indexed for query performance",
            "undo_sql": undo_sql,
        }

    # =========================================================================
    # TTL Operations
    # =========================================================================

    def _translate_set_ttl(self, statement: SqlStatement) -> Dict[str, Any]:
        """Translate SET TTL ON CONTAINER to SDK operation.

        Syntax: SET TTL ON CONTAINER <name> TO <seconds>
                SET TTL ON CONTAINER <name> TO OFF

        Args:
            statement: SET TTL statement

        Returns:
            SDK operation dictionary
        """
        sql = statement.sql

        # Parse: SET TTL ON CONTAINER users TO 3600
        # Or: SET TTL ON CONTAINER users TO OFF
        match = re.search(
            r"SET\s+TTL\s+ON\s+CONTAINER\s+(\w+)\s+TO\s+(\w+|\d+)",
            sql,
            re.IGNORECASE,
        )

        if not match:
            return {
                "operation": "error",
                "container_name": "unknown",
                "parameters": {},
                "python_code": "# Error: Could not parse SET TTL statement",
                "description": "Failed to parse SET TTL statement",
                "warning": f"Invalid syntax: {sql}",
            }

        container_name = match.group(1)
        ttl_value = match.group(2)

        # Handle OFF case
        if ttl_value.upper() == "OFF":
            ttl_seconds = None
            description = f"Disable TTL on container '{container_name}'"
            python_code = f"""container_client = database.get_container_client('{container_name}')
container_props = container_client.read()
# Remove default_ttl to disable TTL
if 'defaultTtl' in container_props:
    del container_props['defaultTtl']
container_client.replace_container(**container_props)"""
            undo_sql = None  # Can't undo disabling TTL without knowing previous value
        else:
            ttl_seconds = int(ttl_value)
            description = (
                f"Set default TTL on container '{container_name}' to {ttl_seconds} seconds"
            )
            python_code = f"""container_client = database.get_container_client('{container_name}')
container_props = container_client.read()
container_props['defaultTtl'] = {ttl_seconds}
container_client.replace_container(**container_props)"""

            # Get current TTL for undo
            current_ttl = self._get_current_ttl(container_name)
            if current_ttl is not None:
                undo_sql = f"SET TTL ON CONTAINER {container_name} TO {current_ttl}"
            else:
                undo_sql = f"SET TTL ON CONTAINER {container_name} TO OFF"

        return {
            "operation": "set_ttl",
            "container_name": container_name,
            "parameters": {
                "ttl_seconds": ttl_seconds,
            },
            "python_code": python_code,
            "description": description,
            "note": "TTL (Time To Live) automatically deletes documents after the specified number of seconds",
            "undo_sql": undo_sql if ttl_seconds is not None else None,
        }

    # =========================================================================
    # Helper Methods for State Retrieval
    # =========================================================================

    def _get_current_throughput(self, container_name: str) -> Optional[int]:
        """Get current throughput for a container (used for undo generation).

        Args:
            container_name: Container name

        Returns:
            Current throughput in RU/s, or None if not available
        """
        from typing import cast

        if not self.connection_manager or not self.connection_manager.database:
            return None

        try:
            container_client = self.connection_manager.database.get_container_client(container_name)
            offer = container_client.read_offer()
            return cast(Optional[int], offer.offer_throughput)
        except Exception as e:
            self.log.debug(f"Could not get throughput for {container_name}: {e}")
            return None

    def _get_current_ttl(self, container_name: str) -> Optional[int]:
        """Get current TTL for a container (used for undo generation).

        Args:
            container_name: Container name

        Returns:
            Current TTL in seconds, or None if not set
        """
        from typing import cast

        if not self.connection_manager or not self.connection_manager.database:
            return None

        try:
            container_client = self.connection_manager.database.get_container_client(container_name)
            props = container_client.read()
            return cast(Optional[int], props.get("defaultTtl"))
        except Exception as e:
            self.log.debug(f"Could not get TTL for {container_name}: {e}")
            return None

    def _get_current_indexing_policy(self, container_name: str) -> Optional[Dict[str, Any]]:
        """Get current indexing policy for a container.

        Args:
            container_name: Container name

        Returns:
            Current indexing policy, or None if not available
        """
        from typing import cast

        if not self.connection_manager or not self.connection_manager.database:
            return None

        try:
            container_client = self.connection_manager.database.get_container_client(container_name)
            props = container_client.read()
            return cast(Optional[Dict[str, Any]], props.get("indexingPolicy"))
        except Exception as e:
            self.log.debug(f"Could not get indexing policy for {container_name}: {e}")
            return None

    def _extract_container_name(self, sql: str, statement: Optional[SqlStatement] = None) -> str:
        """Extract container name from SQL statement.

        Args:
            sql: SQL statement
            statement: Optional SqlStatement for fallback

        Returns:
            Container name
        """
        container_name = extract_container_name(
            sql,
            ("DROP", "ALTER", "UPDATE", "SET"),
            allow_if_exists=True,
        )
        if container_name:
            return container_name

        # Fallback: try to extract from object_name in statement
        if statement:
            return getattr(statement, "object_name", "unknown")
        return "unknown"

    def _parse_container_properties(self, sql: str) -> Dict[str, str]:
        """Parse container properties from ALTER CONTAINER statement.

        Args:
            sql: SQL statement

        Returns:
            Dictionary of property names to values
        """
        properties: Dict[str, str] = {}

        # Remove comments
        sql_no_comments = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
        sql_no_comments = re.sub(r"/\*.*?\*/", "", sql_no_comments, flags=re.DOTALL)

        # Match: ALTER CONTAINER name SET (property=value, ...)
        set_match = re.search(r"SET\s*\((.*?)\)", sql_no_comments, re.IGNORECASE | re.DOTALL)
        if not set_match:
            return properties

        properties_str = set_match.group(1)

        # Parse key=value pairs
        # Handle quoted values and JSON strings
        parts = []
        current_part = ""
        in_quotes = False
        quote_char = None
        paren_depth = 0

        for char in properties_str:
            if char in ("'", '"') and (not in_quotes or char == quote_char):
                in_quotes = not in_quotes
                quote_char = char if in_quotes else None
                current_part += char
            elif char == "(" and not in_quotes:
                paren_depth += 1
                current_part += char
            elif char == ")" and not in_quotes:
                paren_depth -= 1
                current_part += char
            elif char == "," and not in_quotes and paren_depth == 0:
                if current_part.strip():
                    parts.append(current_part.strip())
                current_part = ""
            else:
                current_part += char

        if current_part.strip():
            parts.append(current_part.strip())

        # Parse each part as key=value
        for part in parts:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            value = value.strip()

            # Remove quotes if present
            if len(value) >= 2:
                if (value.startswith("'") and value.endswith("'")) or (
                    value.startswith('"') and value.endswith('"')
                ):
                    value = value[1:-1]

            properties[key] = value

        return properties

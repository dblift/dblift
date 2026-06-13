"""CosmosDB SDK script generation helpers.

Keeps undo/python script generation without the legacy MigrationPlan planner.
"""

# mypy: disable-error-code="attr-defined"

import json
from typing import Any, Callable, Dict, List, Optional

from core.sql_generator.sql_statement import SqlStatement
from db.plugins.cosmosdb.sdk_translator._parsing import extract_container_name


class _CosmosDbScriptGenerationMixin:
    """Mixin providing ``generate_undo_script`` and ``generate_python_script``."""

    log: Any
    can_translate: Callable[..., bool]
    translate_to_sdk_operation: Callable[..., Optional[Dict[str, Any]]]

    def generate_undo_script(self, statements: List[SqlStatement]) -> str:
        """Generate an undo script for a list of SQL statements."""
        undo_statements = [
            "-- Undo Script",
            "-- Generated from migration statements",
            "-- Execute these statements to rollback the migration",
            "",
        ]

        for i, statement in enumerate(reversed(statements), 1):
            sql = statement.sql.strip()

            if self.can_translate(statement):
                operation = self.translate_to_sdk_operation(statement)
                if operation and operation.get("undo_sql"):
                    undo_statements.append(
                        f"-- Undo step {i}: {operation.get('description', 'N/A')}"
                    )
                    undo_statements.append(operation["undo_sql"] + ";")
                    undo_statements.append("")
                elif operation:
                    undo_statements.append(
                        f"-- Undo step {i}: {operation.get('description', 'N/A')}"
                    )
                    undo_statements.append(
                        f"-- WARNING: Cannot automatically generate undo for: {sql}"
                    )
                    if operation["operation"] == "delete_container":
                        undo_statements.append(
                            "-- Container deletion cannot be undone - data is lost"
                        )
                    undo_statements.append("")
            else:
                sql_upper = sql.upper()
                if sql_upper.startswith("CREATE CONTAINER"):
                    container_name = extract_container_name(
                        sql,
                        ("CREATE",),
                        allow_if_not_exists=True,
                    )
                    if container_name:
                        undo_statements.append(
                            f"-- Undo step {i}: Drop container created by migration"
                        )
                        undo_statements.append(f"DROP CONTAINER {container_name};")
                        undo_statements.append("")
                elif sql_upper.startswith("INSERT"):
                    undo_statements.append(f"-- Undo step {i}: Delete inserted document")
                    undo_statements.append(
                        "-- WARNING: Cannot automatically generate DELETE for INSERT"
                    )
                    undo_statements.append(f"-- Original: {sql}")
                    undo_statements.append("")

        return "\n".join(undo_statements)

    def generate_python_script(self, statements: List[SqlStatement]) -> str:
        """Generate a Python script that executes SDK operations."""
        lines = [
            "# CosmosDB SDK Operations Script",
            "# Generated from pseudo-SQL statements",
            "#",
            "# This script uses Azure SDK to execute operations that cannot be done via SQL API",
            "",
            "from azure.cosmos import CosmosClient, PartitionKey",
            "import json",
            "",
            "# Initialize connection (adjust these values)",
            "# client = CosmosClient(url='<account_endpoint>', credential='<account_key>')",
            "# database = client.get_database_client(database_name='<database_name>')",
            "",
        ]

        for i, statement in enumerate(statements, 1):
            if not self.can_translate(statement):
                continue

            operation = self.translate_to_sdk_operation(statement)
            if not operation:
                continue

            lines.append(f"# Operation {i}: {operation.get('description', 'N/A')}")
            if "warning" in operation:
                lines.append(f"# WARNING: {operation['warning']}")
            if "note" in operation:
                lines.append(f"# NOTE: {operation['note']}")

            lines.append(f"# {statement.sql}")
            lines.append("")

            container_name = operation["container_name"]
            op_type = operation["operation"]

            if op_type == "delete_container":
                lines.append(f"# Delete container '{container_name}'")
                lines.append(
                    f"container_client = database.get_container_client('{container_name}')"
                )
                lines.append("container_client.delete_container()")
                lines.append('print(f"Deleted container: {container_name}")')
            elif op_type == "replace_container":
                lines.append(f"# Update container '{container_name}' properties")
                lines.append(
                    f"container_client = database.get_container_client('{container_name}')"
                )
                lines.append("container_properties = container_client.read()")
                for key, value in operation["parameters"].items():
                    if key == "offer_throughput":
                        lines.append(f"container_client.replace_throughput({value})")
                    else:
                        if isinstance(value, dict):
                            lines.append(f"container_properties['{key}'] = {json.dumps(value)}")
                        else:
                            lines.append(f"container_properties['{key}'] = {value}")
                lines.append("container_client.replace_container(**container_properties)")
                lines.append('print(f"Updated container: {container_name}")')

            lines.append("")

        return "\n".join(lines)

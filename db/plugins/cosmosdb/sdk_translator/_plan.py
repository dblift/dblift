"""CosmosDB Migration Plan Mixin — plan generation, undo script, formatting.

This module contains the _CosmosDbPlanMixin class which implements
migration plan generation, undo script generation, and formatting methods.
"""

# mypy: disable-error-code="attr-defined"

import json
from typing import Any, Callable, Dict, List, Optional

from core.state.sql_statement import SqlStatement
from db.plugins.cosmosdb.sdk_translator._models import MigrationPlan, MigrationPlanStep
from db.plugins.cosmosdb.sdk_translator._parsing import extract_container_name


class _CosmosDbPlanMixin:
    """Mixin providing generate_migration_plan, generate_undo_script, format_migration_plan,
    generate_python_script, and _create_migration_step methods."""

    # Must be provided by the concrete class
    log: Any
    can_translate: Callable[..., bool]
    translate_to_sdk_operation: Callable[..., Optional[Dict[str, Any]]]
    _get_current_throughput: Callable[..., Optional[int]]

    def generate_migration_plan(self, statements: List[SqlStatement]) -> MigrationPlan:
        """Generate a migration plan from a list of SQL statements.

        This provides a dry-run view of what SDK operations would be executed.

        Args:
            statements: List of SQL statements

        Returns:
            MigrationPlan with detailed steps
        """
        plan = MigrationPlan()

        for statement in statements:
            step = self._create_migration_step(statement)
            plan.add_step(step)

        return plan

    def _create_migration_step(self, statement: SqlStatement) -> MigrationPlanStep:
        """Create a migration step from a SQL statement.

        Args:
            statement: SQL statement

        Returns:
            MigrationPlanStep
        """
        sql = statement.sql.strip()

        if self.can_translate(statement):
            operation = self.translate_to_sdk_operation(statement)
            if operation:
                # Estimate RU impact for throughput changes
                ru_impact = None
                if operation["operation"] == "set_throughput":
                    current = self._get_current_throughput(operation["container_name"])
                    new = operation["parameters"].get("throughput", 0)
                    if current:
                        ru_impact = new - current

                return MigrationPlanStep(
                    sql=sql,
                    operation_type=operation["operation"],
                    sdk_operation=operation["operation"],
                    python_code=operation.get("python_code"),
                    description=operation.get("description", ""),
                    warning=operation.get("warning"),
                    note=operation.get("note"),
                    is_sdk_required=True,
                    estimated_ru_impact=ru_impact,
                    undo_sql=operation.get("undo_sql"),
                )

        # Native SQL API operation (CREATE CONTAINER, SELECT, INSERT, etc.)
        sql_upper = sql.upper()
        if sql_upper.startswith("CREATE CONTAINER"):
            return MigrationPlanStep(
                sql=sql,
                operation_type="create_container",
                description="Create new container (native SQL API)",
                is_sdk_required=False,
            )
        elif sql_upper.startswith("SELECT"):
            return MigrationPlanStep(
                sql=sql,
                operation_type="query",
                description="Query documents (native SQL API)",
                is_sdk_required=False,
            )
        elif sql_upper.startswith("INSERT"):
            return MigrationPlanStep(
                sql=sql,
                operation_type="insert",
                description="Insert document (native SQL API)",
                is_sdk_required=False,
            )
        elif sql_upper.startswith("UPDATE"):
            return MigrationPlanStep(
                sql=sql,
                operation_type="update",
                description="Update documents (native SQL API)",
                is_sdk_required=False,
            )
        elif sql_upper.startswith("DELETE"):
            return MigrationPlanStep(
                sql=sql,
                operation_type="delete",
                description="Delete documents (native SQL API)",
                is_sdk_required=False,
            )
        else:
            return MigrationPlanStep(
                sql=sql,
                operation_type="unknown",
                description="Unknown statement type",
                is_sdk_required=False,
            )

    def generate_undo_script(self, statements: List[SqlStatement]) -> str:
        """Generate an undo script for a list of SQL statements.

        Args:
            statements: List of SQL statements

        Returns:
            Undo script as SQL string
        """
        undo_statements = []
        undo_statements.append("-- Undo Script")
        undo_statements.append("-- Generated from migration statements")
        undo_statements.append("-- Execute these statements to rollback the migration")
        undo_statements.append("")

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
                # Handle native SQL operations
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

    def format_migration_plan(self, plan: MigrationPlan) -> str:
        """Format a migration plan for display.

        Args:
            plan: Migration plan

        Returns:
            Formatted string for display
        """
        lines = []
        lines.append("=" * 70)
        lines.append("MIGRATION PLAN (Dry Run)")
        lines.append("=" * 70)
        lines.append("")

        if plan.has_destructive_operations:
            lines.append("⚠️  WARNING: This migration contains DESTRUCTIVE operations!")
            lines.append("")

        if plan.has_sdk_operations:
            lines.append("ℹ️  Note: Some operations require Azure SDK (not native SQL API)")
            lines.append("")

        for i, step in enumerate(plan.steps, 1):
            lines.append(f"Step {i}: {step.operation_type}")
            lines.append("-" * 40)
            lines.append(f"  SQL: {step.sql[:60]}{'...' if len(step.sql) > 60 else ''}")
            lines.append(f"  Description: {step.description}")

            if step.is_sdk_required:
                lines.append("  Execution: Azure SDK")
                if step.python_code:
                    # Show first line of Python code
                    first_line = step.python_code.split("\n")[0]
                    lines.append(f"  Python: {first_line}")
            else:
                lines.append("  Execution: Native SQL API")

            if step.warning:
                lines.append(f"  ⚠️  WARNING: {step.warning}")

            if step.note:
                lines.append(f"  Note: {step.note}")

            if step.estimated_ru_impact:
                sign = "+" if step.estimated_ru_impact > 0 else ""
                lines.append(f"  RU Impact: {sign}{step.estimated_ru_impact} RU/s")

            if step.undo_sql:
                lines.append(f"  Undo: {step.undo_sql}")

            lines.append("")

        lines.append("=" * 70)
        lines.append("SUMMARY")
        lines.append("=" * 70)
        lines.append(f"  Total steps: {len(plan.steps)}")
        lines.append(f"  SDK operations: {sum(1 for s in plan.steps if s.is_sdk_required)}")
        lines.append(
            f"  Native SQL operations: {sum(1 for s in plan.steps if not s.is_sdk_required)}"
        )
        if plan.total_ru_impact != 0:
            sign = "+" if plan.total_ru_impact > 0 else ""
            lines.append(f"  Estimated RU impact: {sign}{plan.total_ru_impact} RU/s")
        lines.append("")

        return "\n".join(lines)

    def generate_python_script(self, statements: List[SqlStatement]) -> str:
        """Generate a Python script that executes SDK operations.

        Args:
            statements: List of SQL statements to translate

        Returns:
            Python script as string
        """
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

            # Generate Python code
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

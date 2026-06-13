"""CosmosDB ALTER Statement Generator.

CosmosDB is schema-less, so most ALTER operations are not applicable.
This generator provides appropriate handling for CosmosDB.
"""

import logging
from typing import TYPE_CHECKING, List, Optional

from core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
from core.sql_model.base import SqlConstraint

if TYPE_CHECKING:
    from core.sql_model.base import SqlColumn
    from core.sql_model.table import Table
    from core.sql_model.view import View

logger = logging.getLogger(__name__)


class CosmosDbAlterGenerator(BaseAlterGenerator):
    """ALTER generator for CosmosDB.

    CosmosDB is schema-less, so most ALTER TABLE operations are not applicable.
    This generator returns comments explaining that operations are not needed.
    """

    def generate_alter_table_statements(
        self,
        table: "Table",
        add_constraints: Optional[List[SqlConstraint]] = None,
        drop_constraints: Optional[List[str]] = None,
        add_columns: Optional[List["SqlColumn"]] = None,
        drop_columns: Optional[List[str]] = None,
        modify_columns: Optional[List["SqlColumn"]] = None,
    ) -> List[str]:
        """Generate ALTER TABLE statements for CosmosDB.

        CosmosDB is schema-less, so ALTER TABLE operations are not applicable.
        Returns comments explaining this.

        Args:
            table: Table object to alter
            add_constraints: List of constraints to add
            drop_constraints: List of constraint names to drop
            add_columns: List of columns to add
            drop_columns: List of column names to drop
            modify_columns: List of columns to modify

        Returns:
            List of comment statements explaining that operations are not needed
        """
        statements: List[str] = []
        table_name = self._format_identifier(table.name)

        if add_columns:
            for col in add_columns:
                statements.append(
                    f"-- CosmosDB is schema-less: no ALTER TABLE needed to add column {self._format_identifier(col.name)} to {table_name}"
                )

        if drop_columns:
            for col_name in drop_columns:
                statements.append(
                    f"-- CosmosDB is schema-less: no ALTER TABLE needed to drop column {self._format_identifier(col_name)} from {table_name}"
                )

        if modify_columns:
            for col in modify_columns:
                statements.append(
                    f"-- CosmosDB is schema-less: no ALTER TABLE needed to modify column {self._format_identifier(col.name)} in {table_name}"
                )

        if add_constraints:
            for constraint in add_constraints:
                constraint_name = (
                    self._format_identifier(constraint.name) if constraint.name else "constraint"
                )
                statements.append(
                    f"-- CosmosDB is schema-less: no ALTER TABLE needed to add constraint {constraint_name} to {table_name}"
                )

        if drop_constraints:
            for constraint_name in drop_constraints:
                statements.append(
                    f"-- CosmosDB is schema-less: no ALTER TABLE needed to drop constraint {self._format_identifier(constraint_name)} from {table_name}"
                )

        return statements

    def generate_alter_view_statement(
        self,
        view: "View",
        new_query: Optional[str] = None,
    ) -> Optional[str]:
        """Generate ALTER VIEW statement for CosmosDB.

        CosmosDB doesn't support views in the traditional sense.
        Returns a comment explaining this.

        Args:
            view: View object to alter
            new_query: New view query

        Returns:
            Comment statement explaining that views are not supported
        """
        view_name = self._format_identifier(view.name)
        return f"-- CosmosDB does not support views: no ALTER VIEW needed for {view_name}"

    def _format_identifier(self, identifier: str) -> str:
        """Format identifier for CosmosDB.

        CosmosDB SQL API uses double quotes for identifiers.

        Args:
            identifier: The identifier to format

        Returns:
            Formatted identifier with double quotes
        """
        return f'"{identifier}"'

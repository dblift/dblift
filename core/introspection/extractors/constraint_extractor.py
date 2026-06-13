"""
Constraint extraction from vendor metadata queries.

This module provides constraint extraction functionality, extracting constraint
metadata from vendor-specific queries.
"""

import re
from typing import Any, Dict, List, Optional, Set

from core.introspection.extractors.base_extractor import BaseExtractor
from core.sql_model.base import ConstraintType, SqlConstraint


def _build_unique_constraints_from_dict(
    extractor: Any, unique_indexes: Dict[str, Dict[str, Any]]
) -> List[SqlConstraint]:
    """Convert the per-index dict produced by the dialect-specific catalog
    queries into ``SqlConstraint`` objects, applying name sanitization.

    Used by plugin ``fetch_unique_constraints`` hooks (SQL Server,
    Oracle, PostgreSQL). The DB2 path builds ``SqlConstraint`` objects
    itself (without sanitization) so it doesn't call this helper.
    """
    constraints: List[SqlConstraint] = []
    for idx_data in unique_indexes.values():
        idx_data["columns"].sort(key=lambda x: x["position"])
        constraints.append(
            SqlConstraint(
                constraint_type=ConstraintType.UNIQUE,
                name=extractor._sanitize_constraint_name(idx_data["name"]),
                column_names=[col["column"] for col in idx_data["columns"]],
                dialect=extractor.dialect,
            )
        )
    return constraints


def _is_oracle_generated_not_null_check(dialect: str, row: Dict[str, Any], check_expr: str) -> bool:
    if (dialect or "").lower() != "oracle":
        return False
    generated = str(row.get("generated") or row.get("GENERATED") or "").upper()
    if generated != "GENERATED NAME":
        return False
    return (
        re.match(r'^\s*\(?\s*"?[A-Z0-9_$#]+"?\s+IS\s+NOT\s+NULL\s*\)?\s*$', check_expr, re.I)
        is not None
    )


class ConstraintExtractor(BaseExtractor):
    """Extract constraint metadata from plugin-owned vendor metadata queries."""

    def get_constraints(self, schema: str, table: str) -> List[SqlConstraint]:
        """
        Get all constraints for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            List of SqlConstraint objects (PK, FK, Unique, Check)
        """
        constraints = []

        pk = None
        pk_columns_lower: Set[str] = set()
        pk_name_lower: Optional[str] = None

        try:
            # Get primary key
            self.log.debug(f"Getting primary key for {schema}.{table}")
            pk = self.get_primary_key(schema, table)
            if pk:
                constraints.append(pk)
                pk_columns_lower = {col.lower() for col in getattr(pk, "column_names", []) if col}
                if pk.name:
                    pk_name_lower = pk.name.lower()

            # Get foreign keys
            self.log.debug(f"Getting foreign keys for {schema}.{table}")
            fks = self.get_foreign_keys(schema, table)
            constraints.extend(fks)

            # Get unique constraints (via unique indexes)
            self.log.debug(f"Getting unique constraints for {schema}.{table}")
            unique_constraints = self.get_unique_constraints(schema, table)
            for unique_constraint in unique_constraints:
                unique_columns_lower = {
                    col.lower() for col in getattr(unique_constraint, "column_names", []) if col
                }
                unique_name_lower = (
                    unique_constraint.name.lower() if unique_constraint.name else None
                )

                # Skip if unique constraint duplicates the primary key
                if pk_columns_lower and unique_columns_lower == pk_columns_lower:
                    continue
                if pk_name_lower and unique_name_lower == pk_name_lower:
                    continue

                constraints.append(unique_constraint)

            # Get check constraints via vendor-specific queries
            self.log.debug(f"Getting check constraints for {schema}.{table}")
            check_constraints = self.get_check_constraints(schema, table)
            if check_constraints:
                constraints.extend(check_constraints)

        except Exception as e:
            self.log.error(f"Error getting constraints for {schema}.{table}: {e}")
            self.track_error(
                f"Error getting constraints: {e}",
                object_type="table",
                object_name=table,
                property_name="constraints",
                exception=e,
            )

        return constraints

    def get_primary_key(self, schema: str, table: str) -> Optional[SqlConstraint]:
        """
        Get primary key constraint for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            SqlConstraint object or None
        """
        self.ensure_metadata()
        if not self.vendor_queries:
            return None
        query_result = self.vendor_queries.get_primary_key_query(schema, table)
        if query_result is None:
            return None

        try:
            query, params = query_result
            rows = self.provider.query_executor.execute_query(self.connection, query, params)
            pk_columns: List[Dict[str, Any]] = []
            pk_name = None
            for position, row in enumerate(rows):
                column_name = self.get_row_value(row, "column_name")
                if not column_name:
                    continue
                pk_columns.append({"column": str(column_name), "sequence": position})
                if not pk_name:
                    raw_name = self.get_row_value(row, "constraint_name")
                    pk_name = str(raw_name) if raw_name else None

        except Exception as e:
            self.log.warning(f"Error getting primary key for {schema}.{table}: {e}")
            return None

        if not pk_columns:
            return None

        pk_columns.sort(key=lambda x: int(x["sequence"]))

        # Sanitize constraint name (Oracle-specific)
        sanitized_name = self._sanitize_constraint_name(pk_name)
        if sanitized_name is None:
            sanitized_name = f"pk_{table}"

        return SqlConstraint(
            constraint_type=ConstraintType.PRIMARY_KEY,
            name=sanitized_name,
            column_names=[str(col["column"]) for col in pk_columns],
            dialect=self.dialect,
        )

    def get_foreign_keys(self, schema: str, table: str) -> List[SqlConstraint]:
        """
        Get foreign key constraints for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            List of SqlConstraint objects
        """
        self.ensure_metadata()
        if not self.vendor_queries:
            return []
        query_result = self.vendor_queries.get_foreign_keys_query(schema, table)
        if query_result is None:
            return []

        foreign_keys_data: Dict[str, Dict[str, Any]] = {}

        try:
            query, params = query_result
            rows = self.provider.query_executor.execute_query(self.connection, query, params)
            for row in rows:
                raw_pos = (
                    self.get_row_value(row, "key_seq")
                    or self.get_row_value(row, "ordinal_position")
                    or self.get_row_value(row, "position")
                    or 0
                )
                try:
                    position = int(raw_pos)
                except (TypeError, ValueError):
                    position = 0
                fk_name = self.get_row_value(row, "name")
                if not fk_name:
                    fk_column = self.get_row_value(row, "column_name")
                    ref_table = self.get_row_value(row, "ref_table")
                    fk_name = f"fk_{table}_{ref_table}_{fk_column}"
                fk_name = str(fk_name)

                if fk_name not in foreign_keys_data:
                    foreign_keys_data[fk_name] = {
                        "name": fk_name,
                        "columns": [],
                        "referenced_table": self.get_row_value(row, "ref_table"),
                        "referenced_schema": self.get_row_value(row, "ref_schema"),
                        "referenced_columns": [],
                        "on_update": self.get_row_value(row, "on_update"),
                        "on_delete": self.get_row_value(row, "on_delete"),
                    }

                fk_data = foreign_keys_data[fk_name]
                fk_data["columns"].append((position, self.get_row_value(row, "column_name")))
                fk_data["referenced_columns"].append(
                    (position, self.get_row_value(row, "ref_column"))
                )

        except Exception as e:
            self.log.warning(f"Error getting foreign keys for {schema}.{table}: {e}")
            return []

        constraints = []
        for fk_data in foreign_keys_data.values():
            fk_data["columns"].sort(key=lambda x: x[0])
            fk_data["referenced_columns"].sort(key=lambda x: x[0])

            constraint = SqlConstraint(
                constraint_type=ConstraintType.FOREIGN_KEY,
                name=self._sanitize_constraint_name(fk_data["name"]),
                column_names=[str(col[1]) for col in fk_data["columns"] if col[1]],
                reference_table=(
                    str(fk_data["referenced_table"]) if fk_data["referenced_table"] else None
                ),
                reference_columns=[str(col[1]) for col in fk_data["referenced_columns"] if col[1]],
                dialect=self.dialect,
                on_delete=self._normalize_fk_action(fk_data.get("on_delete")),
                on_update=self._normalize_fk_action(fk_data.get("on_update")),
            )
            reference_schema = fk_data.get("referenced_schema") or schema
            constraint.reference_schema = str(reference_schema) if reference_schema else None
            constraints.append(constraint)

        return constraints

    @staticmethod
    def _normalize_fk_action(action: Any) -> Optional[str]:
        if action is None:
            return None
        action_str = str(action).strip().upper()
        return action_str or None

    def get_unique_constraints(self, schema: str, table: str) -> List[SqlConstraint]:
        """
        Get unique constraints for a table.

        Each plugin's quirks :meth:`BaseQuirks.fetch_unique_constraints`
        hook returns the dialect-specific result (DB2 / SQL Server /
        Oracle / PostgreSQL). When the hook returns ``None`` the native
        path returns an empty list instead of performing a second metadata pass.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            List of SqlConstraint objects
        """
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        result = quirks.fetch_unique_constraints(self, schema, table)
        if result is not None:
            return result

        return self._get_unique_constraints_via_vendor_queries(schema, table)

    def _get_unique_constraints_sqlserver(
        self, schema: str, table: str
    ) -> Dict[str, Dict[str, Any]]:
        """Get unique constraints for SQL Server via sys.key_constraints."""
        sql = """
            SELECT
                kc.name AS constraint_name,
                ic.key_ordinal AS ordinal_position,
                c.name AS column_name
            FROM sys.key_constraints kc
            INNER JOIN sys.tables t
                ON kc.parent_object_id = t.object_id
            INNER JOIN sys.schemas s
                ON t.schema_id = s.schema_id
            INNER JOIN sys.index_columns ic
                ON kc.parent_object_id = ic.object_id
                AND kc.unique_index_id = ic.index_id
            INNER JOIN sys.columns c
                ON ic.object_id = c.object_id
                AND ic.column_id = c.column_id
            WHERE kc.type = 'UQ'
                AND s.name = ?
                AND t.name = ?
            ORDER BY kc.name, ic.key_ordinal
        """
        rows = self.provider.query_executor.execute_query(self.connection, sql, [schema, table])
        unique_indexes: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            idx_name = self.get_row_value(row, "constraint_name")
            if not idx_name:
                continue
            if idx_name not in unique_indexes:
                unique_indexes[idx_name] = {"name": idx_name, "columns": []}
            unique_indexes[idx_name]["columns"].append(
                {
                    "column": self.get_row_value(row, "column_name"),
                    "position": self.get_row_value(row, "ordinal_position") or 0,
                }
            )
        return unique_indexes

    def _get_unique_constraints_oracle(self, schema: str, table: str) -> Dict[str, Dict[str, Any]]:
        """Get unique constraints for Oracle via vendor queries (get_indexes_query)."""
        self.ensure_metadata()
        query, params = self.vendor_queries.get_indexes_query(schema, table)
        rows = self.provider.query_executor.execute_query(self.connection, query, params)
        unique_indexes: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            is_unique_val = self.get_row_value(row, "is_unique") or "N"
            if is_unique_val.upper() not in ("Y", "YES", "TRUE", "1"):
                continue
            idx_name = self.get_row_value(row, "index_name")
            if not idx_name:
                continue
            if idx_name.lower().startswith("pk_") or "primary" in idx_name.lower():
                continue
            if idx_name not in unique_indexes:
                unique_indexes[idx_name] = {"name": idx_name, "columns": []}
            column_name = self.get_row_value(row, "column_name")
            if column_name:
                unique_indexes[idx_name]["columns"].append(
                    {
                        "column": column_name,
                        "position": self.get_row_value(row, "ordinal_position") or 0,
                    }
                )
        return unique_indexes

    def _get_unique_constraints_postgresql(
        self, schema: str, table: str
    ) -> Dict[str, Dict[str, Any]]:
        """Get PG UNIQUE constraints via pg_constraint (contype='u').

        The ``pg_constraint`` catalog lists named UNIQUE constraints without
        conflating standalone ``CREATE UNIQUE INDEX`` objects.
        """
        sql = """
            SELECT
                con.conname AS constraint_name,
                att.attname AS column_name,
                array_position(con.conkey, att.attnum) AS ordinal_position
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class cls ON cls.oid = con.conrelid
            JOIN pg_catalog.pg_namespace nsp ON nsp.oid = cls.relnamespace
            JOIN pg_catalog.pg_attribute att
                ON att.attrelid = cls.oid AND att.attnum = ANY(con.conkey)
            WHERE con.contype = 'u'
                AND nsp.nspname = ?
                AND cls.relname = ?
            ORDER BY con.conname, ordinal_position
        """
        try:
            rows = self.provider.query_executor.execute_query(self.connection, sql, [schema, table])
        except Exception as e:
            self.log.warning(f"PG unique constraint lookup failed for {schema}.{table}: {e}")
            return {}

        unique_indexes: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            idx_name = self.get_row_value(row, "constraint_name")
            column_name = self.get_row_value(row, "column_name")
            if not idx_name or not column_name:
                continue
            if idx_name not in unique_indexes:
                unique_indexes[idx_name] = {"name": idx_name, "columns": []}
            unique_indexes[idx_name]["columns"].append(
                {
                    "column": column_name,
                    "position": self.get_row_value(row, "ordinal_position") or 0,
                }
            )
        return unique_indexes

    def _get_unique_constraints_via_vendor_queries(
        self, schema: str, table: str
    ) -> List[SqlConstraint]:
        """
        Get unique constraints for DB2 via SYSCAT.TABCONST.

        Called by :meth:`Db2Quirks.fetch_unique_constraints`. DB2 stores
        UNIQUE constraints in ``SYSCAT.TABCONST`` with ``TYPE='U'``, which
        is more reliable than the index-based path for multi-column
        UNIQUE constraints. Unlike the other dialect paths, the names
        are *not* run through :meth:`_sanitize_constraint_name` —
        ``TABCONST`` rows already represent user-meaningful constraints.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            List of SqlConstraint objects
        """
        if not self.vendor_queries:
            return []

        self.ensure_metadata()

        try:
            query, params = self.vendor_queries.get_unique_constraints_query(schema, table)

            self.log.debug(
                f"[{self.dialect.upper()}] Executing get_unique_constraints query for {schema}.{table}"
            )
            results = self.provider.query_executor.execute_query(self.connection, query, params)
            self.log.debug(
                f"[{self.dialect.upper()}] get_unique_constraints query completed for {schema}.{table}"
            )

            unique_constraints: Dict[str, Dict[str, Any]] = {}

            for row in results:
                constraint_name = self.get_row_value(row, "constraint_name")
                if not constraint_name:
                    continue

                if constraint_name not in unique_constraints:
                    unique_constraints[constraint_name] = {
                        "name": constraint_name,
                        "columns": [],
                    }

                column_name = self.get_row_value(row, "column_name")
                if column_name:
                    unique_constraints[constraint_name]["columns"].append(
                        {
                            "column": column_name,
                            "position": self.get_row_value(row, "ordinal_position") or 0,
                        }
                    )

            # Convert to SqlConstraint objects
            constraints = []
            for constraint_data in unique_constraints.values():
                # Sort by position
                constraint_data["columns"].sort(key=lambda x: x["position"])

                constraint = SqlConstraint(
                    constraint_type=ConstraintType.UNIQUE,
                    name=constraint_data["name"],
                    column_names=[col["column"] for col in constraint_data["columns"]],
                    dialect=self.dialect,
                )
                constraints.append(constraint)

            if len(constraints) > 0:
                self.log.debug(
                    f"Found {len(constraints)} unique constraints for {schema}.{table} via vendor queries"
                )

            return constraints

        except Exception as e:
            self.log.warning(
                f"Could not get unique constraints via vendor queries for {schema}.{table}: {e}"
            )
            return []

    def get_check_constraints(self, schema: str, table: str) -> List[SqlConstraint]:
        """
        Get check constraints for a table using vendor-specific queries.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            List of SqlConstraint objects with CHECK type
        """
        if not self.vendor_queries or not self.vendor_queries.supports_check_constraints():
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_check_constraints_query(schema, table)
            if not sql:
                return []

            self.log.debug(f"Executing get_check_constraints query for {schema}.{table}")

            results = self.provider.query_executor.execute_query(self.connection, sql, params)

            constraints = []
            for row in results:
                constraint_name = self.get_row_value(row, "constraint_name")
                constraint_def = self.get_row_value(row, "constraint_definition")

                if not constraint_def:
                    continue

                # Parse constraint definition - may be "CHECK (expression)" or just "expression"
                check_expr = constraint_def.strip()

                # Remove "CHECK (" prefix and ")" suffix if present
                check_pattern = re.compile(r"^CHECK\s*\((.+)\)$", re.IGNORECASE | re.DOTALL)
                match = check_pattern.match(check_expr)
                if match:
                    check_expr = match.group(1).strip()
                else:
                    # If it doesn't start with CHECK, assume it's just the expression
                    # Remove outer parentheses if they wrap the entire expression
                    if check_expr.startswith("(") and check_expr.endswith(")"):
                        # Count parentheses to ensure we only remove outer ones
                        if check_expr.count("(") == 1 and check_expr.count(")") == 1:
                            check_expr = check_expr[1:-1].strip()

                # Skip empty or trivial constraints
                if not check_expr or check_expr.strip() in ("1=1", "(1=1)"):
                    continue
                if _is_oracle_generated_not_null_check(self.dialect or "", row, check_expr):
                    continue

                # Sanitize constraint name (Oracle system-generated names)
                sanitized_name = self._sanitize_constraint_name(constraint_name)

                constraint = SqlConstraint(
                    constraint_type=ConstraintType.CHECK,
                    name=sanitized_name,
                    check_expression=check_expr,
                    dialect=self.dialect,
                )

                # Set deferrable/initially_deferred if available
                # Always set to boolean (False if not available or not deferrable)
                is_deferrable_val = self.get_row_value(row, "is_deferrable")
                initially_deferred_val = self.get_row_value(row, "initially_deferred")

                if is_deferrable_val is not None:
                    is_deferrable = str(is_deferrable_val).upper() in ("YES", "Y", "TRUE", "1")
                else:
                    is_deferrable = False  # Default to False if not available

                constraint.is_deferrable = is_deferrable

                if initially_deferred_val is not None:
                    initially_deferred = str(initially_deferred_val).upper() in (
                        "YES",
                        "Y",
                        "TRUE",
                        "1",
                    )
                else:
                    initially_deferred = False  # Default to False if not available

                constraint.initially_deferred = initially_deferred

                # Set is_enabled/is_validated if available (Oracle and SQL Server)
                is_enabled_val = self.get_row_value(row, "is_enabled")
                if is_enabled_val is not None:
                    is_enabled = str(is_enabled_val).upper() in ("YES", "Y", "TRUE", "1")
                    constraint.is_enabled = is_enabled

                is_validated_val = self.get_row_value(row, "is_validated")
                if is_validated_val is not None:
                    is_validated = str(is_validated_val).upper() in ("YES", "Y", "TRUE", "1")
                    constraint.is_validated = is_validated

                constraints.append(constraint)

            if len(constraints) > 0:
                self.log.debug(f"Found {len(constraints)} check constraints for {schema}.{table}")

            return constraints

        except Exception as e:
            self.log.warning(f"Could not get check constraints for {schema}.{table}: {e}")
            self.track_error(
                f"Error getting check constraints: {e}",
                object_type="table",
                object_name=table,
                property_name="check_constraints",
                exception=e,
            )
            return []

    def _sanitize_constraint_name(self, name: Optional[str]) -> Optional[str]:
        """Strip engine-generated constraint names; return ``None`` to drop.

        Delegates to :meth:`BaseQuirks.sanitize_constraint_name`:

        - Oracle drops ``SYS_*`` / ``SYS$*`` patterns.
        - DB2 drops the ``SQL\\d+`` pattern used for system-generated names.
        - Other dialects pass through unchanged.
        """
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        return quirks.sanitize_constraint_name(name)

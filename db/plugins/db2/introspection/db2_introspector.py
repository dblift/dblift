"""DB2 :class:`Introspector` — F.3.f plugin-self-containment.

Native path: plugin-owned vendor queries via ``provider.execute_query()``.
"""

from collections import defaultdict
from fnmatch import fnmatchcase
from typing import Any, Dict, List

from core.constants import DBLIFT_SCHEMA_SNAPSHOTS_TABLE
from core.introspection.base_introspector import BaseIntrospector
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.index import Index
from core.sql_model.table import Table
from db.object_naming import get_normalized_object_name

DBLIFT_HISTORY_TABLE = "DBLIFT_SCHEMA_HISTORY"
DBLIFT_MIGRATION_LOCK_TABLE = "DBLIFT_MIGRATION_LOCK"
FLYWAY_LEGACY_HISTORY_TABLE = "SCHEMA_VERSION"


class DB2Introspector(BaseIntrospector):
    """DB2 introspector entry point."""

    @staticmethod
    def _catalog_lookup_identifier(identifier: str) -> str:
        """Return a quoted identifier marker for exact catalog-name lookups."""
        return '"' + identifier.replace('"', '""') + '"'

    @staticmethod
    def _is_truthy_catalog_value(value: Any) -> bool:
        """Return True for boolean-ish values projected by DB2 catalog queries."""
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value != 0
        return str(value).strip().upper() in {"1", "Y", "YES", "TRUE"}

    @staticmethod
    def _matches_pattern(name: str, pattern: str) -> bool:
        """Match SQL LIKE-style ``%``/``_`` table patterns against a name."""
        glob = pattern.replace("%", "*").replace("_", "?")
        return fnmatchcase(name, glob) or fnmatchcase(name.upper(), glob.upper())

    def _is_internal_table(self, table_name: str) -> bool:
        """Return True for DBLift internal tables that should not be introspected."""
        config = getattr(self.provider, "config", None)
        db = getattr(config, "database", None)
        history_raw = getattr(config, "history_table", None) or getattr(db, "history_table", None)
        snapshot_raw = getattr(config, "snapshot_table", None) or getattr(
            db, "snapshot_table", None
        )
        normalized = get_normalized_object_name(table_name, self.dialect)
        configured = {
            get_normalized_object_name(str(name), self.dialect)
            for name in (
                history_raw or DBLIFT_HISTORY_TABLE,
                snapshot_raw or DBLIFT_SCHEMA_SNAPSHOTS_TABLE,
                DBLIFT_MIGRATION_LOCK_TABLE,
                FLYWAY_LEGACY_HISTORY_TABLE,
            )
        }
        return normalized in configured

    def _vendor_columns(self, schema: str, table: str) -> List[SqlColumn]:
        """Return SQL model columns from vendor ``get_columns_query``."""
        if not self.vendor_queries:
            return []
        result = self.vendor_queries.get_columns_query(schema, table)
        if result is None:
            return []
        sql, params = result
        rows = self.provider.execute_query(sql, params)
        return [
            SqlColumn(
                name=self._get_row_value(row, "column_name"),
                data_type=self._get_row_value(row, "data_type"),
                is_nullable=bool(self._get_row_value(row, "is_nullable")),
                default_value=self._get_row_value(row, "column_default"),
                is_primary_key=bool(self._get_row_value(row, "is_primary_key")),
                dialect=self.dialect,
            )
            for row in rows
        ]

    def get_tables(
        self, schema: str, include_views: bool = False, table_pattern: str = "%"
    ) -> List[Table]:
        """Get DB2 tables through vendor queries for native providers."""
        if getattr(self.provider, "provider_transport", "native") != "native":
            return super().get_tables(schema, include_views, table_pattern)

        if not self.vendor_queries:
            return []

        self._ensure_native_connection()

        table_rows: List[Any] = []
        tables_result = self.vendor_queries.get_tables_query(schema)
        if tables_result is not None:
            sql, params = tables_result
            table_rows = list(self.provider.execute_query(sql, params))

        if include_views:
            views_result = self.vendor_queries.get_view_names_query(schema)
            if views_result is not None:
                sql, params = views_result
                table_rows.extend(
                    {"table_name": self._get_row_value(r, "view_name"), "is_temporary": 0}
                    for r in self.provider.execute_query(sql, params)
                )

        tables: List[Table] = []
        for row in table_rows:
            table_name = self._get_row_value(row, "table_name")
            if not self._matches_pattern(table_name, table_pattern):
                continue
            if self._is_internal_table(table_name):
                continue
            lookup_table = self._catalog_lookup_identifier(table_name)
            columns = self._vendor_columns(schema, lookup_table)
            self.enrich_columns_with_computed(schema, lookup_table, columns)
            self.enrich_columns_with_identity(schema, lookup_table, columns)
            constraints = self.get_constraints(schema, lookup_table)
            table = Table(
                name=table_name,
                columns=columns,
                schema=schema,
                constraints=constraints,
                temporary=self._is_truthy_catalog_value(self._get_row_value(row, "is_temporary")),
                dialect=self.dialect,
            )
            self._apply_vendor_table_properties(schema, lookup_table, table)
            self.enrich_table_with_partition_scheme(schema, lookup_table, table)
            tables.append(table)
        return tables

    def get_constraints(self, schema: str, table: str) -> List[SqlConstraint]:
        """Get DB2 PK/FK/UNIQUE/CHECK constraints via vendor queries."""
        if getattr(self.provider, "provider_transport", "native") != "native":
            return self._get_constraints(schema, table)

        if not self.vendor_queries:
            return []

        constraints: List[SqlConstraint] = []

        pk_result = self.vendor_queries.get_primary_key_query(schema, table)
        if pk_result is not None:
            sql, params = pk_result
            pk_rows = self.provider.execute_query(sql, params)
            if pk_rows:
                pk_name = self._get_row_value(pk_rows[0], "constraint_name") or f"{table}_pk"
                pk_cols = [self._get_row_value(r, "column_name") for r in pk_rows]
                constraints.append(
                    SqlConstraint(
                        ConstraintType.PRIMARY_KEY,
                        name=pk_name,
                        column_names=pk_cols,
                        dialect=self.dialect,
                    )
                )

        fk_result = self.vendor_queries.get_foreign_keys_query(schema, table)
        if fk_result is not None:
            sql, params = fk_result
            fk_rows = self.provider.execute_query(sql, params)
            fk_map: Dict[str, Any] = {}
            for row in fk_rows:
                name = self._get_row_value(row, "name") or ""
                if name not in fk_map:
                    fk_map[name] = {
                        "name": name,
                        "columns": [],
                        "ref_schema": self._get_row_value(row, "ref_schema"),
                        "ref_table": self._get_row_value(row, "ref_table"),
                        "ref_columns": [],
                        "on_delete": self._get_row_value(row, "on_delete"),
                        "on_update": self._get_row_value(row, "on_update"),
                    }
                fk_map[name]["columns"].append(self._get_row_value(row, "column_name"))
                fk_map[name]["ref_columns"].append(self._get_row_value(row, "ref_column"))
            for fk in fk_map.values():
                c = SqlConstraint(
                    ConstraintType.FOREIGN_KEY,
                    name=fk["name"],
                    column_names=fk["columns"],
                    reference_table=fk["ref_table"],
                    reference_columns=fk["ref_columns"],
                    dialect=self.dialect,
                    on_delete=fk["on_delete"],
                    on_update=fk["on_update"],
                )
                c.reference_schema = fk["ref_schema"]
                constraints.append(c)

        uc_sql, uc_params = self.vendor_queries.get_unique_constraints_query(schema, table)
        if uc_sql is not None:
            uc_rows = self.provider.execute_query(uc_sql, uc_params)
            uc_map: Dict[str, List[str]] = defaultdict(list)
            for row in uc_rows:
                uc_map[self._get_row_value(row, "constraint_name") or ""].append(
                    self._get_row_value(row, "column_name")
                )
            for name, cols in uc_map.items():
                if cols:
                    constraints.append(
                        SqlConstraint(
                            ConstraintType.UNIQUE,
                            name=name,
                            column_names=cols,
                            dialect=self.dialect,
                        )
                    )

        constraints.extend(self.get_check_constraints(schema, table))
        return constraints

    def get_indexes(self, schema: str, table: str) -> List[Index]:
        """Get DB2 indexes via IndexExtractor (vendor queries on native path)."""
        return super().get_indexes(schema, table)


__all__ = ["DB2Introspector"]

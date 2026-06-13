"""PostgreSQL :class:`Introspector` — F.3.a plugin-self-containment.

After the H.2 series moved every ``self.dialect ==`` branch out of
``db/introspection/extractors/`` and into ``BaseQuirks`` hooks, the
introspector's orchestration code became dialect-agnostic: it
instantiates the extractors and routes ``get_X`` calls through them.
Each plugin owns the *wiring* (capability gating, vendor query
selection, the ``XQuirks.introspector_class`` hook) while sharing
the orchestration with the canonical implementation.

This module is the plugin-located entry point. F.3.h merged the
orchestration code into :class:`BaseIntrospector`; this subclass
exists so ``db/plugins/postgresql/`` shows the full plugin surface
without leaving the directory.

Native path: vendor queries via ``provider.execute_query()``.
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

DBLIFT_HISTORY_TABLE = "dblift_schema_history"
DBLIFT_MIGRATION_LOCK_TABLE = "dblift_migration_lock"
FLYWAY_LEGACY_HISTORY_TABLE = "schema_version"


class PostgreSQLIntrospector(BaseIntrospector):
    """PostgreSQL-specific introspector entry point.

    Inherits all orchestration from :class:`BaseIntrospector`. The
    dialect-specific behaviour lives in :class:`PostgresqlQuirks` and
    in the per-kind extractors (which already call
    ``ProviderRegistry.get_quirks`` for every dialect decision).

    All structural metadata is fetched via vendor SQL queries through
    ``provider.execute_query()``.
    """

    @staticmethod
    def _matches_pattern(name: str, pattern: str) -> bool:
        """Match SQL ``%``/``_`` table patterns against a name."""
        glob = pattern.replace("%", "*").replace("_", "?")
        return fnmatchcase(name, glob)

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
                name=row["column_name"],
                data_type=row["data_type"],
                is_nullable=bool(row.get("is_nullable", True)),
                default_value=row.get("column_default"),
                is_primary_key=bool(row.get("is_primary_key", False)),
                dialect=self.dialect,
            )
            for row in rows
        ]

    def get_tables(
        self, schema: str, include_views: bool = False, table_pattern: str = "%"
    ) -> List[Table]:
        """Get PostgreSQL tables through vendor queries for native providers."""
        if getattr(self.provider, "provider_transport", "native") != "native":
            return super().get_tables(schema, include_views, table_pattern)

        if not self.vendor_queries:
            return []

        # Ensure a connection exists so extractor calls in get_constraints work.
        self._ensure_native_connection()

        names: List[str] = []
        tables_result = self.vendor_queries.get_tables_query(schema)
        if tables_result is not None:
            sql, params = tables_result
            names = [r["table_name"] for r in self.provider.execute_query(sql, params)]

        if include_views:
            views_result = self.vendor_queries.get_view_names_query(schema)
            if views_result is not None:
                sql, params = views_result
                names.extend(r["view_name"] for r in self.provider.execute_query(sql, params))

        tables: List[Table] = []
        for table_name in names:
            if not self._matches_pattern(table_name, table_pattern):
                continue
            if self._is_internal_table(table_name):
                continue
            columns = self._vendor_columns(schema, table_name)
            self.enrich_columns_with_computed(schema, table_name, columns)
            self.enrich_columns_with_identity(schema, table_name, columns)
            constraints = self.get_constraints(schema, table_name)
            tables.append(
                Table(
                    name=table_name,
                    columns=columns,
                    schema=schema,
                    constraints=constraints,
                    dialect=self.dialect,
                )
            )
        return tables

    def get_constraints(self, schema: str, table: str) -> List[SqlConstraint]:
        """Get PostgreSQL PK/FK/UNIQUE/CHECK constraints via vendor queries."""
        if getattr(self.provider, "provider_transport", "native") != "native":
            return self._get_constraints(schema, table)

        if not self.vendor_queries:
            return []

        constraints: List[SqlConstraint] = []

        # Primary key
        pk_result = self.vendor_queries.get_primary_key_query(schema, table)
        if pk_result is not None:
            sql, params = pk_result
            pk_rows = self.provider.execute_query(sql, params)
            if pk_rows:
                pk_name = pk_rows[0].get("constraint_name") or f"{table}_pkey"
                pk_cols = [r["column_name"] for r in pk_rows]
                constraints.append(
                    SqlConstraint(
                        ConstraintType.PRIMARY_KEY,
                        name=pk_name,
                        column_names=pk_cols,
                        dialect=self.dialect,
                    )
                )

        # Foreign keys — aggregate multi-row result by constraint name
        fk_result = self.vendor_queries.get_foreign_keys_query(schema, table)
        if fk_result is not None:
            sql, params = fk_result
            fk_rows = self.provider.execute_query(sql, params)
            fk_map: Dict[str, Any] = {}
            for row in fk_rows:
                name = row.get("name") or ""
                if name not in fk_map:
                    fk_map[name] = {
                        "name": name,
                        "columns": [],
                        "ref_schema": row.get("ref_schema"),
                        "ref_table": row.get("ref_table"),
                        "ref_columns": [],
                        "on_delete": row.get("on_delete"),
                        "on_update": row.get("on_update"),
                    }
                fk_map[name]["columns"].append(row["column_name"])
                fk_map[name]["ref_columns"].append(row["ref_column"])
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

        # Unique constraints — aggregate by name
        uc_sql, uc_params = self.vendor_queries.get_unique_constraints_query(schema, table)
        if uc_sql is not None:
            uc_rows = self.provider.execute_query(uc_sql, uc_params)
            uc_map: Dict[str, List[str]] = defaultdict(list)
            for row in uc_rows:
                uc_map[row.get("name") or ""].append(row["column_name"])
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

        # Check constraints via base class (uses ConstraintExtractor + vendor queries)
        constraints.extend(self.get_check_constraints(schema, table))
        return constraints

    def get_indexes(self, schema: str, table: str) -> List[Index]:
        """Get PostgreSQL indexes via IndexExtractor (vendor queries on native path)."""
        return super().get_indexes(schema, table)


__all__ = ["PostgreSQLIntrospector"]

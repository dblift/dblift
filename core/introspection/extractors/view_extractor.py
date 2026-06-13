"""
View extractor for schema introspection.

This module extracts view and materialized view metadata from databases
using vendor-specific queries.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from core.introspection._utils import get_row_value, parse_json_array, strip_leading_comments
from core.introspection.extractors.base_extractor import BaseExtractor
from core.sql_model.view import View

logger = logging.getLogger(__name__)


class ViewExtractor(BaseExtractor):
    """
    Extractor for views and materialized views.

    This extractor handles both regular views and materialized views
    using vendor-specific queries for comprehensive metadata extraction.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the extractor and the per-object column-name cache.

        ``*args``/``**kwargs`` are forwarded to :class:`BaseExtractor`. The
        ``_object_column_cache`` keys ``(schema, object_name)`` to the
        column list returned by the vendor-specific column query, so
        repeated lookups during view/materialized-view extraction reuse
        the result.
        """
        super().__init__(*args, **kwargs)
        self._object_column_cache: Dict[tuple[str, str], List[str]] = {}

    def _get_object_column_names(self, schema: str, object_name: str) -> List[str]:
        """Fetch and cache column names for views/materialized views."""
        key = (schema.lower(), object_name.lower())
        if key in self._object_column_cache:
            return list(self._object_column_cache[key])

        if not hasattr(self.provider, "query_executor") or not self.provider.query_executor:
            self._object_column_cache[key] = []
            return []

        column_sql: Optional[str] = None
        column_params: Optional[List[Any]] = None

        provider_get_columns = getattr(self.provider, "get_columns_query", None)
        if callable(provider_get_columns):
            try:
                query_result = provider_get_columns(schema, object_name)
                if isinstance(query_result, tuple):
                    column_sql, column_params = query_result
                else:
                    column_sql = query_result
                    column_params = None
            except Exception as exc:
                self.log.debug(
                    f"Provider-specific column lookup failed for {schema}.{object_name}: {exc}"
                )
                column_sql = None

        if not column_sql:
            column_sql = """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = ?
                  AND table_name = ?
                ORDER BY ordinal_position
            """
            column_params = [schema, object_name]

        try:
            if column_params is not None:
                rows = self.provider.query_executor.execute_query(
                    self.connection, column_sql, column_params
                )
            else:
                rows = self.provider.query_executor.execute_query(self.connection, column_sql)
        except Exception as e:
            self.log.debug(f"Could not query view columns for {key}: {e}")
            self._object_column_cache[key] = []
            return []

        column_names = [
            get_row_value(row, "column_name") for row in rows if get_row_value(row, "column_name")
        ]
        self._object_column_cache[key] = column_names
        return list(column_names)

    def _extract_view_query(self, definition: Optional[str]) -> Optional[str]:
        """Extract the SELECT query from a view definition."""
        if not definition:
            return None
        text = strip_leading_comments(definition).strip()
        if not text:
            return None
        if re.match(r"^CREATE\b", text, re.IGNORECASE):
            as_match = re.search(r"\bAS\b", text, re.IGNORECASE)
            if as_match:
                query = text[as_match.end() :].strip()
                if query.endswith(";"):
                    query = query[:-1].strip()
                return query
        if not re.match(r"^(SELECT|WITH)\b", text, re.IGNORECASE):
            text = f"SELECT {text}"
        return text

    def get_views(self, schema: str) -> List[View]:
        """
        Get views in a schema using vendor-specific queries.

        Args:
            schema: Schema name

        Returns:
            List of View objects with their definitions
        """
        if not self.vendor_queries or not self.vendor_queries.supports_views():
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_views_query(schema)
            self.log.debug(f"[{self.dialect.upper()}] Executing views query for schema '{schema}'")
            results = self.provider.query_executor.execute_query(self.connection, sql, params)
            self.log.debug(f"[{self.dialect.upper()}] Views query completed, processing results")

            views = []
            for row in results:
                view_name = get_row_value(row, "view_name") or get_row_value(row, "table_name")
                if not view_name or view_name.upper() == "NONE":
                    logger.warning(f"Skipping view with invalid name: {row}")
                    continue

                # Dialect-specific catalog-name normalisation (DB2 lowercases)
                # routed through the per-plugin quirks hook.
                from db.provider_registry import ProviderRegistry

                quirks = ProviderRegistry.get_quirks(self.dialect or "")
                view_name = quirks.normalize_view_name(view_name)

                check_option = get_row_value(row, "check_option")
                columns = parse_json_array(get_row_value(row, "column_names"))
                if not columns:
                    try:
                        columns = self._get_object_column_names(schema, view_name)
                    except Exception as e:
                        if self.result_tracker:
                            self.result_tracker._track_warning(
                                f"Could not get view columns: {e}",
                                object_type="view",
                                object_name=view_name,
                                property_name="columns",
                                exception=e,
                            )
                        columns = []

                # Track view capture status
                view_status = None
                if self.result_tracker:
                    view_status = self.result_tracker._track_object_status(
                        "view", view_name, schema
                    )

                view = View(
                    name=view_name,
                    schema=schema,
                    query=self._extract_view_query(get_row_value(row, "view_definition")),
                    columns=columns,
                    is_updatable=(get_row_value(row, "is_updatable") or "NO") == "YES",
                    check_option=(
                        check_option if check_option and check_option.upper() != "NONE" else None
                    ),
                    dialect=self.dialect,
                )

                # Track property capture
                if view_status:
                    view_status.add_property_status("query", view.query is not None)
                    view_status.add_property_status("columns", len(columns) > 0)

                # Dialect-specific row-level view enrichment (MySQL definer +
                # sql_security, PostgreSQL security_definer / security_invoker).
                quirks.enrich_view_from_row(view, row, view_status)

                # Vendor-specific view algorithm fetch (MySQL / MariaDB
                # via ``SHOW CREATE VIEW``; other dialects return None).
                try:
                    algorithm = quirks.fetch_view_algorithm(self, schema, view_name)
                    if algorithm:
                        view.algorithm = algorithm
                        if view_status:
                            view_status.add_property_status("algorithm", True)
                    elif view_status and quirks.provides_view_algorithm:
                        view_status.add_property_status("algorithm", False)
                except Exception as e:
                    if view_status:
                        view_status.add_property_status("algorithm", False)
                    if self.result_tracker:
                        self.result_tracker._track_warning(
                            f"Could not get view algorithm: {e}",
                            object_type="view",
                            object_name=view_name,
                            property_name="algorithm",
                            exception=e,
                        )

                views.append(view)

            self.log.debug(f"Found {len(views)} views in schema {schema}")

            return views

        except Exception as e:
            logger.warning(f"Error getting views for schema {schema}: {e}")
            self.log.warning(f"Could not get views for schema {schema}: {e}")
            if self.result_tracker:
                self.result_tracker._track_error(
                    f"Error getting views: {e}",
                    object_type="schema",
                    object_name=schema,
                    property_name="views",
                    exception=e,
                )
            return []

    def get_materialized_views(self, schema: str) -> List[View]:
        """
        Get materialized views in a schema using vendor-specific queries.

        Materialized views are supported by PostgreSQL (9.3+) and Oracle.

        Args:
            schema: Schema name

        Returns:
            List of View objects with materialized=True
        """
        if not self.vendor_queries or not self.vendor_queries.supports_materialized_views():
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_materialized_views_query(schema)
            if sql is None:
                return []

            results = self.provider.query_executor.execute_query(self.connection, sql, params)

            materialized_views = []
            for row in results:
                mv_name = get_row_value(row, "materialized_view_name")
                if not mv_name:
                    logger.warning(f"Skipping materialized view with no name: {row}")
                    continue

                columns = parse_json_array(get_row_value(row, "column_names"))
                if not columns:
                    columns = self._get_object_column_names(schema, mv_name)
                mview = View(
                    name=mv_name,
                    schema=schema,
                    query=get_row_value(row, "view_definition"),
                    materialized=True,
                    columns=columns,
                    dialect=self.dialect,
                )
                # Store additional metadata as dynamic attributes
                mview.is_populated = (get_row_value(row, "is_populated") or "NO") == "YES"

                # Dialect-specific materialized-view row enrichment
                # (PostgreSQL ``UNLOGGED`` flag).
                from db.provider_registry import ProviderRegistry

                quirks = ProviderRegistry.get_quirks(self.dialect or "")
                quirks.enrich_materialized_view_from_row(mview, row)

                # Oracle-specific metadata
                last_refresh = get_row_value(row, "last_refresh")
                if last_refresh:
                    mview.last_refresh = last_refresh

                refresh_method = get_row_value(row, "refresh_method")
                if refresh_method:
                    mview.refresh_method = refresh_method

                refresh_mode = get_row_value(row, "refresh_mode")
                if refresh_mode:
                    mview.refresh_mode = refresh_mode

                fast_refreshable = get_row_value(row, "fast_refreshable")
                if fast_refreshable:
                    mview.fast_refreshable = fast_refreshable

                # SQL Server indexed views: capture the unique clustered index so the
                # generator can emit the ``CREATE UNIQUE CLUSTERED INDEX`` DDL that
                # materializes the view. Without it, the exported script would not
                # actually be an indexed view after replay.
                clustered_index_name = get_row_value(row, "clustered_index_name")
                if clustered_index_name:
                    mview.clustered_index_name = clustered_index_name  # type: ignore[attr-defined]
                    clustered_index_columns = get_row_value(row, "clustered_index_columns") or ""
                    mview.clustered_index_columns = [  # type: ignore[attr-defined]
                        col.strip() for col in clustered_index_columns.split(",") if col.strip()
                    ]

                materialized_views.append(mview)

            self.log.debug(f"Found {len(materialized_views)} materialized views in schema {schema}")

            return materialized_views

        except Exception as e:
            logger.warning(f"Error getting materialized views for schema {schema}: {e}")
            self.log.warning(f"Could not get materialized views for schema {schema}: {e}")
            return []

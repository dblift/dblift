"""Column extraction from plugin-owned vendor metadata queries."""

import logging
from typing import Any, List, Optional, Set

from core.introspection.extractors.base_extractor import BaseExtractor
from core.sql_model.base import SqlColumn

logger = logging.getLogger(__name__)


class ColumnExtractor(BaseExtractor):
    """Extract column metadata from plugin-owned vendor metadata queries."""

    def get_columns(self, schema: str, table: str) -> List[SqlColumn]:
        """
        Get all columns for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            List of SqlColumn objects with full metadata
        """
        self.ensure_metadata()
        if not self.vendor_queries:
            raise RuntimeError("Vendor metadata queries not available")
        query_result = self.vendor_queries.get_columns_query(schema, table)
        if query_result is None:
            raise RuntimeError(f"Column metadata query not available for {self.dialect}")

        try:
            query, params = query_result
            rows = self.provider.query_executor.execute_query(self.connection, query, params)
            columns = []

            for row in rows:
                column_name = self.get_row_value(row, "column_name")
                data_type = self.get_row_value(row, "data_type") or self.get_row_value(
                    row, "type_name"
                )
                if not column_name or not data_type:
                    continue
                column_name = str(column_name)
                data_type = self.to_python_string(data_type) or ""

                column_table = self.get_row_value(row, "table_name")
                if column_table and str(column_table).upper() != table.upper():
                    self.log.debug(
                        f"Skipping column {column_name} from different table: {column_table} != {table}"
                    )
                    continue

                column_def = self.get_row_value(row, "column_default")
                if column_def is None:
                    column_def = self.get_row_value(row, "column_def")
                ordinal_position = self.to_int(self.get_row_value(row, "ordinal_position")) or 0
                remarks = self.get_row_value(row, "comment") or self.get_row_value(row, "remarks")
                collation = self.get_row_value(row, "collation")
                is_identity_flag = self._coerce_bool(
                    self.get_row_value(row, "is_identity")
                    or self.get_row_value(row, "is_autoincrement")
                )
                is_computed_column = self._coerce_bool(
                    self.get_row_value(row, "is_computed")
                    or self.get_row_value(row, "is_generatedcolumn")
                )

                column = SqlColumn(
                    name=column_name,
                    data_type=data_type,
                    is_nullable=self._coerce_bool(
                        self.get_row_value(row, "is_nullable")
                        if self.get_row_value(row, "is_nullable") is not None
                        else self.get_row_value(row, "nullable")
                    ),
                    default_value=str(column_def) if column_def is not None else None,
                    dialect=self.dialect,
                    is_identity=is_identity_flag,
                    is_computed=is_computed_column,
                    comment=str(remarks) if remarks else None,
                    ordinal_position=ordinal_position,
                    collation=str(collation) if collation else None,
                )

                columns.append(column)

        except Exception as e:
            logger.error(f"Error getting columns for {schema}.{table}: {e}")
            self.track_error(
                f"Error getting columns: {e}",
                object_type="table",
                object_name=table,
                property_name="columns",
                exception=e,
            )
            raise

        # Sort by ordinal position (handle None values)
        columns.sort(key=lambda c: c.ordinal_position if c.ordinal_position is not None else 0)

        # Enhance with vendor-specific queries (SQL Server default values)
        columns = self._enhance_with_vendor_queries(schema, table, columns)

        return columns

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().upper() in {"1", "Y", "YES", "TRUE", "T"}
        return False

    def _build_data_type_string(self, type_name: str, column_size: int, decimal_digits: int) -> str:
        """
        Build data type string with precision/scale.

        Dialect-specific behaviour:

        * Whether ``TIMESTAMP`` / ``TIME`` take only the fractional-seconds
          argument is gated by
          :attr:`BaseQuirks.time_type_supports_only_fractional_precision`
          (PostgreSQL, Oracle, DB2).
        * Which ``column_size`` sentinels encode ``VARCHAR(MAX)`` is gated
          by :attr:`BaseQuirks.varchar_max_sentinel_sizes` (SQL Server).
        """
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect or "")

        data_type = type_name
        # Check if type_name already contains precision/scale (e.g., "TIMESTAMP(6)" from Oracle metadata)
        type_has_precision = "(" in type_name and ")" in type_name

        if column_size > 0 and not type_has_precision:
            if decimal_digits > 0:
                type_name_upper = type_name.upper()
                # Datetime types that accept only a scale argument
                if type_name_upper in ("DATETIME2", "DATETIMEOFFSET", "TIME"):
                    data_type = f"{type_name}({decimal_digits})"
                elif quirks.time_type_supports_only_fractional_precision and (
                    type_name_upper.startswith("TIMESTAMP") or type_name_upper.startswith("TIME")
                ):
                    data_type = f"{type_name}({decimal_digits})"
                else:
                    # DECIMAL/NUMERIC with precision and scale
                    data_type = f"{type_name}({column_size}, {decimal_digits})"
            elif type_name.upper() in (
                "VARCHAR",
                "VARCHAR2",
                "CHAR",
                "NVARCHAR",
                "NVARCHAR2",
                "NCHAR",
            ):
                if (
                    quirks.varchar_max_sentinel_sizes
                    and column_size in quirks.varchar_max_sentinel_sizes
                ):
                    data_type = f"{type_name}(MAX)"
                else:
                    data_type = f"{type_name}({column_size})"

        return data_type

    def _detect_identity(
        self,
        is_autoincrement: Optional[str],
        column_name: Optional[str],
        db2_identity_cols: Optional[Set[str]],
    ) -> bool:
        """
        Detect if a column is an identity/auto-increment column.

        Plugins that mark
        :attr:`BaseQuirks.identity_uses_catalog_fallback` consult the
        preloaded *db2_identity_cols* set when the identity flag is missing.
        """
        from db.provider_registry import ProviderRegistry

        is_identity_flag = is_autoincrement == "YES"
        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        if (
            quirks.identity_uses_catalog_fallback
            and not is_identity_flag
            and db2_identity_cols is not None
        ):
            is_identity_flag = bool(column_name and column_name.upper() in db2_identity_cols)

        return is_identity_flag

    def _detect_computed_column(
        self,
        is_generatedcolumn: Optional[str],
        column_def: Optional[str],
        is_identity_flag: bool,
    ) -> bool:
        """
        Detect if a column is a computed/generated column.

        Delegates to :meth:`BaseQuirks.correct_computed_column_flag` to
        suppress driver false positives (MySQL ``DEFAULT CURRENT_TIMESTAMP``,
        DB2 IDENTITY columns).
        """
        from db.provider_registry import ProviderRegistry

        is_generated = is_generatedcolumn == "YES"
        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        return quirks.correct_computed_column_flag(is_generated, column_def, is_identity_flag)

    def _enhance_with_vendor_queries(
        self, schema: str, table: str, columns: List[SqlColumn]
    ) -> List[SqlColumn]:
        """
        Enhance columns with vendor-specific queries.

        Delegates to :meth:`BaseQuirks.enhance_columns` so each plugin
        owns its own column post-processing (SQL Server fills empty
        defaults from ``sys.default_constraints``; MySQL / MariaDB
        replace bare ``ENUM`` with the full member-list form).
        """
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        quirks.enhance_columns(self, schema, table, columns)
        return columns

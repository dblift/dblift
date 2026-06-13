"""Index extraction from plugin-owned vendor metadata queries."""

import re
from typing import Any, Dict, List, Optional

from core.introspection.extractors.base_extractor import BaseExtractor
from core.sql_model.index import Index

_PG_SIMPLE_OPERAND_RE = (
    r"(?:'(?:''|[^'])*'|"
    r'(?:(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_$]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_$]*))*))'
)
_PG_TEXT_CAST_RE = re.compile(
    rf"\bCAST\(\s*(?P<operand>{_PG_SIMPLE_OPERAND_RE})\s+AS\s+TEXT\s*\)",
    re.IGNORECASE,
)
_PG_TEXT_COLON_CAST_RE = re.compile(
    rf"(?P<operand>{_PG_SIMPLE_OPERAND_RE})\s*::\s*TEXT\b",
    re.IGNORECASE,
)


def normalize_postgresql_index_predicate(predicate: Optional[str]) -> Optional[str]:
    """Remove redundant PostgreSQL text casts from simple index predicates."""
    if predicate is None:
        return None

    def replace_cast(match: re.Match[str]) -> str:
        return re.sub(r"\s*\.\s*", ".", match.group("operand").strip())

    normalized = _PG_TEXT_CAST_RE.sub(replace_cast, predicate)
    normalized = _PG_TEXT_COLON_CAST_RE.sub(replace_cast, normalized)
    return normalized


class IndexExtractor(BaseExtractor):
    """Extract index metadata from plugin-owned vendor metadata queries."""

    def get_indexes(self, schema: str, table: str) -> List[Index]:
        """
        Get all indexes for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            List of Index objects
        """
        self.ensure_metadata()
        if not self.vendor_queries:
            return []

        try:
            indexes_data = self._get_indexes_from_vendor_queries(schema, table)

        except Exception as e:
            self.log.warning(f"Could not get indexes for {schema}.{table}: {e}")
            self.track_error(
                f"Error getting indexes: {e}",
                object_type="table",
                object_name=table,
                property_name="indexes",
                exception=e,
            )
            return []

        # Convert to Index objects
        return self._build_index_objects(schema, table, indexes_data)

    def get_all_indexes(self, schema: str) -> List[Index]:
        """
        Get all indexes for an entire schema.

        Uses a vendor bulk query when available.

        Args:
            schema: Schema name

        Returns:
            List of Index objects for the entire schema
        """
        if not self.vendor_queries:
            return []

        self.ensure_metadata()
        query_result = self.vendor_queries.get_all_indexes_query(schema)
        if query_result is None:
            return (
                []
            )  # no bulk query; empty for this test path (per-table fallback would be used by callers)

        query, params = query_result
        rows = self.provider.query_executor.execute_query(self.connection, query, params)

        # Group rows by table_name
        rows_by_table: Dict[str, List[Any]] = {}
        for row in rows:
            table_name = (
                self.get_row_value(row, "table_name") or self.get_row_value(row, "TABLE_NAME") or ""
            )
            if table_name:
                rows_by_table.setdefault(table_name, []).append(row)

        # Build Index objects per table, reusing shared vendor row parsing
        all_indexes: List[Index] = []
        for table_name, table_rows in rows_by_table.items():
            indexes_data = self._parse_vendor_rows(table_name, table_rows)
            all_indexes.extend(self._build_index_objects(schema, table_name, indexes_data))

        return all_indexes

    def _get_indexes_from_vendor_queries(
        self, schema: str, table: str
    ) -> Dict[str, Dict[str, Any]]:
        """Get indexes using vendor-specific queries."""
        query, params = self.vendor_queries.get_indexes_query(schema, table)
        rows = self.provider.query_executor.execute_query(self.connection, query, params)
        return self._parse_vendor_rows(table, rows)

    def _parse_vendor_rows(self, table: str, rows: List[Any]) -> Dict[str, Dict[str, Any]]:
        """Parse vendor query rows for a single table into indexes_data dict."""
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        indexes_data: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            idx_name = self.get_row_value(row, "index_name")
            if not idx_name:
                continue

            # Skip engine-internal indexes (Oracle: SYS_* / SYS$*).
            if quirks.should_skip_index(str(idx_name)):
                continue

            if idx_name not in indexes_data:
                is_unique_raw = (
                    self.get_row_value(row, "is_unique")
                    or self.get_row_value(row, "IS_UNIQUE")
                    or False
                )
                if isinstance(is_unique_raw, str):
                    is_unique_flag = is_unique_raw.upper() in ("Y", "YES", "TRUE", "1")
                else:
                    is_unique_flag = bool(is_unique_raw)

                index_type_val = self.get_row_value(row, "index_type") or self.get_row_value(
                    row, "INDEX_TYPE"
                )
                filter_condition = self.get_row_value(
                    row, "filter_condition"
                ) or self.get_row_value(row, "FILTER_CONDITION")
                filter_condition = quirks.normalize_index_predicate(filter_condition)
                concurrent_raw = (
                    self.get_row_value(row, "is_concurrent")
                    or self.get_row_value(row, "IS_CONCURRENT")
                    or False
                )
                if isinstance(concurrent_raw, str):
                    concurrent_flag = concurrent_raw.upper() in ("Y", "YES", "TRUE")
                else:
                    concurrent_flag = bool(concurrent_raw)

                tablespace_val = self.get_row_value(row, "tablespace") or self.get_row_value(
                    row, "TABLESPACE"
                )
                locality_val = self.get_row_value(row, "locality") or self.get_row_value(
                    row, "LOCALITY"
                )
                is_local_flag = None
                if locality_val:
                    is_local_flag = locality_val.upper() == "LOCAL"

                fillfactor_val = self.get_row_value(row, "fillfactor")
                compression_val = self.get_row_value(row, "compression")
                comment_val = self.get_row_value(row, "comment")
                definition_val = self.get_row_value(row, "definition") or self.get_row_value(
                    row, "DEFINITION"
                )

                indexes_data[idx_name] = {
                    "name": idx_name,
                    "unique": is_unique_flag,
                    "table": table,
                    "type": (index_type_val or "BTREE").upper(),
                    "condition": filter_condition,
                    "concurrently": concurrent_flag,
                    "tablespace": tablespace_val,
                    "is_local": is_local_flag,
                    "fillfactor": int(fillfactor_val) if fillfactor_val is not None else None,
                    "compression": compression_val,
                    "comment": comment_val,
                    "definition": definition_val,
                    "columns": [],
                    "sort_directions": [],
                }

            # Handle include columns (SQL Server)
            include_raw = self.get_row_value(row, "include_columns")
            if include_raw:
                parsed_include = self.parse_json_array(include_raw)
                include_values: List[str] = []
                for include_entry in parsed_include:
                    if include_entry is None:
                        continue
                    if isinstance(include_entry, dict):
                        name_val = include_entry.get("name")
                        if name_val is None and include_entry:
                            name_val = next(iter(include_entry.values()))
                        if name_val is not None:
                            include_values.append(str(name_val))
                    else:
                        include_values.append(str(include_entry))
                if include_values:
                    indexes_data[idx_name]["include_columns"] = include_values

            # Handle column information
            include_flag_raw = (
                self.get_row_value(row, "is_included")
                or self.get_row_value(row, "IS_INCLUDED")
                or self.get_row_value(row, "is_included_column")
                or self.get_row_value(row, "IS_INCLUDED_COLUMN")
            )
            include_flag = False
            if include_flag_raw is not None:
                if isinstance(include_flag_raw, str):
                    include_flag = include_flag_raw.upper() in ("Y", "YES", "TRUE", "1")
                else:
                    include_flag = bool(include_flag_raw)

            column_name = self.get_row_value(row, "column_name")
            if not column_name:
                column_name = self.get_row_value(row, "COLUMN_NAME")
            index_expression = self.get_row_value(row, "index_expression") or self.get_row_value(
                row, "INDEX_EXPRESSION"
            )
            if isinstance(index_expression, str):
                index_expression = index_expression.strip()

            is_expression_raw = self.get_row_value(row, "is_expression") or self.get_row_value(
                row, "IS_EXPRESSION"
            )
            if isinstance(is_expression_raw, str):
                is_expression_flag = is_expression_raw.upper() in ("Y", "YES", "TRUE", "1")
            else:
                is_expression_flag = bool(is_expression_raw)

            # Substitute the expression text for engine-generated hidden
            # column names (Oracle function-based indexes materialize them
            # under ``SYS_NCxxx`` and similar internal aliases).
            if index_expression and (
                not column_name or quirks.is_index_hidden_column(str(column_name))
            ):
                column_name = index_expression
                is_expression_flag = True

            if column_name and not include_flag:
                col_list: List[Dict[str, Any]] = indexes_data[idx_name]["columns"]
                is_desc_raw = self.get_row_value(row, "is_descending")
                # Handle boolean values returned as numeric driver values.
                if isinstance(is_desc_raw, bool):
                    is_desc_flag = is_desc_raw
                else:
                    is_desc_str = str(is_desc_raw or "N").upper()
                    is_desc_flag = is_desc_str in ("Y", "YES", "TRUE", "DESC", "D", "1")

                col_list.append(
                    {
                        "column": column_name,
                        "position": self.get_row_value(row, "ordinal_position") or 0,
                        "order": "DESC" if is_desc_flag else "ASC",
                        "is_expression": is_expression_flag,
                    }
                )
                indexes_data[idx_name]["sort_directions"].append("DESC" if is_desc_flag else "ASC")

        return indexes_data

    def _build_index_objects(
        self, schema: str, table: str, indexes_data: Dict[str, Dict[str, Any]]
    ) -> List[Index]:
        """Convert index data dictionaries to Index objects."""
        index_objects = []

        for idx_data in indexes_data.values():
            # Sort by position
            idx_data["columns"].sort(key=lambda x: x["position"])

            column_entries = [col for col in idx_data["columns"] if col.get("column")]
            columns_only = [col["column"] for col in column_entries]

            # Determine if sort directions are supported
            index_type_upper = str(idx_data.get("type", "BTREE")).upper()
            supports_sort_direction = self._supports_sort_direction(index_type_upper)

            # Build sort directions
            sort_directions = []
            if supports_sort_direction:
                for col in column_entries:
                    order_val = col.get("order")
                    if isinstance(order_val, bool):
                        sort_directions.append("DESC" if order_val else "ASC")
                    else:
                        sort_directions.append(str(order_val or "ASC").upper())
                # Normalize sort direction abbreviations from metadata.
                sort_directions = [
                    "DESC" if direction in ("D", "DESC", "TRUE") else "ASC"
                    for direction in sort_directions
                ]

            expression_flags = [bool(col.get("is_expression")) for col in column_entries]

            # Build index kwargs
            index_kwargs = {
                "name": idx_data["name"],
                "table_name": table,
                "columns": columns_only,
                "schema": schema,
                "unique": idx_data["unique"],
                "dialect": self.dialect,
            }

            if idx_data.get("type"):
                index_kwargs["type"] = idx_data["type"]
            if idx_data.get("condition"):
                index_kwargs["condition"] = idx_data["condition"]
            if sort_directions:
                index_kwargs["sort_directions"] = sort_directions
            if expression_flags:
                index_kwargs["expression_flags"] = expression_flags
            if idx_data.get("include_columns"):
                index_kwargs["include_columns"] = idx_data["include_columns"]
            if idx_data.get("fillfactor") is not None:
                index_kwargs["fillfactor"] = idx_data["fillfactor"]
            if idx_data.get("compression"):
                index_kwargs["compression"] = idx_data["compression"]
            if idx_data.get("comment"):
                index_kwargs["comment"] = idx_data["comment"]
            if idx_data.get("definition"):
                index_kwargs["definition"] = idx_data["definition"]

            # Add dialect-specific properties
            self._add_dialect_specific_properties(idx_data, index_kwargs)

            index = Index(**index_kwargs)
            index_objects.append(index)

        return index_objects

    def _supports_sort_direction(self, index_type: str) -> bool:
        """Check if index type supports sort directions.

        Driven by the quirks-declared
        :attr:`BaseQuirks.index_no_sort_types` frozenset (PostgreSQL:
        ``GIN``/``GIST``/``BRIN``/``HASH``/``SPGIST``).
        """
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        return index_type.upper() not in quirks.index_no_sort_types

    def _add_dialect_specific_properties(
        self, idx_data: Dict[str, Any], index_kwargs: Dict[str, Any]
    ) -> None:
        """Apply dialect-specific index properties via the quirks hook."""
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        quirks.apply_index_vendor_properties(idx_data, index_kwargs)

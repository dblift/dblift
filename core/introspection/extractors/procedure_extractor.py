"""
Procedure and function extractor for schema introspection.

This module extracts stored procedure and function metadata from databases
using vendor-specific queries.
"""

import logging
import re
from typing import Any, Callable, Dict, List, Optional

from core.constants import LOG_CONTENT_PREVIEW_LENGTH, truncate_sql_for_logging
from core.introspection._utils import (
    get_row_value,
    parse_json_array,
    strip_leading_comments,
    to_int,
)
from core.introspection.extractors.base_extractor import BaseExtractor
from core.sql_model.procedure import Parameter, Procedure

logger = logging.getLogger(__name__)


def _fetch_mysql_show_create_routine(
    extractor: Any, schema: str, name: str, kind: str, status: Any = None
) -> Optional[str]:
    """MySQL / MariaDB: fetch the full ``CREATE PROCEDURE`` / ``CREATE FUNCTION``
    statement via ``SHOW CREATE`` and update the routine's ``body`` from the
    ``BEGIN`` offset.

    BUG-01: ``information_schema.ROUTINES`` exposes only the body, not the
    full CREATE statement; without this fallback the routine would be
    silently dropped during export.

    Returns the full CREATE statement, or ``None`` on any failure (the
    optional *status* tracker is updated when present).
    """
    keyword = "PROCEDURE" if kind == "procedure" else "FUNCTION"
    try:
        safe_schema = schema.replace("`", "``")
        safe_name = name.replace("`", "``")
        show_sql = f"SHOW CREATE {keyword} `{safe_schema}`.`{safe_name}`"
        show_rows = extractor.provider.query_executor.execute_query(
            extractor.connection, show_sql, []
        )
        if not show_rows:
            return None
        title = f"Create {keyword.title()}"
        create_stmt = show_rows[0].get(title) or show_rows[0].get(title.lower())
        if create_stmt:
            return str(create_stmt)
    except Exception as exc:
        extractor.log.debug(f"Could not fetch SHOW CREATE {keyword} for {schema}.{name}: {exc}")
        if status:
            status.add_property_status("definition", False)
        if extractor.result_tracker:
            extractor.result_tracker._track_warning(
                f"Could not fetch {keyword.lower()} definition: {exc}",
                object_type=keyword.lower(),
                object_name=name,
                property_name="definition",
                exception=exc,
            )
    return None


def _extract_definition_parts(definition: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Return (full_definition, body) for a routine/trigger definition."""
    if not definition:
        return (None, None)
    text = strip_leading_comments(definition).strip()
    if not text:
        return (None, None)
    normalized = text
    upper_text = normalized.upper()
    body_index = None
    for match in re.finditer(r"\bAS\b", upper_text):
        start = match.start()
        preceding = upper_text[max(0, start - 9) : start]
        if preceding.endswith("EXECUTE "):
            continue
        body_index = match.end()
        break
    if body_index is None:
        return (normalized, None)
    body = normalized[body_index:].strip()
    return (normalized, body or None)


def _is_full_definition(definition: Optional[str]) -> bool:
    """Return True if the definition already contains full DDL (starts with CREATE/ALTER)."""
    if not isinstance(definition, str):
        return False
    stripped = definition.strip()
    if not stripped:
        return False
    upper = stripped.upper()
    return upper.startswith(("CREATE", "ALTER", "REPLACE"))


def _clean_source_text(extractor: Any, text: Optional[str]) -> Optional[str]:
    """Normalize raw routine source text via the plugin quirks hook
    (Oracle removes ``<E>`` XML markup; other dialects no-op)."""
    from db.provider_registry import ProviderRegistry

    quirks = ProviderRegistry.get_quirks(extractor.dialect or "")
    return quirks.clean_source_text(text)


class ProcedureExtractor(BaseExtractor):
    """
    Extractor for stored procedures and functions.

    This extractor handles procedure and function metadata extraction using
    vendor-specific queries for comprehensive metadata coverage.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the extractor and the Oracle package-spec cache.

        ``*args``/``**kwargs`` are forwarded to :class:`BaseExtractor`. The
        per-instance ``_oracle_package_specs`` cache keys ``(schema, package)``
        pairs to package-spec source text harvested during procedure scans
        — Oracle inlines package specs alongside their bodies, so caching
        avoids re-issuing ``ALL_SOURCE`` queries for the misc-object pass.
        """
        super().__init__(*args, **kwargs)
        # Cache for Oracle package specs embedded in procedure definitions
        self._oracle_package_specs: Dict[tuple[str, str], str] = {}

    def _build_parameters_from_json(self, raw_value: Any) -> List[Parameter]:
        """Convert JSON parameter payloads into Parameter objects."""
        parameters: List[Parameter] = []
        entries = parse_json_array(raw_value)
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or f"param_{idx + 1}"
            data_type = entry.get("data_type") or "text"
            mode = (entry.get("mode") or "IN").upper()
            default_value = entry.get("default_value") or entry.get("default")
            parameters.append(
                Parameter(
                    name=name,
                    data_type=data_type,
                    direction=mode,
                    default_value=default_value,
                    dialect=self.dialect,
                )
            )
        return parameters

    def _fetch_mysql_routine_parameters(self, schema: str, routine_name: str) -> List[Parameter]:
        """Fetch MySQL routine parameters using information_schema.PARAMETERS.

        Reached only via :meth:`MysqlQuirks.fetch_routine_parameters_fallback`,
        which already gates on dialect — so no inline dialect check is needed."""
        if not self.vendor_queries:
            return []

        try:
            query, params = self.vendor_queries.get_parameters_query(schema, routine_name)
            if not query:
                return []
            rows = self.provider.query_executor.execute_query(self.connection, query, params)
            parameters: List[tuple[int, Parameter]] = []
            for row in rows:
                ordinal = to_int(get_row_value(row, "ordinal_position")) or 0
                name = get_row_value(row, "param_name") or f"param_{ordinal}"
                data_type = (
                    get_row_value(row, "parameter_type")
                    or get_row_value(row, "data_type")
                    or "UNKNOWN"
                )
                direction = (get_row_value(row, "param_mode") or "IN").upper()
                parameter = Parameter(
                    name=name,
                    data_type=data_type,
                    direction=direction,
                    dialect=self.dialect,
                )
                parameters.append((ordinal, parameter))

            parameters.sort(key=lambda item: item[0])
            return [param for _, param in parameters]
        except Exception as exc:
            self.log.debug(
                f"Could not fetch MySQL routine parameters for {schema}.{routine_name}: {exc}"
            )
            return []

    def _fetch_oracle_procedure_parameters(
        self, schema: str, procedure_name: str
    ) -> List[Parameter]:
        """Fetch Oracle procedure parameters using ALL_ARGUMENTS.

        Reached only via :meth:`OracleQuirks.fetch_routine_parameters_fallback`,
        which already gates on dialect — so no inline dialect check is needed."""
        if not self.vendor_queries:
            self.log.debug("Skipping Oracle procedure parameters fetch: no vendor_queries")
            return []
        try:
            query, params = self.vendor_queries.get_procedure_arguments_query(
                schema, procedure_name
            )
            if query is None:
                self.log.debug("Skipping Oracle procedure parameters fetch: query not supported")
                return []
            self.log.debug(
                f"Fetching Oracle procedure parameters: {truncate_sql_for_logging(query, LOG_CONTENT_PREVIEW_LENGTH)}"
            )
            rows = self.provider.query_executor.execute_query(self.connection, query, params)
            self.log.debug(f"Found {len(rows)} parameter rows for {schema}.{procedure_name}")
            parameters: List[tuple[int, Parameter]] = []
            for row in rows:
                position = (
                    to_int(get_row_value(row, "position"))
                    or to_int(get_row_value(row, "POSITION"))
                    or 0
                )
                name = (
                    get_row_value(row, "argument_name")
                    or get_row_value(row, "ARGUMENT_NAME")
                    or f"param_{position}"
                )
                data_type = (
                    get_row_value(row, "data_type") or get_row_value(row, "DATA_TYPE") or "UNKNOWN"
                )
                in_out = get_row_value(row, "in_out") or get_row_value(row, "IN_OUT") or "IN"
                # Map Oracle IN/OUT to standard direction
                if in_out == "IN":
                    direction = "IN"
                elif in_out == "OUT":
                    direction = "OUT"
                elif in_out == "IN/OUT":
                    direction = "INOUT"
                else:
                    direction = "IN"

                parameter = Parameter(
                    name=name,
                    data_type=data_type,
                    direction=direction,
                    dialect=self.dialect,
                )
                parameters.append((position, parameter))

            parameters.sort(key=lambda item: item[0])
            result = [param for _, param in parameters]
            self.log.debug(f"Returning {len(result)} parameters for {schema}.{procedure_name}")
            return result
        except Exception as exc:
            self.log.debug(
                f"Could not fetch Oracle procedure parameters for {schema}.{procedure_name}: {exc}",
                exc_info=True,
            )
            return []

    def _fetch_oracle_ddl(self, object_type: str, object_name: str, schema: str) -> Optional[str]:
        """Fetch full Oracle DDL using DBMS_METADATA when available.

        Reached only via :meth:`OracleQuirks.fetch_routine_full_definition`,
        which already gates on dialect — so no inline dialect check is needed."""
        # Normalize identifiers for Oracle (unquoted identifiers are stored in uppercase)
        object_type_upper = object_type.upper()
        object_name_upper = object_name.upper() if object_name else ""
        schema_upper = schema.upper() if schema else ""

        ddl_sql = "SELECT DBMS_METADATA.GET_DDL(?, ?, ?) AS definition FROM DUAL"
        try:
            rows = self.provider.query_executor.execute_query(
                self.connection, ddl_sql, [object_type_upper, object_name_upper, schema_upper]
            )
            if rows:
                definition = get_row_value(rows[0], "definition")
                if definition:
                    return str(definition).strip()
        except Exception as exc:
            self.log.debug(
                f"DBMS_METADATA.GET_DDL failed for {schema}.{object_name} ({object_type}): {exc}"
            )
        return None

    def _fetch_oracle_source_text(
        self, schema: str, object_name: str, object_type: str
    ) -> Optional[str]:
        """Fetch raw Oracle source text from ALL_SOURCE for the given object.

        Reached only via the misc-extractor's Oracle codepath; the
        external dialect gate (and the parallel helper in
        :class:`MiscExtractor`) ensures we're already on Oracle when
        this is called."""
        if not getattr(self.provider, "query_executor", None):
            return None

        source_sql = """
            SELECT text
            FROM all_source
            WHERE owner = ?
              AND name = ?
              AND type = ?
            ORDER BY line
        """
        try:
            rows = self.provider.query_executor.execute_query(
                self.connection, source_sql, [schema, object_name, object_type.upper()]
            )
        except Exception as exc:
            self.log.debug(
                f"Could not fetch Oracle source for {schema}.{object_name} ({object_type}): {exc}"
            )
            return None

        text = "".join(get_row_value(row, "text") or "" for row in rows).strip()
        return text or None

    def _strip_embedded_oracle_package_spec(
        self, schema: Optional[str], definition: str
    ) -> Optional[str]:
        """Detect and cache package specs embedded in procedure definitions."""
        upper_def = definition.upper()
        marker = "CREATE OR REPLACE PACKAGE"
        if marker not in upper_def:
            return definition

        match = re.search(
            r"CREATE\s+OR\s+REPLACE\s+PACKAGE\s+([\"A-Z0-9_\$#\.]+)",
            definition,
            re.IGNORECASE,
        )
        if not match:
            return definition

        pkg_start = match.start()
        package_identifier = match.group(1).strip()
        package_name = package_identifier.strip('"')
        spec_text = definition[pkg_start:].strip()
        cleaned = definition[:pkg_start].rstrip()

        schema_key = (schema or "").upper()
        cache_key = (schema_key, package_name.upper())
        self._oracle_package_specs[cache_key] = spec_text

        return cleaned or None

    def get_procedures(self, schema: str) -> List[Procedure]:
        """
        Get stored procedures in a schema.

        Args:
            schema: Schema name

        Returns:
            List of Procedure objects
        """
        from db.provider_registry import ProviderRegistry

        if not self.vendor_queries or not self.vendor_queries.supports_procedures():
            return []

        self.ensure_metadata()

        quirks = ProviderRegistry.get_quirks(self.dialect or "")

        try:
            sql, params = self.vendor_queries.get_procedures_query(schema)
            if not sql:
                return []

            self.log.debug(f"Executing get_procedures query for schema: {schema}")

            results = self.provider.query_executor.execute_query(self.connection, sql, params)

            self.log.debug(f"Query returned {len(results)} procedures")

            procedures = []
            for row in results:
                procedure_name = get_row_value(row, "procedure_name")
                if not procedure_name:
                    continue

                # Track procedure capture status
                procedure_status = None
                if self.result_tracker:
                    procedure_status = self.result_tracker._track_object_status(
                        "procedure", procedure_name, schema
                    )

                raw_definition = _clean_source_text(self, get_row_value(row, "definition"))

                try:
                    parameter_json = get_row_value(row, "parameter_json")
                    parameters = self._build_parameters_from_json(parameter_json)
                    if not parameters:
                        parameters = quirks.fetch_routine_parameters_fallback(
                            self, schema, procedure_name, "procedure"
                        )
                    if procedure_status:
                        procedure_status.add_property_status("parameters", True)
                except Exception as e:
                    if procedure_status:
                        procedure_status.add_property_status("parameters", False)
                    if self.result_tracker:
                        self.result_tracker._track_warning(
                            f"Could not get procedure parameters: {e}",
                            object_type="procedure",
                            object_name=procedure_name,
                            property_name="parameters",
                            exception=e,
                        )
                    parameters = []

                definition_text, body_text = _extract_definition_parts(raw_definition)

                procedure = Procedure(
                    name=procedure_name,
                    schema=schema,
                    parameters=parameters,
                    body=body_text or raw_definition,
                    language=(
                        get_row_value(row, "language")
                        if "language" in row or "LANGUAGE" in row
                        else "SQL"
                    ),
                    comment=(
                        get_row_value(row, "comment")
                        if "comment" in row or "COMMENT" in row
                        else None
                    ),
                    is_function=False,
                    dialect=self.dialect,
                    definition=definition_text or raw_definition,
                )
                # Plugin-derived volatility (MySQL: is_deterministic;
                # SQL Server: is_deterministic — irrelevant for procs).
                quirks.apply_routine_volatility_from_row(self, procedure, row)
                volatility = get_row_value(row, "volatility")
                if volatility:
                    procedure.volatility = volatility
                security_definer_val = get_row_value(row, "security_definer") or get_row_value(
                    row, "security_type"
                )
                if security_definer_val is not None:
                    security_value = str(security_definer_val).upper()
                    procedure.security_definer = security_value in ("YES", "DEFINER", "TRUE", "1")
                execute_as_principal = get_row_value(row, "execute_as_principal")
                if execute_as_principal:
                    procedure.definer = execute_as_principal
                    if not procedure.security_definer:
                        procedure.security_definer = True
                elif raw_definition:
                    upper_def = raw_definition.upper()
                    if "EXECUTE AS OWNER" in upper_def:
                        procedure.definer = "OWNER"
                        procedure.security_definer = True
                # MySQL definer column has final authority — it can
                # replace ``"OWNER"`` set just above with the real
                # ``user@host``.
                quirks.apply_routine_definer_from_row(self, procedure, row)
                data_access_val = get_row_value(row, "data_access")
                if data_access_val:
                    procedure.data_access = data_access_val
                if procedure.definition and not _is_full_definition(procedure.definition):
                    procedure.definition = None
                # Catalog DDL fallback (MySQL only fills when definition
                # is missing; Oracle DBMS_METADATA always replaces).
                quirks.fetch_routine_full_definition(
                    self, schema, procedure_name, "procedure", procedure, procedure_status
                )
                if not procedure.parameters:
                    procedure.parameters = quirks.fetch_routine_parameters_fallback(
                        self, schema, procedure_name, "procedure"
                    )
                quirks.postprocess_routine(self, schema, procedure)
                procedures.append(procedure)

            if len(procedures) > 0:
                self.log.debug(f"Found {len(procedures)} procedures in schema {schema}")

            return procedures

        except Exception as e:
            logger.warning(f"Error getting procedures for schema {schema}: {e}")
            self.log.warning(f"Could not get procedures for schema {schema}: {e}")
            if self.result_tracker:
                self.result_tracker._track_error(
                    f"Error getting procedures: {e}",
                    object_type="schema",
                    object_name=schema,
                    property_name="procedures",
                    exception=e,
                )
            return []

    def get_functions(
        self, schema: str, get_user_defined_types_fn: Optional[Callable[..., Any]] = None
    ) -> List[Procedure]:
        """
        Get functions in a schema.

        Args:
            schema: Schema name
            get_user_defined_types_fn: Optional function to get UDTs for filtering (DB2)

        Returns:
            List of Procedure objects (with is_function=True)
        """
        from db.provider_registry import ProviderRegistry

        if not self.vendor_queries or not self.vendor_queries.supports_functions():
            return []

        self.ensure_metadata()

        quirks = ProviderRegistry.get_quirks(self.dialect or "")

        try:
            sql, params = self.vendor_queries.get_functions_query(schema)
            if not sql:
                return []

            self.log.debug(f"Executing get_functions query for schema: {schema}")

            results = self.provider.query_executor.execute_query(self.connection, sql, params)

            functions = []
            # System function names that should be filtered out (operators, type casts)
            system_function_names = {
                "<",
                "<=",
                "<>",
                "=",
                ">",
                ">=",
                "VARCHAR",
                "INTEGER",
                "DECIMAL",
                "TIMESTAMP",
                "CHAR",
                "SMALLINT",
                "BIGINT",
                "REAL",
                "DOUBLE",
                "DATE",
                "TIME",
            }

            # Get user-defined type names to filter them out (DB2 may return distinct types as functions)
            udt_names = set()
            if get_user_defined_types_fn:
                try:
                    udts = get_user_defined_types_fn(schema)
                    udt_names = {udt.name.upper() for udt in udts if udt.name}
                except Exception as e:
                    self.log.debug(f"Could not get UDTs for procedure filtering: {e}")

            for row in results:
                function_name = (
                    get_row_value(row, "function_name")
                    or row.get("FUNCNAME")
                    or row.get("funcname")
                )

                if not function_name:
                    continue

                # Skip system functions/operators
                if function_name.upper() in {name.upper() for name in system_function_names}:
                    self.log.debug(f"Skipping system function/operator: {function_name}")
                    continue

                # Skip user-defined types that are incorrectly returned as functions (DB2 issue)
                if function_name.upper() in udt_names:
                    self.log.debug(
                        f"Skipping user-defined type incorrectly returned as function: {function_name}"
                    )
                    continue

                # Track function capture status
                function_status = None
                if self.result_tracker:
                    function_status = self.result_tracker._track_object_status(
                        "function", function_name, schema
                    )

                raw_definition = _clean_source_text(self, get_row_value(row, "definition"))
                definition_text, body_text = _extract_definition_parts(raw_definition)

                try:
                    parameters = self._build_parameters_from_json(
                        get_row_value(row, "parameter_json")
                    )
                    if function_status:
                        function_status.add_property_status("parameters", True)
                except Exception as e:
                    if function_status:
                        function_status.add_property_status("parameters", False)
                    if self.result_tracker:
                        self.result_tracker._track_warning(
                            f"Could not get function parameters: {e}",
                            object_type="function",
                            object_name=function_name,
                            property_name="parameters",
                            exception=e,
                        )
                    parameters = []

                function = Procedure(
                    name=function_name,
                    schema=schema,
                    parameters=parameters,
                    body=body_text or raw_definition,
                    language=(
                        get_row_value(row, "language")
                        if "language" in row or "LANGUAGE" in row
                        else "SQL"
                    ),
                    comment=(
                        get_row_value(row, "comment")
                        if "comment" in row or "COMMENT" in row
                        else None
                    ),
                    is_function=True,
                    return_type=(
                        get_row_value(row, "return_type")
                        if "return_type" in row or "RETURN_TYPE" in row
                        else None
                    ),
                    dialect=self.dialect,
                    definition=definition_text or raw_definition,
                )
                # Plugin-derived volatility (MySQL / SQL Server: derived
                # from ``is_deterministic``).
                quirks.apply_routine_volatility_from_row(self, function, row)
                volatility = get_row_value(row, "volatility")
                if volatility:
                    function.volatility = volatility
                security_definer_val = get_row_value(row, "security_definer") or get_row_value(
                    row, "security_type"
                )
                if security_definer_val is not None:
                    security_value = str(security_definer_val).upper()
                    function.security_definer = security_value in ("YES", "DEFINER", "TRUE", "1")
                execute_as_principal = get_row_value(row, "execute_as_principal")
                if execute_as_principal:
                    function.definer = execute_as_principal
                    if not function.security_definer:
                        function.security_definer = True
                elif raw_definition:
                    upper_def = raw_definition.upper()
                    if "EXECUTE AS OWNER" in upper_def:
                        function.definer = "OWNER"
                        function.security_definer = True
                # MySQL definer column has final authority.
                quirks.apply_routine_definer_from_row(self, function, row)
                data_access_val = get_row_value(row, "data_access")
                if data_access_val:
                    function.data_access = data_access_val
                if function.definition and not _is_full_definition(function.definition):
                    function.definition = None
                # Catalog DDL fallback (MySQL only fills when definition
                # is missing; Oracle DBMS_METADATA always replaces).
                quirks.fetch_routine_full_definition(
                    self, schema, function_name, "function", function, function_status
                )
                if self.vendor_queries and hasattr(
                    self.vendor_queries, "get_function_arguments_query"
                ):
                    try:
                        arg_sql, arg_params = self.vendor_queries.get_function_arguments_query(
                            schema, function_name
                        )
                        arg_rows = self.provider.query_executor.execute_query(
                            self.connection, arg_sql, arg_params
                        )
                        parsed_parameters: List[tuple[int, Parameter]] = []

                        for arg_row in arg_rows:
                            position_val = get_row_value(arg_row, "position")
                            if position_val is None:
                                continue
                            try:
                                position = int(position_val)
                            except (TypeError, ValueError):
                                continue

                            data_type = get_row_value(arg_row, "data_type") or "UNKNOWN"
                            direction = (get_row_value(arg_row, "in_out") or "IN").upper()

                            # POSITION = 0 represents the return type for functions
                            if position == 0:
                                if data_type:
                                    function.return_type = data_type
                                continue

                            argument_name = (
                                get_row_value(arg_row, "argument_name") or f"param_{position}"
                            )
                            parameter = Parameter(
                                name=argument_name,
                                data_type=data_type,
                                direction=direction,
                                dialect=self.dialect,
                            )
                            parsed_parameters.append((position, parameter))

                        if parsed_parameters:
                            parsed_parameters.sort(key=lambda item: item[0])
                            function.parameters = [param for _, param in parsed_parameters]
                    except Exception as exc:
                        self.log.debug(
                            f"Could not fetch argument metadata for function {schema}.{function_name}: {exc}"
                        )

                if self.vendor_queries and not getattr(function, "definition", None):
                    try:
                        def_sql, def_params = self.vendor_queries.get_function_definition_query(
                            schema, function_name
                        )
                        # BUG-01: if the vendor has no definition query (base
                        # returns (None, [])), keep the function — don't drop
                        # it entirely. Missing-definition is a capture warning,
                        # not a reason to skip the object from export.
                        if def_sql:
                            def_rows = self.provider.query_executor.execute_query(
                                self.connection, def_sql, def_params
                            )
                            if def_rows:
                                definition_value = _clean_source_text(
                                    self, get_row_value(def_rows[0], "definition")
                                )
                                if definition_value:
                                    function.definition = definition_value.strip()
                    except Exception as exc:
                        self.log.debug(
                            f"Could not fetch definition for function {schema}.{function_name}: {exc}"
                        )

                # Fallback: Parse parameters/return type from definition if still missing
                if (
                    not function.parameters or len(function.parameters) == 0
                ) or not function.return_type:
                    definition_for_parse = function.definition or definition_text
                    if definition_for_parse:
                        signature_match = re.search(
                            r"FUNCTION\s+[^\(]+\((?P<params>.*?)\)\s+RETURN\s+(?P<ret>[^\s]+)",
                            definition_for_parse,
                            re.IGNORECASE | re.DOTALL,
                        )
                        if signature_match:
                            params_section = signature_match.group("params").strip()
                            return_type = signature_match.group("ret").strip()
                            if return_type and not function.return_type:
                                function.return_type = return_type

                            if params_section and not function.parameters:
                                parameter_chunks: List[str] = []
                                current = ""
                                paren_depth = 0
                                for ch in params_section:
                                    if ch == "(":
                                        paren_depth += 1
                                    elif ch == ")":
                                        paren_depth = max(paren_depth - 1, 0)
                                    elif ch == "," and paren_depth == 0:
                                        if current.strip():
                                            parameter_chunks.append(current.strip())
                                        current = ""
                                        continue
                                    current += ch
                                if current.strip():
                                    parameter_chunks.append(current.strip())

                                manual_parameters: List[Parameter] = []
                                for part in parameter_chunks:
                                    tokens = part.split()
                                    if not tokens:
                                        continue

                                    direction = "IN"
                                    name = tokens[0]
                                    data_type = None

                                    if len(tokens) >= 3 and tokens[1].upper() in {
                                        "IN",
                                        "OUT",
                                        "INOUT",
                                    }:
                                        direction = tokens[1].upper()
                                        data_type = tokens[2]
                                    elif (
                                        tokens[0].upper() in {"IN", "OUT", "INOUT"}
                                        and len(tokens) >= 3
                                    ):
                                        direction = tokens[0].upper()
                                        name = tokens[1]
                                        data_type = tokens[2]
                                    elif len(tokens) >= 2:
                                        data_type = tokens[1]

                                    if data_type is None and len(tokens) >= 3:
                                        data_type = tokens[-1]

                                    if data_type is None:
                                        data_type = "UNKNOWN"

                                    parameter = Parameter(
                                        name=name,
                                        data_type=data_type,
                                        direction=direction,
                                        dialect=self.dialect,
                                    )
                                    manual_parameters.append(parameter)

                                if manual_parameters:
                                    function.parameters = manual_parameters

                if not function.parameters:
                    function.parameters = quirks.fetch_routine_parameters_fallback(
                        self, schema, function_name, "function"
                    )

                extension_name = (
                    get_row_value(row, "extension_name") or row.get("EXTENSION_NAME")
                    if isinstance(row, dict)
                    else None
                )
                if extension_name:
                    function.extension = extension_name  # type: ignore[attr-defined]

                # Track property capture
                if function_status:
                    function_status.add_property_status("body", function.body is not None)
                    function_status.add_property_status(
                        "definition", function.definition is not None
                    )
                    function_status.add_property_status(
                        "return_type", function.return_type is not None
                    )
                    function_status.add_property_status(
                        "volatility", function.volatility is not None
                    )

                functions.append(function)

            if len(functions) > 0:
                self.log.debug(f"Found {len(functions)} functions in schema {schema}")

            return functions

        except Exception as e:
            logger.warning(f"Error getting functions for schema {schema}: {e}")
            self.log.warning(f"Could not get functions for schema {schema}: {e}")
            if self.result_tracker:
                self.result_tracker._track_error(
                    f"Error getting functions: {e}",
                    object_type="schema",
                    object_name=schema,
                    property_name="functions",
                    exception=e,
                )
            return []

"""
Miscellaneous object extractor for schema introspection.

This module extracts various smaller object types like events, packages,
synonyms, user-defined types, extensions, etc.
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from core.introspection._utils import get_row_value
from core.introspection.extractors.base_extractor import BaseExtractor

logger = logging.getLogger(__name__)


class MiscExtractor(BaseExtractor):
    """
    Extractor for miscellaneous database objects.

    This extractor handles smaller object types that don't warrant
    their own dedicated extractor class.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the extractor and the Oracle package-spec cache.

        ``*args``/``**kwargs`` are forwarded to :class:`BaseExtractor`.
        ``_oracle_package_specs`` mirrors the cache populated by
        :class:`ProcedureExtractor` — Oracle package specs surface during
        both passes, so the misc extractor reads from the same
        ``(schema, package)``-keyed map to avoid duplicate work.
        """
        super().__init__(*args, **kwargs)
        # Cache for Oracle package specs (shared with ProcedureExtractor)
        self._oracle_package_specs: Dict[tuple[str, str], str] = {}

    def _clean_oracle_source_text(self, text: Optional[str]) -> Optional[str]:
        """Normalize raw routine source text via the plugin quirks
        hook (Oracle removes ``<E>`` XML markup; others no-op)."""
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        return quirks.clean_source_text(text)

    def _fetch_oracle_source_text(
        self, schema: str, object_name: str, object_type: str
    ) -> Optional[str]:
        """Fetch raw Oracle source text from ``ALL_SOURCE`` for the given object.

        Reached only via :meth:`OracleQuirks.enrich_packages_from_catalog`,
        which already gates on dialect — so no inline dialect check is
        needed."""
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

    def get_events(self, schema: str) -> List[Any]:
        """
        Get scheduled events in a schema (MySQL only).

        Args:
            schema: Schema name

        Returns:
            List of Event objects
        """
        from core.sql_model.event import Event

        # Scheduled events come from MySQL-family engines (MySQL +
        # MariaDB share ``information_schema.EVENTS`` and the
        # ``CREATE EVENT`` grammar). Gate on the vendor query
        # capability flag — ``MySQLMetadataQueries.supports_events``
        # returns ``True`` for both dialects.
        if not self.vendor_queries or not self.vendor_queries.supports_events():
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_events_query(schema)
            if not sql:
                return []
            results = self.provider.query_executor.execute_query(self.connection, sql, params)

            events = []
            for row in results:
                event = Event(
                    name=get_row_value(row, "event_name"),
                    schema=schema,
                    definition=get_row_value(row, "event_definition"),
                    schedule=get_row_value(row, "event_schedule"),
                    enabled=(get_row_value(row, "status") == "ENABLED"),
                    event_type=get_row_value(row, "event_type"),
                    comment=get_row_value(row, "event_comment"),
                    definer=get_row_value(row, "definer"),
                    dialect=self.dialect,
                )
                events.append(event)

            if len(events) > 0:
                self.log.debug(f"Found {len(events)} events in schema {schema}")

            return events

        except Exception as e:
            self.log.warning(f"Could not get events for schema {schema}: {e}")
            return []

    def get_packages(self, schema: str) -> List[Any]:
        """
        Get packages (Oracle) or modules (DB2) in a schema.

        Oracle packages are containers for procedures, functions, and variables.
        DB2 modules serve a similar purpose.

        Args:
            schema: Schema name

        Returns:
            List of Package objects
        """
        from core.sql_model.package import Package

        if not self.vendor_queries:
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_packages_query(schema)
            if not sql:
                return []

            self.log.debug(f"Executing get_packages query for schema: {schema}")

            results = self.provider.query_executor.execute_query(self.connection, sql, params)

            packages = []
            package_dict = {}  # Track packages by name to combine spec and body

            for row in results:
                package_name = get_row_value(row, "package_name")
                package_type = get_row_value(row, "package_type")
                definition = self._clean_oracle_source_text(get_row_value(row, "definition"))

                if not package_name:
                    continue

                # For Oracle, we get separate rows for PACKAGE (spec) and PACKAGE BODY
                # We need to combine them into a single Package object
                package_key = package_name.upper()

                if package_key not in package_dict:
                    package_dict[package_key] = Package(
                        name=package_name,
                        schema=schema,
                        spec=None,
                        body=None,
                        dialect=self.dialect,
                    )

                # Assign definition to spec or body based on package_type
                if package_type and package_type.upper() == "PACKAGE":
                    package_dict[package_key].spec = definition
                elif package_type and package_type.upper() == "PACKAGE BODY":
                    package_dict[package_key].body = definition

            # Convert dict to list and let the plugin's quirks
            # backfill missing source code (Oracle: ALL_SOURCE).
            packages = list(package_dict.values())
            from db.provider_registry import ProviderRegistry

            quirks = ProviderRegistry.get_quirks(self.dialect or "")
            quirks.enrich_packages_from_catalog(self, schema, packages)

            if len(packages) > 0:
                self.log.debug(f"Found {len(packages)} packages in schema {schema}")

            return packages

        except Exception as e:
            self.log.warning(f"Could not get packages for schema {schema}: {e}")
            return []

    def get_synonyms(self, schema: str) -> List[Any]:
        """
        Get synonyms in a schema.

        Args:
            schema: Schema name

        Returns:
            List of Synonym objects
        """
        from core.sql_model.synonym import Synonym

        if not self.vendor_queries or not self.vendor_queries.supports_synonyms():
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_synonyms_query(schema)
            if not sql:
                return []

            self.log.debug(f"Executing get_synonyms query for schema: {schema}")

            results = self.provider.query_executor.execute_query(self.connection, sql, params)

            synonyms = []
            for row in results:
                # Try multiple column name variations (DB2 driver may ignore aliases)
                synonym_name = get_row_value(row, "synonym_name") or get_row_value(row, "tabname")
                if not synonym_name:
                    continue

                synonym = Synonym(
                    name=synonym_name,
                    target_object=(
                        get_row_value(row, "target_object")
                        or get_row_value(row, "base_tabname")
                        or ""
                    ),
                    schema=schema,
                    target_schema=(
                        get_row_value(row, "target_schema") or get_row_value(row, "base_tabschema")
                        if "target_schema" in row
                        or "TARGET_SCHEMA" in row
                        or "base_tabschema" in row
                        or "BASE_TABSCHEMA" in row
                        else None
                    ),
                    target_database=(
                        get_row_value(row, "target_database")
                        if "target_database" in row or "TARGET_DATABASE" in row
                        else None
                    ),
                    db_link=(
                        get_row_value(row, "db_link")
                        if "db_link" in row or "DB_LINK" in row
                        else None
                    ),
                    dialect=self.dialect,
                )
                synonyms.append(synonym)

            if len(synonyms) > 0:
                self.log.debug(f"Found {len(synonyms)} synonyms in schema {schema}")

            return synonyms

        except Exception as e:
            logger.warning(f"Error getting synonyms for schema {schema}: {e}")
            self.log.warning(f"Could not get synonyms for schema {schema}: {e}")
            return []

    def get_user_defined_types(
        self, schema: str, get_tables_fn: Optional[Callable[..., Any]] = None
    ) -> List[Any]:
        """
        Get user-defined types in a schema.

        Uses vendor queries for detailed information like enum values and
        composite type attributes.

        Args:
            schema: Schema name
            get_tables_fn: Optional function to get tables for PostgreSQL filtering

        Returns:
            List of UserDefinedType objects
        """
        from core.sql_model.user_defined_type import UserDefinedType

        types_dict = {}

        self.ensure_metadata()

        try:
            # Method 1: Use vendor queries if available (more comprehensive)
            if self.vendor_queries and self.vendor_queries.supports_user_defined_types():
                sql, params = self.vendor_queries.get_user_defined_types_query(schema)
                if sql:
                    self.log.debug(f"Executing get_user_defined_types query for schema: {schema}")

                    results = self.provider.query_executor.execute_query(
                        self.connection, sql, params
                    )

                    for row in results:
                        type_name = get_row_value(row, "type_name")
                        if not type_name:
                            continue

                        type_category = get_row_value(row, "type_category") or "UNKNOWN"
                        comment = get_row_value(row, "comment") or get_row_value(
                            row, "type_comment"
                        )
                        base_type = get_row_value(row, "base_type")
                        definition = get_row_value(row, "definition")

                        udt = UserDefinedType(
                            name=type_name,
                            type_category=type_category,
                            schema=schema,
                            definition=definition,
                            base_type=base_type,
                            comment=comment,
                            dialect=self.dialect,
                        )

                        # For enum types, get enum values
                        if type_category.lower() in ("e", "enum"):
                            enum_sql, enum_params = self.vendor_queries.get_enum_values_query(
                                schema, type_name
                            )
                            if enum_sql:
                                enum_results = self.provider.query_executor.execute_query(
                                    self.connection, enum_sql, enum_params
                                )
                                udt.enum_values = [
                                    get_row_value(r, "enum_value") for r in enum_results
                                ]

                        # For composite types, get attributes
                        elif type_category.lower() in (
                            "c",
                            "composite",
                            "struct",
                            "object",
                            "table",
                            "varray",
                        ):
                            attr_sql, attr_params = (
                                self.vendor_queries.get_composite_type_attributes_query(
                                    schema, type_name
                                )
                            )
                            if attr_sql:
                                attr_results = self.provider.query_executor.execute_query(
                                    self.connection, attr_sql, attr_params
                                )
                                udt.attributes = [
                                    {
                                        "name": get_row_value(r, "attribute_name"),
                                        "type": get_row_value(r, "data_type"),
                                        "ordinal_position": get_row_value(r, "ordinal_position"),
                                        "is_nullable": get_row_value(r, "is_nullable"),
                                    }
                                    for r in attr_results
                                ]

                        types_dict[type_name] = udt

            user_defined_types = list(types_dict.values())

            # Vendor-specific UDT filtering (PostgreSQL: drops the
            # auto-created composite type that ``pg_type`` emits for
            # every regular table).
            from db.provider_registry import ProviderRegistry

            quirks = ProviderRegistry.get_quirks(self.dialect or "")
            user_defined_types = quirks.filter_user_defined_types(
                self, schema, user_defined_types, get_tables_fn
            )

            if len(user_defined_types) > 0:
                self.log.debug(
                    f"Found {len(user_defined_types)} user-defined types in schema {schema}"
                )

            return user_defined_types

        except Exception as e:
            logger.warning(f"Error getting user-defined types for schema {schema}: {e}")
            self.log.warning(f"Could not get user-defined types for schema {schema}: {e}")
            return []

    def get_extensions(self) -> List[Any]:
        """
        Get installed database extensions (PostgreSQL-specific).

        Args:
            None (extensions are database-wide in PostgreSQL)

        Returns:
            List of Extension objects
        """
        from core.sql_model.extension import Extension

        if not self.vendor_queries or not self.vendor_queries.supports_extensions():
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_extensions_query()
            if not sql:
                return []

            self.log.debug("Executing get_extensions query")

            results = self.provider.query_executor.execute_query(self.connection, sql, params)

            extensions = []
            for row in results:
                extension_name = get_row_value(row, "extension_name")
                if not extension_name:
                    continue

                extension = Extension(
                    name=extension_name,
                    version=get_row_value(row, "version"),
                    schema=get_row_value(row, "schema"),
                    description=get_row_value(row, "description"),
                    relocatable=bool(get_row_value(row, "relocatable")),
                    dialect=self.dialect,
                )
                extensions.append(extension)

            if extensions:
                target_schema = None
                config_db = getattr(self.provider, "config", None)
                if config_db and getattr(config_db, "database", None):
                    target_schema = getattr(config_db.database, "schema", None)

                if target_schema:
                    normalized_schema = target_schema.lower()
                    filtered_extensions = []
                    for extension in extensions:
                        schema_name = extension.schema.lower() if extension.schema else None
                        if schema_name and schema_name != normalized_schema:
                            self.log.debug(
                                f"Filtering out extension '{extension.name}' in schema "
                                f"'{extension.schema}' (target schema: '{target_schema}')"
                            )
                            continue
                        filtered_extensions.append(extension)
                    extensions = filtered_extensions

                if extensions:
                    self.log.debug(f"Found {len(extensions)} installed extensions")

            return extensions

        except Exception as e:
            logger.warning(f"Error getting extensions: {e}")
            self.log.warning(f"Could not get extensions: {e}")
            return []

    def get_foreign_data_wrappers(self) -> List[Any]:
        """
        Get foreign data wrappers (PostgreSQL-specific).
        """
        from core.introspection._utils import parse_pg_options
        from core.sql_model.foreign_data_wrapper import ForeignDataWrapper

        if not self.vendor_queries or not hasattr(
            self.vendor_queries, "get_foreign_data_wrappers_query"
        ):
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_foreign_data_wrappers_query()
            if not sql:
                return []

            self.log.debug("Executing get_foreign_data_wrappers query")

            results = self.provider.query_executor.execute_query(self.connection, sql, params)
            fdws: List[ForeignDataWrapper] = []

            for row in results:
                fdw_name = get_row_value(row, "wrapper_name")
                if not fdw_name:
                    continue

                handler_name = get_row_value(row, "handler_name")
                handler_schema = get_row_value(row, "handler_schema")
                validator_name = get_row_value(row, "validator_name")
                validator_schema = get_row_value(row, "validator_schema")

                handler = (
                    f"{handler_schema}.{handler_name}"
                    if handler_schema and handler_name
                    else handler_name
                )
                validator = (
                    f"{validator_schema}.{validator_name}"
                    if validator_schema and validator_name
                    else validator_name
                )

                options = parse_pg_options(get_row_value(row, "options"))

                fdw = ForeignDataWrapper(
                    name=fdw_name,
                    handler=handler,
                    validator=validator,
                    options=options,
                    dialect=self.dialect,
                )
                fdws.append(fdw)

            if fdws:
                self.log.debug(f"Found {len(fdws)} foreign data wrappers")

            return fdws

        except Exception as e:
            logger.warning(f"Error getting foreign data wrappers: {e}")
            self.log.warning(f"Could not get foreign data wrappers: {e}")
            return []

    def get_foreign_servers(self) -> List[Any]:
        """
        Get foreign servers (PostgreSQL-specific).
        """
        from core.introspection._utils import parse_pg_options
        from core.sql_model.foreign_server import ForeignServer

        if not self.vendor_queries:
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_foreign_servers_query()
            if not sql:
                return []

            self.log.debug("Executing get_foreign_servers query")

            results = self.provider.query_executor.execute_query(self.connection, sql, params)
            servers: List[ForeignServer] = []

            for row in results:
                server_name = get_row_value(row, "server_name")
                fdw_name = get_row_value(row, "fdw_name")
                if not server_name or not fdw_name:
                    continue

                options = parse_pg_options(get_row_value(row, "options"))

                host = options.get("host")
                port_val = options.get("port")
                port = None
                if port_val:
                    try:
                        port = int(port_val)
                    except ValueError:
                        port = None
                dbname = options.get("dbname")

                server = ForeignServer(
                    name=server_name,
                    fdw_name=fdw_name,
                    host=host,
                    port=port,
                    dbname=dbname,
                    options=options,
                    dialect=self.dialect,
                )
                servers.append(server)

            if servers:
                self.log.debug(f"Found {len(servers)} foreign servers")

            return servers

        except Exception as e:
            self.log.warning(f"Could not get foreign servers: {e}")
            return []

    def get_database_links(self, schema: str) -> List[Any]:
        """
        Get database links in a schema (Oracle-specific).

        Args:
            schema: Schema name

        Returns:
            List of DatabaseLink objects
        """
        from core.sql_model.database_link import DatabaseLink

        if not self.vendor_queries or not self.vendor_queries.supports_database_links():
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_database_links(schema)
            if not sql:
                return []

            results = self.provider.query_executor.execute_query(self.connection, sql, params)
            db_links = []

            for row in results:
                link_name = get_row_value(row, "db_link") or row.get("DB_LINK")
                username = get_row_value(row, "username") or row.get("USERNAME")
                host = get_row_value(row, "host") or row.get("HOST")

                db_link = DatabaseLink(
                    name=link_name,
                    host=host,
                    username=username,
                    schema=schema,
                    dialect=self.dialect,
                )
                db_links.append(db_link)

            self.log.debug(f"Found {len(db_links)} database links in schema {schema}")

            return db_links

        except Exception as e:
            self.log.error(f"Error getting database links: {e}")
            return []

    def get_linked_servers(self) -> List[Any]:
        """
        Get linked servers (SQL Server-specific).

        Returns:
            List of LinkedServer objects
        """
        from core.sql_model.linked_server import LinkedServer

        if not self.vendor_queries or not self.vendor_queries.supports_linked_servers():
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_linked_servers_query()
            if not sql:
                return []

            results = self.provider.query_executor.execute_query(self.connection, sql, params)
            linked_servers = []

            for row in results:
                ls = LinkedServer(
                    name=get_row_value(row, "name") or row.get("NAME", ""),
                    product=get_row_value(row, "product") or row.get("PRODUCT"),
                    provider=get_row_value(row, "provider") or row.get("PROVIDER"),
                    data_source=get_row_value(row, "data_source") or row.get("DATA_SOURCE"),
                    catalog=get_row_value(row, "catalog") or row.get("CATALOG"),
                    dialect=self.dialect,
                )
                linked_servers.append(ls)

            self.log.debug(f"Found {len(linked_servers)} linked servers")
            return linked_servers

        except Exception as e:
            self.log.error(f"Error getting linked servers: {e}")
            return []

    def get_modules(self, schema: str) -> List[Any]:
        """
        Get modules in a schema (DB2-specific).

        Args:
            schema: Schema name

        Returns:
            List of Module objects
        """
        from core.sql_model.module import Module

        if not self.vendor_queries or not self.vendor_queries.supports_modules():
            return []

        self.ensure_metadata()

        try:
            sql, params = self.vendor_queries.get_modules_query(schema)
            if not sql:
                return []

            results = self.provider.query_executor.execute_query(self.connection, sql, params)
            modules = []

            for row in results:
                module_name = get_row_value(row, "module_name") or row.get("MODULE_NAME", "")
                definition = get_row_value(row, "definition") or row.get("DEFINITION", "")
                module_schema = (
                    get_row_value(row, "module_schema") or row.get("MODULE_SCHEMA") or schema
                )
                mod = Module(
                    name=module_name,
                    definition=definition,
                    schema=module_schema,
                    dialect=self.dialect,
                )
                modules.append(mod)

            self.log.debug(f"Found {len(modules)} modules in schema {schema}")
            return modules

        except Exception as e:
            self.log.error(f"Error getting modules: {e}")
            return []

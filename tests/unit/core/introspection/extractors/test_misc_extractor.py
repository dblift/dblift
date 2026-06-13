"""
Unit tests for MiscExtractor.
Covers: get_events(), get_packages(), get_synonyms(), get_user_defined_types(),
get_extensions(), get_foreign_data_wrappers(), get_foreign_servers(),
get_database_links(), error handling, dialect guards.
"""

import unittest
from unittest.mock import MagicMock, patch

import pytest

from core.introspection.extractors.misc_extractor import MiscExtractor

pytestmark = [pytest.mark.unit]


def _make_extractor(dialect="postgresql", vendor_queries=None):
    provider = MagicMock()
    provider.query_executor = MagicMock()
    provider.config = MagicMock()
    provider.config.database = None  # no schema filter by default
    extractor = MiscExtractor(
        provider=provider,
        dialect=dialect,
        vendor_queries=vendor_queries,
    )
    extractor.ensure_metadata = MagicMock()
    return extractor


# --- _clean_oracle_source_text ---


class TestCleanOracleSourceText(unittest.TestCase):
    """``_clean_oracle_source_text`` now delegates to
    :meth:`OracleQuirks.clean_source_text`; the wrapper only does work
    when the extractor's dialect is Oracle (other dialects return the
    text unchanged via the default hook)."""

    def test_none_returns_none(self):
        e = _make_extractor(dialect="oracle")
        self.assertIsNone(e._clean_oracle_source_text(None))

    def test_empty_string_returns_empty(self):
        e = _make_extractor(dialect="oracle")
        self.assertEqual(e._clean_oracle_source_text(""), "")

    def test_removes_e_tags(self):
        e = _make_extractor(dialect="oracle")
        result = e._clean_oracle_source_text("<E>line1</E><E>line2</E>")
        self.assertNotIn("<E>", result)
        self.assertNotIn("</E>", result)

    def test_joins_with_newline(self):
        e = _make_extractor(dialect="oracle")
        result = e._clean_oracle_source_text("<E>line1</E><E>line2</E>")
        self.assertIn("\n", result)

    def test_unescapes_html_entities(self):
        e = _make_extractor(dialect="oracle")
        result = e._clean_oracle_source_text("<E>a &amp; b</E>")
        self.assertIn("a & b", result)


# --- get_events() ---


class TestGetEvents(unittest.TestCase):
    def test_non_mysql_returns_empty(self):
        extractor = _make_extractor(dialect="postgresql")
        result = extractor.get_events("public")
        self.assertEqual(result, [])

    def test_mysql_no_vendor_queries_returns_empty(self):
        extractor = _make_extractor(dialect="mysql", vendor_queries=None)
        result = extractor.get_events("mydb")
        self.assertEqual(result, [])

    def test_mysql_no_sql_returns_empty(self):
        vq = MagicMock()
        vq.get_events_query.return_value = (None, [])
        extractor = _make_extractor(dialect="mysql", vendor_queries=vq)
        result = extractor.get_events("mydb")
        self.assertEqual(result, [])

    def test_mysql_returns_events(self):
        vq = MagicMock()
        vq.get_events_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="mysql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "event_name": "daily_cleanup",
                "event_definition": "DELETE FROM logs WHERE age > 30",
                "event_schedule": "EVERY 1 DAY",
                "status": "ENABLED",
                "event_type": "RECURRING",
                "event_comment": "",
                "definer": "root@localhost",
            }
        ]
        events = extractor.get_events("mydb")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].name, "daily_cleanup")
        self.assertTrue(events[0].enabled)

    def test_mysql_empty_results(self):
        vq = MagicMock()
        vq.get_events_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="mysql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = []
        events = extractor.get_events("mydb")
        self.assertEqual(events, [])

    def test_mysql_event_not_enabled(self):
        vq = MagicMock()
        vq.get_events_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="mysql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "event_name": "ev",
                "event_definition": "SELECT 1",
                "event_schedule": "EVERY 1 HOUR",
                "status": "DISABLED",
                "event_type": "RECURRING",
                "event_comment": None,
                "definer": None,
            }
        ]
        events = extractor.get_events("mydb")
        self.assertFalse(events[0].enabled)

    def test_exception_returns_empty(self):
        vq = MagicMock()
        vq.get_events_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="mysql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        events = extractor.get_events("mydb")
        self.assertEqual(events, [])


# --- get_packages() ---


class TestGetPackages(unittest.TestCase):
    def test_no_vendor_queries_returns_empty(self):
        extractor = _make_extractor(dialect="oracle", vendor_queries=None)
        result = extractor.get_packages("myschema")
        self.assertEqual(result, [])

    def test_no_sql_returns_empty(self):
        vq = MagicMock()
        vq.get_packages_query.return_value = (None, [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        result = extractor.get_packages("myschema")
        self.assertEqual(result, [])

    def test_oracle_packages_combined(self):
        vq = MagicMock()
        vq.get_packages_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        # Two rows for same package: spec and body
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "package_name": "PKG_UTILS",
                "package_type": "PACKAGE",
                "definition": "<E>PACKAGE PKG_UTILS IS</E><E>END;</E>",
            },
            {
                "package_name": "PKG_UTILS",
                "package_type": "PACKAGE BODY",
                "definition": "<E>PACKAGE BODY PKG_UTILS IS</E><E>END;</E>",
            },
        ]
        # Mock _fetch_oracle_source_text to return None (no separate fetch needed)
        extractor._fetch_oracle_source_text = MagicMock(return_value=None)

        packages = extractor.get_packages("MYSCHEMA")
        self.assertEqual(len(packages), 1)
        self.assertEqual(packages[0].name, "PKG_UTILS")
        self.assertIsNotNone(packages[0].spec)
        self.assertIsNotNone(packages[0].body)

    def test_skips_row_with_no_package_name(self):
        vq = MagicMock()
        vq.get_packages_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {"package_name": None, "package_type": "PACKAGE", "definition": "something"},
        ]
        extractor._fetch_oracle_source_text = MagicMock(return_value=None)
        packages = extractor.get_packages("MYSCHEMA")
        self.assertEqual(packages, [])

    def test_empty_results(self):
        vq = MagicMock()
        vq.get_packages_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = []
        extractor._fetch_oracle_source_text = MagicMock(return_value=None)
        packages = extractor.get_packages("MYSCHEMA")
        self.assertEqual(packages, [])

    def test_exception_returns_empty(self):
        vq = MagicMock()
        vq.get_packages_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        packages = extractor.get_packages("MYSCHEMA")
        self.assertEqual(packages, [])


# --- get_synonyms() ---


class TestGetSynonyms(unittest.TestCase):
    def test_no_vendor_queries_returns_empty(self):
        extractor = _make_extractor(dialect="oracle", vendor_queries=None)
        result = extractor.get_synonyms("myschema")
        self.assertEqual(result, [])

    def test_not_supported_returns_empty(self):
        vq = MagicMock()
        vq.supports_synonyms.return_value = False
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        result = extractor.get_synonyms("myschema")
        self.assertEqual(result, [])

    def test_no_sql_returns_empty(self):
        vq = MagicMock()
        vq.supports_synonyms.return_value = True
        vq.get_synonyms_query.return_value = (None, [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        result = extractor.get_synonyms("myschema")
        self.assertEqual(result, [])

    def test_oracle_synonyms_returned(self):
        vq = MagicMock()
        vq.supports_synonyms.return_value = True
        vq.get_synonyms_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "synonym_name": "SYN_ORDERS",
                "target_object": "ORDERS",
                "target_schema": "PRODSCHEMA",
            }
        ]
        synonyms = extractor.get_synonyms("MYSCHEMA")
        self.assertEqual(len(synonyms), 1)
        self.assertEqual(synonyms[0].name, "SYN_ORDERS")
        self.assertEqual(synonyms[0].target_object, "ORDERS")

    def test_skips_row_with_no_name(self):
        vq = MagicMock()
        vq.supports_synonyms.return_value = True
        vq.get_synonyms_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {"synonym_name": None, "target_object": "X", "target_schema": None}
        ]
        synonyms = extractor.get_synonyms("MYSCHEMA")
        self.assertEqual(synonyms, [])

    def test_db2_uses_tabname_fallback(self):
        vq = MagicMock()
        vq.supports_synonyms.return_value = True
        vq.get_synonyms_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="db2", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "tabname": "MY_ALIAS",
                "base_tabname": "REAL_TABLE",
                "base_tabschema": "PRODSCHEMA",
            }
        ]
        synonyms = extractor.get_synonyms("MYSCHEMA")
        self.assertEqual(len(synonyms), 1)
        self.assertEqual(synonyms[0].name, "MY_ALIAS")

    def test_exception_returns_empty(self):
        vq = MagicMock()
        vq.supports_synonyms.return_value = True
        vq.get_synonyms_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        synonyms = extractor.get_synonyms("MYSCHEMA")
        self.assertEqual(synonyms, [])


# --- get_extensions() ---


class TestGetExtensions(unittest.TestCase):
    def test_no_vendor_queries_returns_empty(self):
        extractor = _make_extractor(dialect="postgresql", vendor_queries=None)
        result = extractor.get_extensions()
        self.assertEqual(result, [])

    def test_not_supported_returns_empty(self):
        vq = MagicMock()
        vq.supports_extensions.return_value = False
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        result = extractor.get_extensions()
        self.assertEqual(result, [])

    def test_no_sql_returns_empty(self):
        vq = MagicMock()
        vq.supports_extensions.return_value = True
        vq.get_extensions_query.return_value = (None, [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        result = extractor.get_extensions()
        self.assertEqual(result, [])

    def test_returns_extensions_without_schema_filter(self):
        vq = MagicMock()
        vq.supports_extensions.return_value = True
        vq.get_extensions_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "extension_name": "pg_stat_statements",
                "version": "1.9",
                "schema": "public",
                "description": "track query stats",
                "relocatable": True,
            }
        ]
        exts = extractor.get_extensions()
        self.assertEqual(len(exts), 1)
        self.assertEqual(exts[0].name, "pg_stat_statements")

    def test_skips_extension_with_no_name(self):
        vq = MagicMock()
        vq.supports_extensions.return_value = True
        vq.get_extensions_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "extension_name": None,
                "version": "1.0",
                "schema": "public",
                "description": None,
                "relocatable": False,
            }
        ]
        exts = extractor.get_extensions()
        self.assertEqual(exts, [])

    def test_schema_filter_excludes_other_schema(self):
        vq = MagicMock()
        vq.supports_extensions.return_value = True
        vq.get_extensions_query.return_value = ("SELECT 1", [])

        # Set up schema filter
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.config = MagicMock()
        extractor.provider.config.database = MagicMock()
        extractor.provider.config.database.schema = "public"

        extractor.provider.query_executor.execute_query.return_value = [
            {
                "extension_name": "pg_trgm",
                "version": "1.5",
                "schema": "public",
                "description": "trigram",
                "relocatable": True,
            },
            {
                "extension_name": "other_ext",
                "version": "1.0",
                "schema": "other_schema",
                "description": "other",
                "relocatable": False,
            },
        ]
        exts = extractor.get_extensions()
        self.assertEqual(len(exts), 1)
        self.assertEqual(exts[0].name, "pg_trgm")

    def test_exception_returns_empty(self):
        vq = MagicMock()
        vq.supports_extensions.return_value = True
        vq.get_extensions_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        exts = extractor.get_extensions()
        self.assertEqual(exts, [])


# --- get_foreign_data_wrappers() ---


class TestGetForeignDataWrappers(unittest.TestCase):
    def test_no_vendor_queries_returns_empty(self):
        extractor = _make_extractor(dialect="postgresql", vendor_queries=None)
        result = extractor.get_foreign_data_wrappers()
        self.assertEqual(result, [])

    def test_no_method_returns_empty(self):
        vq = MagicMock()
        del vq.get_foreign_data_wrappers_query  # method doesn't exist
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        result = extractor.get_foreign_data_wrappers()
        self.assertEqual(result, [])

    def test_no_sql_returns_empty(self):
        vq = MagicMock()
        vq.get_foreign_data_wrappers_query.return_value = (None, [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        result = extractor.get_foreign_data_wrappers()
        self.assertEqual(result, [])

    def test_returns_fdws(self):
        vq = MagicMock()
        vq.get_foreign_data_wrappers_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "wrapper_name": "postgres_fdw",
                "handler_name": "postgres_fdw_handler",
                "handler_schema": "public",
                "validator_name": "postgres_fdw_validator",
                "validator_schema": "public",
                "options": None,
            }
        ]
        fdws = extractor.get_foreign_data_wrappers()
        self.assertEqual(len(fdws), 1)
        self.assertEqual(fdws[0].name, "postgres_fdw")
        self.assertEqual(fdws[0].handler, "public.postgres_fdw_handler")
        self.assertEqual(fdws[0].validator, "public.postgres_fdw_validator")

    def test_skips_row_with_no_name(self):
        vq = MagicMock()
        vq.get_foreign_data_wrappers_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "wrapper_name": None,
                "handler_name": None,
                "handler_schema": None,
                "validator_name": None,
                "validator_schema": None,
                "options": None,
            }
        ]
        fdws = extractor.get_foreign_data_wrappers()
        self.assertEqual(fdws, [])

    def test_fdw_handler_without_schema(self):
        vq = MagicMock()
        vq.get_foreign_data_wrappers_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "wrapper_name": "file_fdw",
                "handler_name": "file_fdw_handler",
                "handler_schema": None,
                "validator_name": None,
                "validator_schema": None,
                "options": None,
            }
        ]
        fdws = extractor.get_foreign_data_wrappers()
        self.assertEqual(fdws[0].handler, "file_fdw_handler")

    def test_exception_returns_empty(self):
        vq = MagicMock()
        vq.get_foreign_data_wrappers_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        fdws = extractor.get_foreign_data_wrappers()
        self.assertEqual(fdws, [])


# --- get_foreign_servers() ---


class TestGetForeignServers(unittest.TestCase):
    def test_no_vendor_queries_returns_empty(self):
        extractor = _make_extractor(dialect="postgresql", vendor_queries=None)
        result = extractor.get_foreign_servers()
        self.assertEqual(result, [])

    def test_no_sql_returns_empty(self):
        vq = MagicMock()
        vq.get_foreign_servers_query.return_value = (None, [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        result = extractor.get_foreign_servers()
        self.assertEqual(result, [])

    def test_returns_servers(self):
        vq = MagicMock()
        vq.get_foreign_servers_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "server_name": "remote_db",
                "fdw_name": "postgres_fdw",
                "options": "host=192.168.1.1,port=5432,dbname=prod",
            }
        ]
        servers = extractor.get_foreign_servers()
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0].name, "remote_db")
        self.assertEqual(servers[0].fdw_name, "postgres_fdw")
        self.assertEqual(servers[0].host, "192.168.1.1")
        self.assertEqual(servers[0].port, 5432)
        self.assertEqual(servers[0].dbname, "prod")

    def test_skips_row_with_no_server_name(self):
        vq = MagicMock()
        vq.get_foreign_servers_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {"server_name": None, "fdw_name": "fdw", "options": None}
        ]
        servers = extractor.get_foreign_servers()
        self.assertEqual(servers, [])

    def test_skips_row_with_no_fdw_name(self):
        vq = MagicMock()
        vq.get_foreign_servers_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {"server_name": "s", "fdw_name": None, "options": None}
        ]
        servers = extractor.get_foreign_servers()
        self.assertEqual(servers, [])

    def test_invalid_port_handled(self):
        vq = MagicMock()
        vq.get_foreign_servers_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {"server_name": "s", "fdw_name": "f", "options": "host=h,port=not_a_number"}
        ]
        servers = extractor.get_foreign_servers()
        self.assertEqual(len(servers), 1)
        self.assertIsNone(servers[0].port)

    def test_exception_returns_empty(self):
        vq = MagicMock()
        vq.get_foreign_servers_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        servers = extractor.get_foreign_servers()
        self.assertEqual(servers, [])


# --- get_database_links() ---


class TestGetDatabaseLinks(unittest.TestCase):
    def test_no_vendor_queries_returns_empty(self):
        extractor = _make_extractor(dialect="oracle", vendor_queries=None)
        result = extractor.get_database_links("MYSCHEMA")
        self.assertEqual(result, [])

    def test_not_supported_returns_empty(self):
        vq = MagicMock()
        vq.supports_database_links.return_value = False
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        result = extractor.get_database_links("MYSCHEMA")
        self.assertEqual(result, [])

    def test_no_sql_returns_empty(self):
        vq = MagicMock()
        vq.supports_database_links.return_value = True
        vq.get_database_links.return_value = (None, [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        result = extractor.get_database_links("MYSCHEMA")
        self.assertEqual(result, [])

    def test_returns_database_links(self):
        vq = MagicMock()
        vq.supports_database_links.return_value = True
        vq.get_database_links.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "db_link": "REMOTE_LINK",
                "username": "admin",
                "host": "192.168.1.100",
            }
        ]
        links = extractor.get_database_links("MYSCHEMA")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].name, "REMOTE_LINK")
        self.assertEqual(links[0].username, "admin")
        self.assertEqual(links[0].host, "192.168.1.100")

    def test_exception_returns_empty(self):
        vq = MagicMock()
        vq.supports_database_links.return_value = True
        vq.get_database_links.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        links = extractor.get_database_links("MYSCHEMA")
        self.assertEqual(links, [])


# --- get_user_defined_types() ---


class TestGetUserDefinedTypes(unittest.TestCase):
    def test_vendor_queries_returns_enum_types(self):
        vq = MagicMock()
        vq.supports_user_defined_types.return_value = True
        vq.get_user_defined_types_query.return_value = ("SELECT 1", [])
        vq.get_enum_values_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)

        extractor.provider.query_executor.execute_query.side_effect = [
            # UDT query
            [
                {
                    "type_name": "mood",
                    "type_category": "e",
                    "comment": None,
                    "base_type": None,
                    "definition": None,
                }
            ],
            # Enum values query
            [{"enum_value": "happy"}, {"enum_value": "sad"}],
        ]
        udts = extractor.get_user_defined_types("public")
        self.assertEqual(len(udts), 1)
        self.assertEqual(udts[0].name, "mood")
        self.assertEqual(udts[0].enum_values, ["happy", "sad"])

    def test_vendor_queries_returns_composite_types(self):
        vq = MagicMock()
        vq.supports_user_defined_types.return_value = True
        vq.get_user_defined_types_query.return_value = ("SELECT 1", [])
        vq.get_composite_type_attributes_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)

        extractor.provider.query_executor.execute_query.side_effect = [
            # UDT query
            [
                {
                    "type_name": "address_type",
                    "type_category": "c",
                    "comment": None,
                    "base_type": None,
                    "definition": None,
                }
            ],
            # Attributes query
            [
                {
                    "attribute_name": "street",
                    "data_type": "varchar",
                    "ordinal_position": 1,
                    "is_nullable": "YES",
                },
                {
                    "attribute_name": "city",
                    "data_type": "varchar",
                    "ordinal_position": 2,
                    "is_nullable": "YES",
                },
            ],
        ]
        udts = extractor.get_user_defined_types("public")
        self.assertEqual(len(udts), 1)
        self.assertEqual(len(udts[0].attributes), 2)

    def test_no_vendor_queries_returns_empty_udt_list(self):
        """When no vendor query exists, native introspection returns no UDTs."""
        extractor = _make_extractor(dialect="postgresql", vendor_queries=None)

        udts = extractor.get_user_defined_types("public")

        self.assertEqual(udts, [])

    def test_vendor_query_skips_row_with_no_name(self):
        vq = MagicMock()
        vq.supports_user_defined_types.return_value = True
        vq.get_user_defined_types_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "type_name": None,
                "type_category": "e",
                "comment": None,
                "base_type": None,
                "definition": None,
            }
        ]
        udts = extractor.get_user_defined_types("public")
        self.assertEqual(udts, [])

    def test_postgresql_filters_table_generated_composite_types(self):
        vq = MagicMock()
        vq.supports_user_defined_types.return_value = True
        vq.get_user_defined_types_query.return_value = ("SELECT 1", [])
        vq.get_composite_type_attributes_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)

        # First call: UDT rows; subsequent calls: empty (for attribute queries per type)
        call_count = [0]

        def mock_execute(conn, sql, params):
            call_count[0] += 1
            if call_count[0] == 1:
                return [
                    {
                        "type_name": "users",
                        "type_category": "c",
                        "comment": None,
                        "base_type": None,
                        "definition": None,
                    },
                    {
                        "type_name": "custom_type",
                        "type_category": "c",
                        "comment": None,
                        "base_type": None,
                        "definition": None,
                    },
                ]
            return []

        extractor.provider.query_executor.execute_query.side_effect = mock_execute

        # Mock get_tables_fn
        from core.sql_model.table import Table

        mock_table = Table(name="users", schema="public", dialect="postgresql")

        def mock_get_tables(schema, include_views=False):
            return [mock_table]

        udts = extractor.get_user_defined_types("public", get_tables_fn=mock_get_tables)
        # 'users' composite type should be filtered out
        names = [u.name for u in udts]
        self.assertNotIn("users", names)
        self.assertIn("custom_type", names)

    def test_exception_returns_empty(self):
        vq = MagicMock()
        vq.supports_user_defined_types.return_value = True
        vq.get_user_defined_types_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        udts = extractor.get_user_defined_types("public")
        self.assertEqual(udts, [])


# --- _fetch_oracle_source_text ---


class TestFetchOracleSourceText(unittest.TestCase):
    def test_non_oracle_returns_none(self):
        extractor = _make_extractor(dialect="postgresql")
        result = extractor._fetch_oracle_source_text("myschema", "pkg", "PACKAGE")
        self.assertIsNone(result)

    def test_oracle_returns_source_text(self):
        extractor = _make_extractor(dialect="oracle")
        extractor.provider.query_executor.execute_query.return_value = [
            {"text": "PACKAGE PKG_UTILS IS\n"},
            {"text": "  FUNCTION f RETURN NUMBER;\n"},
            {"text": "END;\n"},
        ]
        result = extractor._fetch_oracle_source_text("MYSCHEMA", "PKG_UTILS", "PACKAGE")
        self.assertIn("PKG_UTILS", result)

    def test_oracle_empty_source_returns_none(self):
        extractor = _make_extractor(dialect="oracle")
        extractor.provider.query_executor.execute_query.return_value = []
        result = extractor._fetch_oracle_source_text("MYSCHEMA", "PKG_UTILS", "PACKAGE")
        self.assertIsNone(result)

    def test_oracle_query_exception_returns_none(self):
        extractor = _make_extractor(dialect="oracle")
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        result = extractor._fetch_oracle_source_text("MYSCHEMA", "PKG_UTILS", "PACKAGE")
        self.assertIsNone(result)

    def test_no_query_executor_returns_none(self):
        provider = MagicMock()
        del provider.query_executor
        extractor = MiscExtractor(provider=provider, dialect="oracle")
        extractor.ensure_metadata = MagicMock()
        result = extractor._fetch_oracle_source_text("MYSCHEMA", "PKG", "PACKAGE")
        self.assertIsNone(result)


# --- get_linked_servers ---


class TestGetLinkedServers(unittest.TestCase):
    def test_returns_empty_when_no_vendor_queries(self):
        e = _make_extractor(dialect="sqlserver", vendor_queries=None)
        result = e.get_linked_servers()
        self.assertEqual(result, [])

    def test_returns_empty_when_not_supported(self):
        vq = MagicMock()
        vq.supports_linked_servers.return_value = False
        e = _make_extractor(dialect="sqlserver", vendor_queries=vq)
        result = e.get_linked_servers()
        self.assertEqual(result, [])

    def test_returns_empty_when_query_is_none(self):
        vq = MagicMock()
        vq.supports_linked_servers.return_value = True
        vq.get_linked_servers_query.return_value = (None, [])
        e = _make_extractor(dialect="sqlserver", vendor_queries=vq)
        result = e.get_linked_servers()
        self.assertEqual(result, [])

    def test_returns_linked_server_objects(self):
        from core.sql_model.linked_server import LinkedServer

        vq = MagicMock()
        vq.supports_linked_servers.return_value = True
        vq.get_linked_servers_query.return_value = ("SELECT ...", [])
        e = _make_extractor(dialect="sqlserver", vendor_queries=vq)
        e.provider.query_executor.execute_query.return_value = [
            {
                "name": "remote1",
                "product": "SQL Server",
                "provider": "SQLNCLI",
                "data_source": "remote.host.com",
                "catalog": "db",
            }
        ]
        result = e.get_linked_servers()
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], LinkedServer)
        self.assertEqual(result[0].name, "remote1")

    def test_returns_empty_on_exception(self):
        vq = MagicMock()
        vq.supports_linked_servers.return_value = True
        vq.get_linked_servers_query.return_value = ("SELECT ...", [])
        e = _make_extractor(dialect="sqlserver", vendor_queries=vq)
        e.provider.query_executor.execute_query.side_effect = Exception("fail")
        result = e.get_linked_servers()
        self.assertEqual(result, [])


# --- get_modules ---


class TestGetModules(unittest.TestCase):
    def test_returns_empty_when_no_vendor_queries(self):
        e = _make_extractor(dialect="db2", vendor_queries=None)
        result = e.get_modules("MYSCHEMA")
        self.assertEqual(result, [])

    def test_returns_empty_when_not_supported(self):
        vq = MagicMock()
        vq.supports_modules.return_value = False
        e = _make_extractor(dialect="db2", vendor_queries=vq)
        result = e.get_modules("MYSCHEMA")
        self.assertEqual(result, [])

    def test_returns_empty_when_query_is_none(self):
        vq = MagicMock()
        vq.supports_modules.return_value = True
        vq.get_modules_query.return_value = (None, [])
        e = _make_extractor(dialect="db2", vendor_queries=vq)
        result = e.get_modules("MYSCHEMA")
        self.assertEqual(result, [])

    def test_returns_module_objects(self):
        from core.sql_model.module import Module

        vq = MagicMock()
        vq.supports_modules.return_value = True
        vq.get_modules_query.return_value = ("SELECT ...", ["MYSCHEMA"])
        e = _make_extractor(dialect="db2", vendor_queries=vq)
        e.provider.query_executor.execute_query.return_value = [
            {
                "module_name": "MY_MODULE",
                "module_schema": "MYSCHEMA",
                "definition": "CREATE MODULE MY_MODULE END MODULE;",
            }
        ]
        result = e.get_modules("MYSCHEMA")
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], Module)
        self.assertEqual(result[0].name, "MY_MODULE")

    def test_returns_empty_on_exception(self):
        vq = MagicMock()
        vq.supports_modules.return_value = True
        vq.get_modules_query.return_value = ("SELECT ...", ["MYSCHEMA"])
        e = _make_extractor(dialect="db2", vendor_queries=vq)
        e.provider.query_executor.execute_query.side_effect = Exception("fail")
        result = e.get_modules("MYSCHEMA")
        self.assertEqual(result, [])

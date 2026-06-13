"""Story 20-18 — formalisation ABC VendorMetadataQueries : 13 nouvelles méthodes optionnelles."""

import inspect
from unittest.mock import MagicMock

import pytest

from core.introspection.vendor_queries_base import VendorMetadataQueries


class ConcreteVendorQueries(VendorMetadataQueries):
    """Minimal concrete implementation for testing (implements only abstract methods)."""

    def get_check_constraints_query(self, schema, table):
        return ("SELECT 1", [])

    def get_sequences_query(self, schema):
        return ("SELECT 1", [])

    def get_views_query(self, schema):
        return ("SELECT 1", [])

    def get_view_definition_query(self, schema, view_name):
        return ("SELECT 1", [])

    def get_indexes_query(self, schema, table):
        return ("SELECT 1", [])


# --- AC#7.1 — 13 tests paramétriques pour les nouvelles méthodes ---

_NEW_METHODS_WITH_ARGS = [
    ("get_unique_constraints_query", ("s", "t")),
    ("get_table_properties_query", ("s", "t")),
    ("get_partition_scheme_query", ("s", "t")),
    ("get_table_inheritance_query", ("s", "t")),
    ("get_table_row_security_query", ("s", "t")),
    ("get_policies_query", ("s", "t")),
    ("get_partitioned_tables_query", ("s",)),
    ("get_packages_query", ("s",)),
    ("get_function_definition_query", ("s", "fn")),
    ("get_parameters_query", ("s", "rn")),
    ("get_column_defaults_query", ("s", "t")),
    ("get_events_query", ("s",)),
    ("get_foreign_servers_query", ()),
]


@pytest.mark.unit
class TestVendorQueriesNewMethods:
    """AC#7.1 — Chaque nouvelle méthode retourne (None, []) par défaut."""

    @pytest.mark.parametrize(
        "method_name,args", _NEW_METHODS_WITH_ARGS, ids=[m for m, _ in _NEW_METHODS_WITH_ARGS]
    )
    def test_default_returns_none_empty_list(self, method_name, args):
        vq = ConcreteVendorQueries()
        result = getattr(vq, method_name)(*args)
        assert result == (None, []), f"{method_name} should return (None, []) by default"


@pytest.mark.unit
class TestVendorQueriesIsCompleteABC:
    """AC#7.2 — Les nouvelles méthodes sont optionnelles (pas abstraites)."""

    def test_abstract_method_count_unchanged(self):
        """Le nombre de méthodes abstraites ne doit pas avoir augmenté."""
        abstract_methods = VendorMetadataQueries.__abstractmethods__
        assert (
            len(abstract_methods) == 5
        ), f"Expected 5 abstract methods, got {len(abstract_methods)}: {abstract_methods}"

    def test_abstract_methods_are_original_five(self):
        """Les 5 méthodes abstraites originales sont inchangées."""
        expected = {
            "get_check_constraints_query",
            "get_sequences_query",
            "get_views_query",
            "get_view_definition_query",
            "get_indexes_query",
        }
        assert VendorMetadataQueries.__abstractmethods__ == expected

    def test_new_methods_are_not_abstract(self):
        """Aucune des 13 nouvelles méthodes n'est abstraite."""
        for method_name, _ in _NEW_METHODS_WITH_ARGS:
            assert (
                method_name not in VendorMetadataQueries.__abstractmethods__
            ), f"{method_name} should NOT be abstract"


@pytest.mark.unit
class TestExistingSubclassesUnchanged:
    """AC#7.3 — Les 6 implémentations dialectes s'instancient sans erreur."""

    @pytest.mark.parametrize(
        "cls_path",
        [
            "db.plugins.db2.introspection.db2_queries.DB2MetadataQueries",
            "db.plugins.oracle.introspection.oracle_queries.OracleMetadataQueries",
            "db.plugins.postgresql.introspection.postgresql_queries.PostgreSQLMetadataQueries",
            "db.plugins.mysql.introspection.mysql_queries.MySQLMetadataQueries",
            "db.plugins.sqlserver.introspection.sqlserver_queries.SQLServerMetadataQueries",
            "db.plugins.sqlite.introspection.sqlite_queries.SQLiteMetadataQueries",
        ],
        ids=["DB2", "Oracle", "PostgreSQL", "MySQL", "SqlServer", "SQLite"],
    )
    def test_dialect_subclass_instantiates(self, cls_path):
        """Smoke test — chaque sous-classe s'instancie sans TypeError."""
        module_path, class_name = cls_path.rsplit(".", 1)
        import importlib

        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        instance = cls()
        assert isinstance(instance, VendorMetadataQueries)


# --- Review fixes (code review story 20-18) ---


@pytest.mark.unit
class TestHasattrRemovedFromIntrospector:
    """Review H1/H2 — hasattr vendor_queries supprimés de schema_introspector."""

    def test_apply_vendor_table_properties_no_hasattr_get_table_properties(self):
        """H1 — hasattr(vendor_queries, 'get_table_properties_query') supprimé du bloc SQL Server."""
        from core.introspection.schema_introspector import SchemaIntrospector

        source = inspect.getsource(SchemaIntrospector._apply_vendor_table_properties)
        assert (
            'hasattr(self.vendor_queries, "get_table_properties_query")' not in source
            and "hasattr(self.vendor_queries, 'get_table_properties_query')" not in source
        ), (
            "hasattr(vendor_queries, 'get_table_properties_query') encore présent dans "
            "_apply_vendor_table_properties — doit être supprimé (méthode garantie par l'ABC)"
        )

    def test_introspect_schema_no_hasattr_get_partition_scheme(self):
        """H2 — hasattr(vendor_queries, 'get_partition_scheme_query') supprimé du call-site."""
        from core.introspection.schema_introspector import SchemaIntrospector

        source = inspect.getsource(SchemaIntrospector.introspect_schema)
        assert (
            'hasattr(self.vendor_queries, "get_partition_scheme_query")' not in source
            and "hasattr(self.vendor_queries, 'get_partition_scheme_query')" not in source
        ), (
            "hasattr(vendor_queries, 'get_partition_scheme_query') encore présent dans "
            "introspect_schema — doit être supprimé (méthode garantie par l'ABC)"
        )


@pytest.mark.unit
class TestQueryNoneGuards:
    """Review M1/M2 — guards if not query après suppression des hasattr."""

    def test_column_extractor_returns_columns_when_query_is_none(self):
        """M1 — column_extractor retourne les colonnes inchangées si get_column_defaults_query → None."""
        from core.introspection.extractors.column_extractor import ColumnExtractor
        from core.sql_model.base import SqlColumn

        provider = MagicMock()
        provider.config.database.type = "sqlserver"
        extractor = ColumnExtractor(
            provider=provider,
            connection=MagicMock(),
            metadata=MagicMock(),
            vendor_queries=MagicMock(),
            dialect="sqlserver",
        )
        extractor.vendor_queries.get_column_defaults_query.return_value = (None, [])

        col = SqlColumn(name="id", data_type="INT")
        result = extractor._enhance_with_vendor_queries("dbo", "users", [col])

        assert result == [col]
        extractor.provider.query_executor.execute_query.assert_not_called()

    def test_procedure_extractor_returns_empty_when_query_is_none(self):
        """M2 — procedure_extractor retourne [] si get_parameters_query → None."""
        from core.introspection.extractors.procedure_extractor import ProcedureExtractor

        provider = MagicMock()
        provider.config.database.type = "mysql"
        extractor = ProcedureExtractor(
            provider=provider,
            connection=MagicMock(),
            metadata=MagicMock(),
            vendor_queries=MagicMock(),
            dialect="mysql",
        )
        extractor.vendor_queries.get_parameters_query.return_value = (None, [])

        result = extractor._fetch_mysql_routine_parameters("mydb", "my_proc")

        assert result == []
        extractor.provider.query_executor.execute_query.assert_not_called()


@pytest.mark.unit
class TestNoDoubleMiscLogging:
    """Review M3 — pas de double logging dans les méthodes misc_extractor touchées par la story."""

    def _make_misc_extractor(self):
        from core.introspection.extractors.misc_extractor import MiscExtractor

        provider = MagicMock()
        provider.config.database.type = "mysql"
        extractor = MiscExtractor(
            provider=provider,
            connection=MagicMock(),
            metadata=MagicMock(),
            vendor_queries=MagicMock(),
            dialect="mysql",
        )
        extractor.log = MagicMock()
        extractor.ensure_metadata = MagicMock()
        return extractor

    def test_get_events_logs_only_once_on_exception(self):
        """M3 — get_events: une seule entrée log lors d'une exception."""
        extractor = self._make_misc_extractor()
        extractor.vendor_queries.get_events_query.side_effect = RuntimeError("boom")

        extractor.get_events("mydb")

        assert extractor.log.warning.call_count == 1

    def test_get_packages_logs_only_once_on_exception(self):
        """M3 — get_packages: une seule entrée log lors d'une exception."""
        extractor = self._make_misc_extractor()
        extractor.dialect = "oracle"
        extractor.vendor_queries.get_packages_query.side_effect = RuntimeError("boom")

        extractor.get_packages("myschema")

        assert extractor.log.warning.call_count == 1

    def test_get_foreign_servers_logs_only_once_on_exception(self):
        """M3 — get_foreign_servers: une seule entrée log lors d'une exception."""
        extractor = self._make_misc_extractor()
        extractor.vendor_queries.get_foreign_servers_query.side_effect = RuntimeError("boom")

        extractor.get_foreign_servers()

        assert extractor.log.warning.call_count == 1

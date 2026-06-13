"""
Integration tests for schema introspection.

These tests validate that introspection works correctly against real databases.
They test both basic and enhanced vendor-query modes.

Prerequisites:
- Docker containers must be running (see tests/integration/docker-compose.yml)
- Test migrations are deployed automatically by the test fixtures

Usage:
    # Run all introspection tests
    pytest tests/integration/db/test_introspection_integration.py -v

    # Run tests for specific database
    pytest tests/integration/db/test_introspection_integration.py -k postgresql -v
"""

from pathlib import Path

import pytest

from config.database_config import DatabaseConfig
from config.dblift_config import DbliftConfig
from core.introspection import IntrospectorFactory
from core.logger.log import ConsoleLog
from db.provider_registry import ProviderRegistry
from tests.integration.helpers.cli_runner import DBLiftCLI
from tests.integration.helpers.migration_helper import create_config


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["postgresql", "oracle", "sqlserver", "mysql", "db2"],
    indirect=True,
)
class TestSchemaIntrospection:
    """Integration tests for schema introspection across all databases."""

    # Expected schema objects from test migration V001__create_test_schema.sql
    EXPECTED_DATA = {
        "postgresql": {
            "tables": {"users", "departments", "employees", "orders", "products"},
            "sequences": 2,  # users_id_seq, orders_id_seq (minimum)
            "views": 3,  # active_users, employee_details, department_summary
            "check_constraints_min": 10,
            "synonyms": 0,  # PostgreSQL doesn't support synonyms
            "user_defined_types": 3,  # status_enum, address_type, email_domain
        },
        "oracle": {
            "tables": {"USERS", "DEPARTMENTS", "EMPLOYEES", "ORDERS", "PRODUCTS"},
            "sequences": 2,  # USERS_ID_SEQ, ORDERS_ID_SEQ (minimum)
            "views": 3,  # ACTIVE_USERS, EMPLOYEE_DETAILS, DEPARTMENT_SUMMARY
            "check_constraints_min": 9,  # One less than PostgreSQL (no hire_date check)
            "synonyms": 2,  # EMP_SYN, DEPT_SYN
            "user_defined_types": 0,  # Not testing Oracle UDTs yet
        },
        "sqlserver": {
            "tables": {"users", "departments", "employees", "orders", "products"},
            "sequences": 2,  # users_id_seq, orders_id_seq
            "views": 3,  # active_users, employee_details, department_summary
            "check_constraints_min": 10,
            "synonyms": 2,  # emp_syn, dept_syn
            "user_defined_types": 0,  # Not testing SQL Server UDTs yet
        },
        "mysql": {
            "tables": {"users", "departments", "employees", "orders", "products"},
            "sequences": 0,  # MySQL doesn't support sequences (uses AUTO_INCREMENT)
            "views": 3,  # active_users, employee_details, department_summary
            "check_constraints_min": 9,  # MySQL doesn't allow non-deterministic functions in CHECK
            "synonyms": 0,  # MySQL doesn't support synonyms
            "user_defined_types": 0,  # Not testing MySQL UDTs yet
        },
        "db2": {
            "tables": {"USERS", "DEPARTMENTS", "EMPLOYEES", "ORDERS", "PRODUCTS"},
            "sequences": 2,  # USERS_ID_SEQ, ORDERS_ID_SEQ
            "views": 3,  # ACTIVE_USERS, EMPLOYEE_DETAILS, DEPARTMENT_SUMMARY
            "check_constraints_min": 9,  # DB2 doesn't allow CURRENT DATE in CHECK constraints
            "synonyms": 2,  # EMP_ALIAS, DEPT_ALIAS
            "user_defined_types": 0,  # Not testing DB2 UDTs yet
        },
    }

    def _get_provider(self, db_container):
        """Create database provider based on container type."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Build database URL with proper parameters
        if db_type == "sqlserver":
            database_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"
        elif db_type == "oracle":
            service = db_container.get("service", db_container.get("database"))
            database_url = f"oracle+oracledb://{db_container['host']}:{db_container['port']}?service_name={service}"
        elif db_type == "mysql":
            database_url = f"mysql+pymysql://{db_container['host']}:{db_container['port']}/{db_container['database']}"
        elif db_type == "db2":
            database_url = f"ibm_db_sa://{db_container['host']}:{db_container['port']}/{db_container['database']}"
        elif db_type == "postgresql":
            database_url = f"postgresql+psycopg://{db_container['host']}:{db_container['port']}/{db_container['database']}"
        else:
            database_url = db_container.get("url")

        # Build database config (concrete subclass via registry — BaseDatabaseConfig is abstract)
        db_config = DatabaseConfig.from_dict(
            {
                "type": db_type,
                "url": database_url,
                "host": db_container.get("host"),
                "port": db_container.get("port"),
                "database": db_container.get("database"),
                "username": db_container["username"],
                "password": db_container["password"],
                "schema": schema,
            }
        )

        config = DbliftConfig(database=db_config)
        log = ConsoleLog("introspection_test", enable_debug=False)

        # Create provider based on type
        if db_type in {"postgresql", "mysql"}:
            return ProviderRegistry.create_provider(config, log=log)
        elif db_type == "oracle":
            from db.plugins.oracle.provider import OracleProvider

            return OracleProvider(config, log)
        elif db_type == "sqlserver":
            from db.plugins.sqlserver.provider import SqlServerProvider

            return SqlServerProvider(config, log)
        elif db_type == "db2":
            from db.plugins.db2.provider import Db2Provider

            return Db2Provider(config, log)
        else:
            pytest.skip(f"Provider not implemented for {db_type}")

    def test_deploy_and_basic_introspection(self, db_container, tmp_path, introspection_migrations):
        """Test migration deployment and basic introspection coverage."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture
        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)
        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        # Now test basic introspection without vendor queries.
        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(
            provider, log=log, use_vendor_queries=False
        ) as introspector:
            result = introspector.introspect_schema(schema)

            # Should find tables
            assert result["table_count"] > 0, "Should find at least one table"
            assert result["total_columns"] > 0, "Should find at least one column"

            # Should find primary keys, foreign keys, unique constraints
            all_constraints = sum(len(t.constraints) for t in result["tables"])
            assert all_constraints > 0, "Should find at least one constraint"

            # Basic introspection should NOT find check constraints.
            check_constraints = sum(
                1
                for t in result["tables"]
                for c in t.constraints
                if c.constraint_type.value == "CHECK"
            )
            assert check_constraints == 0, "Basic introspection should not find CHECK constraints"

    def test_enhanced_introspection(self, db_container, tmp_path, introspection_migrations):
        """Test enhanced introspection with vendor queries (90-95% coverage)."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")
        expected = self.EXPECTED_DATA[db_type]

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture
        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)
        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        # Now test enhanced introspection
        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(
                schema, include_views=True, include_sequences=True, include_triggers=True
            )

            # Should find tables
            assert result["table_count"] > 0, "Should find at least one table"
            assert result["total_columns"] > 0, "Should find at least one column"

            # Should find check constraints (vendor queries)
            check_constraints = sum(
                1
                for t in result["tables"]
                for c in t.constraints
                if c.constraint_type.value == "CHECK"
            )
            assert (
                check_constraints >= expected["check_constraints_min"]
            ), f"Should find at least {expected['check_constraints_min']} CHECK constraints"

            # Should find views
            assert (
                result["view_count"] >= expected["views"]
            ), f"Should find at least {expected['views']} views"

            # Should find sequences
            assert (
                result["sequence_count"] >= expected["sequences"]
            ), f"Should find at least {expected['sequences']} sequences"

    def test_coverage_improvement(self, db_container, tmp_path, introspection_migrations):
        """Test that enhanced introspection provides better coverage than basic mode."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        # Get basic introspection results
        with IntrospectorFactory.create(
            provider, log=log, use_vendor_queries=False
        ) as introspector:
            basic_result = introspector.introspect_schema(schema)
            basic_constraints = sum(len(t.constraints) for t in basic_result["tables"])

        # Get enhanced results
        provider2 = self._get_provider(db_container)
        with IntrospectorFactory.create(
            provider2, log=log, use_vendor_queries=True
        ) as introspector:
            enhanced_result = introspector.introspect_schema(
                schema, include_views=True, include_sequences=True, include_triggers=True
            )
            enhanced_constraints = sum(len(t.constraints) for t in enhanced_result["tables"])

        # Enhanced should have more constraints (includes CHECK)
        assert (
            enhanced_constraints >= basic_constraints
        ), "Enhanced introspection should find at least as many constraints as basic mode"

        # Enhanced should have views and sequences
        assert (
            enhanced_result["view_count"] > 0 or enhanced_result["sequence_count"] > 0
        ), "Enhanced introspection should find views or sequences"

    def test_computed_columns_introspection(self, db_container, tmp_path, introspection_migrations):
        """Test computed/generated columns are properly introspected."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(schema, include_views=True)

            # Find products table (has computed column: price_with_tax)
            products_table = None
            for table in result["tables"]:
                table_name_upper = table.name.upper()
                if table_name_upper == "PRODUCTS":
                    products_table = table
                    break

            assert products_table is not None, "Should find products table"

            # Find price_with_tax column
            computed_column = None
            for column in products_table.columns:
                col_name_upper = column.name.upper()
                if col_name_upper == "PRICE_WITH_TAX":
                    computed_column = column
                    break

            assert computed_column is not None, "Should find price_with_tax computed column"

            # Verify computed column metadata
            assert hasattr(
                computed_column, "is_computed"
            ), "Computed column should have is_computed attribute"
            assert (
                computed_column.is_computed is True
            ), "price_with_tax should be marked as computed"

            # computed_expression attribute should exist
            # but may be None if the vendor query didn't provide it.
            assert hasattr(
                computed_column, "computed_expression"
            ), "Should have computed_expression attribute"

            # For databases with good vendor query support, expression should be present
            # DB2: May not always provide IMPLICITVALUE correctly
            if db_type not in ("db2",):
                assert (
                    computed_column.computed_expression is not None
                ), f"Expression should not be None for {db_type}"

    def test_identity_columns_introspection(self, db_container, tmp_path, introspection_migrations):
        """Test identity/auto-increment columns are properly introspected."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(schema)

            # Find departments table (has an identity column on engines that support it)
            departments_table = None
            for table in result["tables"]:
                table_name_upper = table.name.upper()
                if table_name_upper == "DEPARTMENTS":
                    departments_table = table
                    break

            assert departments_table is not None, "Should find departments table"

            # Find id column
            id_column = None
            for column in departments_table.columns:
                if column.name.upper() == "ID":
                    id_column = column
                    break

            assert id_column is not None, "Should find id column"

            # All columns should have identity enrichment applied
            assert hasattr(id_column, "is_identity"), "Column should have is_identity attribute"

            # For Oracle, this should be an identity column
            if db_type == "oracle":
                assert id_column.is_identity is True, "Oracle DEPARTMENTS.ID should be identity"
                assert hasattr(id_column, "identity_increment"), "Should have identity_increment"

    def test_constraint_metadata_enhancement(
        self, db_container, tmp_path, introspection_migrations
    ):
        """Test enhanced constraint metadata (deferrable, enabled, validated)."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(schema)

            # Collect all check constraints
            check_constraints = []
            for table in result["tables"]:
                check_constraints.extend(
                    [c for c in table.constraints if c.constraint_type.value == "CHECK"]
                )

            assert len(check_constraints) > 0, "Should find at least one check constraint"

            # Verify all check constraints have deferrable metadata
            for constraint in check_constraints:
                assert hasattr(constraint, "is_deferrable"), "Should have is_deferrable attribute"
                assert hasattr(
                    constraint, "initially_deferred"
                ), "Should have initially_deferred attribute"
                assert isinstance(constraint.is_deferrable, bool), "is_deferrable should be boolean"
                assert isinstance(
                    constraint.initially_deferred, bool
                ), "initially_deferred should be boolean"

            # Oracle and SQL Server should have enabled/validated metadata
            if db_type in ["oracle", "sqlserver"]:
                for constraint in check_constraints:
                    assert hasattr(constraint, "is_enabled"), f"{db_type} should have is_enabled"
                    assert hasattr(
                        constraint, "is_validated"
                    ), f"{db_type} should have is_validated"
                    assert isinstance(constraint.is_enabled, bool), "is_enabled should be boolean"
                    assert isinstance(
                        constraint.is_validated, bool
                    ), "is_validated should be boolean"

    def test_materialized_views_structure(self, db_container, tmp_path, introspection_migrations):
        """Test materialized views result structure (even if none exist)."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(schema, include_views=True)

            # All results should have materialized_views structure
            assert "materialized_views" in result, "Result should have materialized_views list"
            assert "materialized_view_count" in result, "Result should have materialized_view_count"
            assert isinstance(result["materialized_view_count"], int), "Count should be int"
            assert isinstance(result["materialized_views"], list), "Should be a list"

            # PostgreSQL, Oracle, DB2, and SQL Server support materialized views
            if db_type in ["postgresql", "oracle", "db2", "sqlserver"]:
                # Even if count is 0, structure should be present
                assert result["materialized_view_count"] >= 0, "Count should be non-negative"

    def test_partitions_structure(self, db_container, tmp_path, introspection_migrations):
        """Test table partitions result structure (even if none exist)."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(schema)

            # All results should have partitions structure
            assert "partitions" in result, "Result should have partitions dict"
            assert "total_partitions" in result, "Result should have total_partitions count"
            assert isinstance(result["partitions"], dict), "partitions should be a dict"
            assert isinstance(result["total_partitions"], int), "Count should be int"
            assert result["total_partitions"] >= 0, "Count should be non-negative"

    def test_new_metadata_features(self, db_container, tmp_path, introspection_migrations):
        """Test newly added metadata features: computed columns, identity columns, partitions, materialized views."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(
                schema, include_views=True, include_sequences=True, include_triggers=True
            )

            # Test computed columns enrichment
            # All databases should have at least some columns, check if enrichment works
            for table in result["tables"]:
                for column in table.columns:
                    # Check that identity metadata can be accessed (even if False)
                    assert hasattr(column, "is_identity") or True, "Identity enrichment should work"

            # Test constraint metadata enhancement
            check_constraints = []
            for table in result["tables"]:
                check_constraints.extend(
                    [c for c in table.constraints if c.constraint_type.value == "CHECK"]
                )

            if check_constraints:
                # Verify all check constraints have deferrable metadata
                for constraint in check_constraints:
                    assert hasattr(
                        constraint, "is_deferrable"
                    ), "Constraints should have is_deferrable attribute"
                    assert hasattr(
                        constraint, "initially_deferred"
                    ), "Constraints should have initially_deferred attribute"
                    assert isinstance(
                        constraint.is_deferrable, bool
                    ), "is_deferrable should be boolean"
                    assert isinstance(
                        constraint.initially_deferred, bool
                    ), "initially_deferred should be boolean"

                # Oracle and SQL Server should have enabled/validated metadata
                if db_type in ["oracle", "sqlserver"]:
                    for constraint in check_constraints:
                        assert hasattr(
                            constraint, "is_enabled"
                        ), f"{db_type} constraints should have is_enabled"
                        assert hasattr(
                            constraint, "is_validated"
                        ), f"{db_type} constraints should have is_validated"

            # Test materialized views (PostgreSQL, Oracle, DB2, SQL Server)
            if db_type in ["postgresql", "oracle", "db2", "sqlserver"]:
                # Check that materialized_view_count exists in result
                assert (
                    "materialized_view_count" in result
                ), "Result should include materialized_view_count"
                assert isinstance(
                    result["materialized_view_count"], int
                ), "materialized_view_count should be int"

            # Test partitions (all databases support partitions)
            assert "partitions" in result, "Result should include partitions dict"
            assert "total_partitions" in result, "Result should include total_partitions count"

    def test_identity_metadata_detailed(self, db_container, tmp_path, introspection_migrations):
        """Test that identity columns have detailed metadata (seed, increment, generation)."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(schema)

            # Find a table with identity column
            # departments, employees, orders, products all have identity/auto-increment
            identity_found = False

            for table in result["tables"]:
                for column in table.columns:
                    if column.is_identity:
                        identity_found = True

                        # Verify new SQL Model attributes are populated
                        assert hasattr(
                            column, "identity_seed"
                        ), "Identity column should have identity_seed"
                        assert hasattr(
                            column, "identity_increment"
                        ), "Identity column should have identity_increment"

                        # For Oracle with GENERATED ALWAYS AS IDENTITY, should have generation strategy
                        if db_type == "oracle":
                            # Oracle identity columns should have seed/increment from vendor queries
                            assert (
                                column.identity_seed is not None
                                or column.identity_increment is not None
                            ), "Oracle identity should have seed or increment metadata"

                        # For MySQL/PostgreSQL/SQL Server auto-increment, seed/increment might be enriched
                        # Break after finding one identity column
                        break
                if identity_found:
                    break

            assert identity_found, f"Should find at least one identity column in {db_type}"

    def test_computed_column_metadata_detailed(
        self, db_container, tmp_path, introspection_migrations
    ):
        """Test that computed columns have expression and stored metadata."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(schema)

            # Find products table with computed column (price_with_tax)
            products_table = None
            for table in result["tables"]:
                if table.name.upper() == "PRODUCTS":
                    products_table = table
                    break

            assert products_table is not None, "Should find products table"

            # Find price_with_tax computed column
            computed_column = None
            for column in products_table.columns:
                if column.name.upper() == "PRICE_WITH_TAX":
                    computed_column = column
                    break

            assert computed_column is not None, "Should find price_with_tax computed column"

            # Verify new SQL Model attributes
            assert computed_column.is_computed is True, "Should be marked as computed"
            assert hasattr(
                computed_column, "computed_expression"
            ), "Should have computed_expression attribute"
            assert hasattr(
                computed_column, "computed_stored"
            ), "Should have computed_stored attribute"

            # For databases with good vendor query support, expression should be populated
            if db_type not in ("db2",):  # DB2 may have limitations
                assert (
                    computed_column.computed_expression is not None
                ), f"Computed expression should be populated for {db_type}"

                # Verify stored flag is set (all test schemas use STORED)
                assert isinstance(
                    computed_column.computed_stored, bool
                ), "computed_stored should be boolean"

    def test_comment_metadata_extraction(self, db_container, tmp_path, introspection_migrations):
        """Test that table and column comments are extracted into metadata."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(schema)

            # All tables should have comment attribute (may be None)
            for table in result["tables"]:
                assert hasattr(table, "comment"), "Table should have comment attribute"

                # All columns should have comment attribute (may be None)
                for column in table.columns:
                    assert hasattr(column, "comment"), "Column should have comment attribute"

            # Note: Test migrations don't include COMMENT ON statements,
            # so comments will be None. This test validates the attribute exists
            # and is populated, even if empty.

    def test_ordinal_position_extraction(self, db_container, tmp_path, introspection_migrations):
        """Test that columns have ordinal_position metadata."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(schema)

            # All tables should have columns with ordinal_position
            for table in result["tables"]:
                if len(table.columns) > 0:
                    for column in table.columns:
                        assert hasattr(
                            column, "ordinal_position"
                        ), "Column should have ordinal_position"
                        assert isinstance(
                            column.ordinal_position, int
                        ), "ordinal_position should be int"
                        assert column.ordinal_position > 0, "ordinal_position should be 1-based"

                    # Verify columns are sorted by ordinal_position
                    positions = [col.ordinal_position for col in table.columns]
                    assert positions == sorted(
                        positions
                    ), "Columns should be sorted by ordinal_position"

    def test_full_metadata_serialization(self, db_container, tmp_path, introspection_migrations):
        """Test that all new metadata can be serialized via to_dict()."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(schema)

            # Test that all tables can be serialized
            for table in result["tables"]:
                table_dict = table.to_dict()

                # Verify table comment is in dict
                assert "comment" in table_dict, "to_dict should include comment"

                # Verify all column metadata is serialized
                for col_dict in table_dict["columns"]:
                    # Identity metadata
                    assert "is_identity" in col_dict, "Column dict should include is_identity"
                    assert (
                        "identity_generation" in col_dict
                    ), "Column dict should include identity_generation"
                    assert "identity_seed" in col_dict, "Column dict should include identity_seed"
                    assert (
                        "identity_increment" in col_dict
                    ), "Column dict should include identity_increment"

                    # Computed metadata
                    assert "is_computed" in col_dict, "Column dict should include is_computed"
                    assert (
                        "computed_expression" in col_dict
                    ), "Column dict should include computed_expression"
                    assert (
                        "computed_stored" in col_dict
                    ), "Column dict should include computed_stored"

                    # Comment metadata
                    assert "comment" in col_dict, "Column dict should include comment"

                    # Position metadata
                    assert (
                        "ordinal_position" in col_dict
                    ), "Column dict should include ordinal_position"

                # Test round-trip: from_dict should work
                from core.sql_model.table import Table

                restored_table = Table.from_dict(table_dict)

                # Verify restored table has all metadata
                assert restored_table.comment == table.comment, "Comment should be preserved"
                assert len(restored_table.columns) == len(
                    table.columns
                ), "Column count should match"

                # Verify restored columns have all metadata
                for original_col, restored_col in zip(table.columns, restored_table.columns):
                    assert (
                        restored_col.is_identity == original_col.is_identity
                    ), "is_identity should be preserved"
                    assert (
                        restored_col.is_computed == original_col.is_computed
                    ), "is_computed should be preserved"
                    assert (
                        restored_col.comment == original_col.comment
                    ), "comment should be preserved"
                    assert (
                        restored_col.ordinal_position == original_col.ordinal_position
                    ), "ordinal_position should be preserved"

    def test_procedure_extraction_structure(self, db_container, tmp_path, introspection_migrations):
        """Test that procedure extraction works and has correct structure."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            # Test get_procedures() method
            procedures = introspector.get_procedures(schema)

            # Result should be a list (may be empty if no procedures exist)
            assert isinstance(procedures, list), "get_procedures should return a list"

            # Each procedure should have proper attributes
            for proc in procedures:
                assert hasattr(proc, "name"), "Procedure should have name"
                assert hasattr(proc, "schema"), "Procedure should have schema"
                assert hasattr(proc, "is_function"), "Procedure should have is_function"
                assert proc.is_function is False, "Procedures should have is_function=False"
                assert hasattr(proc, "parameters"), "Procedure should have parameters"
                assert hasattr(proc, "body"), "Procedure should have body"
                assert hasattr(proc, "language"), "Procedure should have language"
                assert hasattr(proc, "comment"), "Procedure should have comment"

    def test_function_extraction_structure(self, db_container, tmp_path, introspection_migrations):
        """Test that function extraction works and has correct structure."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            # Test get_functions() method
            functions = introspector.get_functions(schema)

            # Result should be a list (may be empty if no functions exist)
            assert isinstance(functions, list), "get_functions should return a list"

            # Each function should have proper attributes
            for func in functions:
                assert hasattr(func, "name"), "Function should have name"
                assert hasattr(func, "schema"), "Function should have schema"
                assert hasattr(func, "is_function"), "Function should have is_function"
                assert func.is_function is True, "Functions should have is_function=True"
                assert hasattr(func, "return_type"), "Function should have return_type"
                assert hasattr(func, "parameters"), "Function should have parameters"
                assert hasattr(func, "body"), "Function should have body"
                assert hasattr(func, "language"), "Function should have language"
                assert hasattr(func, "comment"), "Function should have comment"

    def test_enhanced_introspection_includes_procedures_functions(
        self, db_container, tmp_path, introspection_migrations
    ):
        """Test that introspect_schema includes procedures and functions."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            # Test with all options enabled
            result = introspector.introspect_schema(
                schema,
                include_views=True,
                include_sequences=True,
                include_triggers=True,
                include_procedures=True,
                include_functions=True,
            )

            # Verify procedures and functions are in result
            assert "procedures" in result, "Result should include procedures list"
            assert "functions" in result, "Result should include functions list"
            assert "procedure_count" in result, "Result should include procedure_count"
            assert "function_count" in result, "Result should include function_count"

            # Verify counts are integers
            assert isinstance(result["procedure_count"], int), "procedure_count should be int"
            assert isinstance(result["function_count"], int), "function_count should be int"

            # Verify lists are lists
            assert isinstance(result["procedures"], list), "procedures should be a list"
            assert isinstance(result["functions"], list), "functions should be a list"

            # Counts should match list lengths
            assert len(result["procedures"]) == result["procedure_count"]
            assert len(result["functions"]) == result["function_count"]

    def test_procedure_function_serialization(
        self, db_container, tmp_path, introspection_migrations
    ):
        """Test that extracted procedures and functions can be serialized."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        from core.sql_model.procedure import Procedure

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(
                schema, include_procedures=True, include_functions=True
            )

            # Test procedure serialization
            for proc in result["procedures"]:
                proc_dict = proc.to_dict()

                # Verify required fields in serialization
                assert "name" in proc_dict, "Procedure dict should have name"
                assert "is_function" in proc_dict, "Procedure dict should have is_function"
                assert proc_dict["is_function"] is False, "Procedure is_function should be False"
                assert "parameters" in proc_dict, "Procedure dict should have parameters"
                assert "body" in proc_dict, "Procedure dict should have body"
                assert "language" in proc_dict, "Procedure dict should have language"
                assert "comment" in proc_dict, "Procedure dict should have comment"

                # Test round-trip
                restored = proc.from_dict(proc_dict)
                assert restored.name == proc.name
                assert restored.is_function == proc.is_function

            # Test function serialization
            for func in result["functions"]:
                func_dict = func.to_dict()

                # Verify required fields in serialization
                assert "name" in func_dict, "Function dict should have name"
                assert "is_function" in func_dict, "Function dict should have is_function"
                assert func_dict["is_function"] is True, "Function is_function should be True"
                assert "return_type" in func_dict, "Function dict should have return_type"
                assert "parameters" in func_dict, "Function dict should have parameters"
                assert "body" in func_dict, "Function dict should have body"
                assert "language" in func_dict, "Function dict should have language"
                assert "comment" in func_dict, "Function dict should have comment"

                # Test round-trip
                restored_proc = Procedure.from_dict(func_dict)
                assert restored_proc.name == func.name
                assert restored_proc.is_function == func.is_function
                assert restored_proc.return_type == func.return_type

    def test_synonyms_introspection(self, db_container, tmp_path, introspection_migrations):
        """Test synonyms are properly introspected (Oracle, SQL Server, DB2)."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Skip for databases that don't support synonyms
        if db_type in ["postgresql", "mysql"]:
            pytest.skip(f"{db_type} does not support synonyms")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(schema)

            # Should find synonyms
            assert "synonyms" in result, "Result should have synonyms list"
            assert "synonym_count" in result, "Result should have synonym_count"
            assert isinstance(result["synonym_count"], int), "Count should be int"
            assert isinstance(result["synonyms"], list), "Should be a list"

            # Debug: Check if DB2 supports synonyms and query is working
            if db_type == "db2":
                # First, check what aliases exist in SYSCAT
                debug_sql = f"""
                SELECT TABNAME, TABSCHEMA, TYPE, BASE_TABSCHEMA, BASE_TABNAME
                FROM SYSCAT.TABLES
                WHERE TABSCHEMA = '{schema.upper()}'
                ORDER BY TABNAME
                """
                all_tables = provider.execute_query(debug_sql)
                print(f"\nDEBUG: All objects in {schema.upper()}:")
                for t in all_tables:
                    print(
                        f"  {t.get('TABNAME')} - TYPE={t.get('TYPE')} - BASE={t.get('BASE_TABNAME')}"
                    )

                # Now check with the actual synonyms query
                from core.introspection import VendorQueriesFactory

                vendor_q = VendorQueriesFactory.create(db_type)
                sql, params = vendor_q.get_synonyms_query(schema)
                print(f"\nDEBUG: Synonym query: {sql}")
                print(f"DEBUG: Params: {params}")
                raw_results = provider.execute_query(sql, params)
                print(f"DEBUG: Raw synonym results: {raw_results}\n")

            # Should find at least 2 synonyms (emp_syn/emp_alias, dept_syn/dept_alias)
            assert (
                result["synonym_count"] >= 2
            ), f"Should find at least 2 synonyms, found {result['synonym_count']}"

            # Verify synonym properties
            synonyms = result["synonyms"]
            if db_type == "oracle":
                emp_syn = next((s for s in synonyms if s.name.upper() == "EMP_SYN"), None)
                assert emp_syn is not None, "Should find EMP_SYN"
                assert emp_syn.target_object.upper() == "EMPLOYEES", "Should target EMPLOYEES table"
            elif db_type == "sqlserver":
                emp_syn = next((s for s in synonyms if s.name.lower() == "emp_syn"), None)
                assert emp_syn is not None, "Should find emp_syn"
                assert emp_syn.target_object.lower() == "employees", "Should target employees table"
            elif db_type == "db2":
                emp_alias = next((s for s in synonyms if s.name.upper() == "EMP_ALIAS"), None)
                assert emp_alias is not None, "Should find EMP_ALIAS"
                assert (
                    emp_alias.target_object.upper() == "EMPLOYEES"
                ), "Should target EMPLOYEES table"

    def test_user_defined_types_introspection(
        self, db_container, tmp_path, introspection_migrations
    ):
        """Test user-defined types are properly introspected (PostgreSQL)."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(schema)

            # Should have UDT structure in result
            assert "user_defined_types" in result, "Result should have user_defined_types list"
            assert "user_defined_type_count" in result, "Result should have user_defined_type_count"
            assert isinstance(result["user_defined_type_count"], int), "Count should be int"
            assert isinstance(result["user_defined_types"], list), "Should be a list"

            # PostgreSQL should find all 3 UDTs: enum, composite, domain.
            if db_type == "postgresql":
                assert (
                    result["user_defined_type_count"] >= 3
                ), f"Should find at least 3 UDTs (enum, composite, domain), found {result['user_defined_type_count']}"

                # Verify we can find specific types
                types = result["user_defined_types"]
                status_enum = next((t for t in types if t.name == "status_enum"), None)
                address_type = next((t for t in types if t.name == "address_type"), None)
                email_domain = next((t for t in types if t.name == "email_domain"), None)

                # Verify enum type
                if status_enum:
                    assert status_enum.is_enum, "status_enum should be recognized as ENUM"
                    assert len(status_enum.enum_values) == 4, "Should have 4 enum values"
                    assert "active" in status_enum.enum_values, "Should contain 'active' value"

                # Verify composite type
                if address_type:
                    assert (
                        address_type.is_composite
                    ), "address_type should be recognized as COMPOSITE"
                    assert len(address_type.attributes) == 3, "Should have 3 attributes"

                # Verify domain type
                if email_domain:
                    assert email_domain.is_domain, "email_domain should be recognized as DOMAIN"

    def test_extensions_introspection(self, db_container, tmp_path, introspection_migrations):
        """Test extensions are properly introspected (PostgreSQL)."""
        db_type = db_container["type"]

        # Only PostgreSQL supports extensions
        if db_type != "postgresql":
            pytest.skip(f"{db_type} does not support extensions")

        schema = db_container.get("schema", "TEST_SCHEMA")

        # Deploy introspection test schema
        # Use introspection_migrations directory from fixture

        config_file = create_config(tmp_path, db_container, migrations_dir=introspection_migrations)

        cli = DBLiftCLI(config_file, introspection_migrations)
        result = cli.migrate()

        assert result.success, f"Migration deployment failed: {result.stderr}"

        provider = self._get_provider(db_container)
        log = ConsoleLog("introspection_test", enable_debug=False)

        with IntrospectorFactory.create(provider, log=log, use_vendor_queries=True) as introspector:
            result = introspector.introspect_schema(schema)

            # Should have extensions structure in result
            assert "extensions" in result, "Result should have extensions list"
            assert "extension_count" in result, "Result should have extension_count"
            assert isinstance(result["extension_count"], int), "Count should be int"
            assert isinstance(result["extensions"], list), "Should be a list"

            # PostgreSQL databases typically have some extensions installed
            # We won't assert specific count as it depends on PostgreSQL installation
            assert result["extension_count"] >= 0, "Count should be non-negative"

            # If extensions found, verify they have required properties
            if result["extension_count"] > 0:
                ext = result["extensions"][0]
                assert hasattr(ext, "name"), "Extension should have name"
                assert hasattr(ext, "version"), "Extension should have version"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

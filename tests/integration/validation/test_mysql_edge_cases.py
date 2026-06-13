"""
MySQL Edge Cases Tests.

Tests for MySQL edge cases: reserved keywords, unicode identifiers, long identifiers, etc.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["mysql"],
    indirect=True,
)
class TestMySQLEdgeCases:
    """MySQL edge cases tests."""

    def test_reserved_keyword_identifiers(self, db_container):
        """Test tables and columns with reserved keywords as identifiers."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        db_config = DatabaseConfig(
            type="mysql",
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "TEST_SCHEMA"),
            extra_params={
                "useSSL": "false",
                "allowPublicKeyRetrieval": "true",
            },
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("mysql_reserved", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`table`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with reserved keyword as name
            create_table = f"""
            CREATE TABLE `{schema}`.`table` (
                `select` INT PRIMARY KEY,
                `from` VARCHAR(50) NOT NULL,
                `where` INT
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "table":
                    test_table = table
                    break

            assert test_table is not None, "Table 'table' not found"
            # Check that reserved keyword columns are found
            column_names = [col.name.lower() for col in test_table.columns]
            assert "select" in column_names, f"Column 'select' not found in {column_names}"
            assert "from" in column_names, f"Column 'from' not found in {column_names}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`table`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_unicode_identifiers(self, db_container):
        """Test tables and columns with unicode identifiers."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        db_config = DatabaseConfig(
            type="mysql",
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "TEST_SCHEMA"),
            extra_params={
                "useSSL": "false",
                "allowPublicKeyRetrieval": "true",
            },
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("mysql_unicode", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`utilisateur`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with unicode identifiers
            create_table = f"""
            CREATE TABLE `{schema}`.`utilisateur` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                `nom` VARCHAR(100) NOT NULL,
                `prénom` VARCHAR(100)
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "utilisateur":
                    test_table = table
                    break

            assert test_table is not None, "Table 'utilisateur' not found"
            # Check that unicode columns are found
            column_names = [col.name.lower() for col in test_table.columns]
            assert "nom" in column_names, f"Column 'nom' not found in {column_names}"
            assert "prénom" in column_names or "prénom" in [
                col.name for col in test_table.columns
            ], f"Column 'prénom' not found in {[col.name for col in test_table.columns]}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`utilisateur`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_self_referencing_foreign_key(self, db_container):
        """Test self-referencing foreign key relationships."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        db_config = DatabaseConfig(
            type="mysql",
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "TEST_SCHEMA"),
            extra_params={
                "useSSL": "false",
                "allowPublicKeyRetrieval": "true",
            },
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("mysql_self_ref", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`employees`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with self-referencing foreign key
            create_table = f"""
            CREATE TABLE `{schema}`.`employees` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                manager_id INT,
                CONSTRAINT fk_employee_manager FOREIGN KEY (manager_id) REFERENCES `{schema}`.`employees`(id)
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "employees":
                    test_table = table
                    break

            assert test_table is not None, "Table 'employees' not found"
            # Check that self-referencing foreign key is found
            fk_constraints = [
                c for c in test_table.constraints if c.constraint_type.value == "FOREIGN KEY"
            ]
            assert (
                len(fk_constraints) >= 1
            ), f"Expected at least 1 foreign key, found {len(fk_constraints)}"

            # Check that it references the same table
            self_ref_fk = None
            for fk in fk_constraints:
                if hasattr(fk, "reference_table") and fk.reference_table.lower() == "employees":
                    self_ref_fk = fk
                    break
            assert self_ref_fk is not None, "Self-referencing foreign key not found"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`employees`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

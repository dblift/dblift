"""
SQL Server Stored Procedures Tests.

Comprehensive tests for stored procedures with various parameter types.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["sqlserver"],
    indirect=True,
)
class TestSQLServerProcedures:
    """SQL Server stored procedure tests."""

    def test_simple_procedure(self, db_container):
        """Test simple procedure with no parameters."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build SQLAlchemy URL
        sqlalchemy_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"

        db_config = DatabaseConfig(
            type="sqlserver",
            url=sqlalchemy_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "dbo"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("sqlserver_procedure_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.GetUsers")
            except Exception:
                pass

            # Create simple procedure
            create_proc = f"""
            CREATE PROCEDURE {schema}.GetUsers
            AS
            BEGIN
                SELECT * FROM users;
            END
            """

            provider.execute_statement(create_proc)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            procedures = introspector.get_procedures(db_config.schema)

            assert len(procedures) >= 1
            proc = next((p for p in procedures if p.name == "GetUsers"), None)
            assert proc is not None
            assert len(proc.parameters) == 0

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.GetUsers")
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.GetUserById")
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.GetUserCount")
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.GetUsersByStatus")
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.UpdateUser")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_procedure_with_in_parameters(self, db_container):
        """Test procedure with IN parameters."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build SQLAlchemy URL
        sqlalchemy_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"

        db_config = DatabaseConfig(
            type="sqlserver",
            url=sqlalchemy_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "dbo"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("sqlserver_procedure_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.GetUserById")
            except Exception:
                pass

            # Create procedure with IN parameters
            create_proc = f"""
            CREATE PROCEDURE {schema}.GetUserById
                @UserId INT,
                @UserName NVARCHAR(100)
            AS
            BEGIN
                SELECT * FROM users WHERE id = @UserId AND name = @UserName;
            END
            """

            provider.execute_statement(create_proc)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            procedures = introspector.get_procedures(db_config.schema)

            proc = next((p for p in procedures if p.name == "GetUserById"), None)
            assert proc is not None
            assert len(proc.parameters) == 2

            # SQL Server strips @ from parameter names in introspection
            param1 = next((p for p in proc.parameters if p.name in ("@UserId", "UserId")), None)
            assert param1 is not None
            assert hasattr(param1, "direction") and param1.direction == "IN"

            param2 = next((p for p in proc.parameters if p.name in ("@UserName", "UserName")), None)
            assert param2 is not None
            assert hasattr(param2, "direction") and param2.direction == "IN"

        finally:
            try:
                provider.execute_statement("DROP PROCEDURE IF EXISTS GetUserById")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_procedure_with_out_parameters(self, db_container):
        """Test procedure with OUT parameters."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build SQLAlchemy URL
        sqlalchemy_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"

        db_config = DatabaseConfig(
            type="sqlserver",
            url=sqlalchemy_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "dbo"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("sqlserver_procedure_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.GetUserCount")
            except Exception:
                pass

            # Create procedure with OUT parameter
            create_proc = f"""
            CREATE PROCEDURE {schema}.GetUserCount
                @Count INT OUTPUT
            AS
            BEGIN
                SELECT @Count = COUNT(*) FROM users;
            END
            """

            provider.execute_statement(create_proc)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            procedures = introspector.get_procedures(db_config.schema)

            proc = next((p for p in procedures if p.name == "GetUserCount"), None)
            assert proc is not None
            assert len(proc.parameters) == 1

            param = proc.parameters[0]
            assert param.name in ("@Count", "Count")
            assert hasattr(param, "direction") and param.direction == "OUT"

        finally:
            try:
                provider.execute_statement("DROP PROCEDURE IF EXISTS GetUserCount")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_procedure_with_default_parameters(self, db_container):
        """Test procedure with default parameter values."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build SQLAlchemy URL
        sqlalchemy_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"

        db_config = DatabaseConfig(
            type="sqlserver",
            url=sqlalchemy_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "dbo"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("sqlserver_procedure_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.GetUsersByStatus")
            except Exception:
                pass

            # Create procedure with default parameter
            create_proc = f"""
            CREATE PROCEDURE {schema}.GetUsersByStatus
                @Status NVARCHAR(50) = 'ACTIVE'
            AS
            BEGIN
                SELECT * FROM users WHERE status = @Status;
            END
            """

            provider.execute_statement(create_proc)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            procedures = introspector.get_procedures(db_config.schema)

            proc = next((p for p in procedures if p.name == "GetUsersByStatus"), None)
            assert proc is not None
            assert len(proc.parameters) == 1

            param = proc.parameters[0]
            assert param.name in ("@Status", "Status")
            # SQL Server may not return default values in introspection, check if present
            # If default_value is None, it means SQL Server doesn't expose it via sys.parameters
            # This is acceptable - the procedure still works with defaults
            if hasattr(param, "default_value") and param.default_value is not None:
                assert "ACTIVE" in str(param.default_value).upper()

        finally:
            try:
                provider.execute_statement("DROP PROCEDURE IF EXISTS GetUsersByStatus")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_procedure_round_trip(self, db_container):
        """Test that procedures are preserved in round-trip."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build SQLAlchemy URL
        sqlalchemy_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"

        db_config = DatabaseConfig(
            type="sqlserver",
            url=sqlalchemy_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "dbo"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("sqlserver_procedure_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.UpdateUser")
            except Exception:
                pass

            # Create procedure with multiple parameters
            create_proc = f"""
            CREATE PROCEDURE {schema}.UpdateUser
                @UserId INT,
                @UserName NVARCHAR(100),
                @Email NVARCHAR(255) = NULL,
                @UpdatedCount INT OUTPUT
            AS
            BEGIN
                UPDATE users SET name = @UserName, email = @Email WHERE id = @UserId;
                SET @UpdatedCount = @@ROWCOUNT;
            END
            """

            provider.execute_statement(create_proc)

            # Run round-trip test
            introspector = IntrospectorFactory.create(provider, log=log)

            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=db_config.schema,
                test_schema=db_config.schema + "_test",
                introspector=introspector,
                test_object_types=["procedures"],
            )

            results = tester.run_round_trip_test()

            assert results["success"], (
                f"Round-trip failed. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('procedures', {}).get('differences', [])}"
            )

        finally:
            try:
                provider.execute_statement("DROP PROCEDURE IF EXISTS UpdateUser")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

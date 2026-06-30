"""Shared fixtures for integration tests."""

import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict

import docker
import pytest

from config import DbliftConfig
from core.logger import DbliftLogger, LogFormat, LogLevel

# Container-readiness helpers extracted in PR-B6. Re-exported here so
# every test that imports from ``tests.integration.conftest`` keeps
# working through the conftest namespace, and so the OS/architecture
# detection vars stay accessible to the fixture bodies below.
from tests.integration._container_readiness import (  # noqa: F401  re-export
    IS_ARM_ARCHITECTURE,
    IS_MACOS,
    MYSQL_DOCKER_COMMAND,
    USING_COLIMA,
    _apply_mysql_docker_run_options,
    is_using_colima,
    wait_for_readiness,
)

# Limit to SQL Server only for focused integration testing
SUPPORTED_DBS = ["sqlserver", "mysql", "postgresql", "oracle", "cosmosdb", "sqlite"]

# Check if we should limit to a specific database for core tests
DBLIFT_CORE_TEST_DB = os.environ.get("DBLIFT_CORE_TEST_DB")
if DBLIFT_CORE_TEST_DB:
    # Limit to only the specified database for core integration tests
    SUPPORTED_DBS = [DBLIFT_CORE_TEST_DB]
    print(f"Limited core tests to database: {DBLIFT_CORE_TEST_DB}")


# External MySQL configuration (useful when containers are not available)
EXTERNAL_MYSQL_HOST = os.environ.get("DBLIFT_MYSQL_HOST")
EXTERNAL_MYSQL_PORT = os.environ.get("DBLIFT_MYSQL_PORT")
EXTERNAL_MYSQL_USERNAME = os.environ.get("DBLIFT_MYSQL_USERNAME")
EXTERNAL_MYSQL_PASSWORD = os.environ.get("DBLIFT_MYSQL_PASSWORD") or os.environ.get(
    "MYSQL_ROOT_PASSWORD"
)
EXTERNAL_MYSQL_DATABASE = os.environ.get("DBLIFT_MYSQL_DATABASE")

# External DB2 configuration
EXTERNAL_DB2_HOST = os.environ.get("DBLIFT_DB2_HOST")
EXTERNAL_DB2_PORT = os.environ.get("DBLIFT_DB2_PORT")
EXTERNAL_DB2_USERNAME = os.environ.get("DBLIFT_DB2_USERNAME")
EXTERNAL_DB2_PASSWORD = os.environ.get("DBLIFT_DB2_PASSWORD") or os.environ.get("DB2_PASSWORD")
EXTERNAL_DB2_DATABASE = os.environ.get("DBLIFT_DB2_DATABASE")
EXTERNAL_DB2_SCHEMA = os.environ.get("DBLIFT_DB2_SCHEMA")

# External CosmosDB configuration
EXTERNAL_COSMOSDB_ENDPOINT = os.environ.get("DBLIFT_COSMOSDB_ENDPOINT")
EXTERNAL_COSMOSDB_KEY = os.environ.get("DBLIFT_COSMOSDB_KEY")
EXTERNAL_COSMOSDB_DATABASE = os.environ.get("DBLIFT_COSMOSDB_DATABASE")
EXTERNAL_COSMOSDB_CONTAINER = os.environ.get("DBLIFT_COSMOSDB_CONTAINER")


def _apply_mysql_port_override(configs: Dict[str, Dict[str, Any]], port_value: str | None) -> None:
    """Apply the MySQL host-port override used by docker-compose.override.yml."""
    if not port_value:
        return

    try:
        configs["mysql"]["port"] = int(port_value)
    except ValueError:
        print(f"[WARN] Invalid DBLIFT_MYSQL_PORT value '{port_value}', using default 3306")


def _ensure_schema_before_cleanup(provider: Any, db_type: str | None, schema: str | None) -> None:
    """Ensure schema-scoped integration databases have their test schema."""
    if db_type not in {"postgresql", "sqlserver"} or not schema:
        return

    provider.create_schema_if_not_exists(schema)
    provider.commit_transaction()


def _test_schema_for_service(service: str, config: Dict[str, Any]) -> str:
    """Return the integration-test schema/catalog for a database service."""
    if service == "mysql":
        return str(config.get("database", "testdb"))
    return "TEST_SCHEMA"


def _published_host_port(container: Any, container_port: str) -> int | None:
    """Return the host port Docker published for a container port."""
    ports = container.attrs.get("NetworkSettings", {}).get("Ports", {})
    bindings = ports.get(container_port) or []
    if not bindings:
        return None
    host_port = bindings[0].get("HostPort")
    return int(host_port) if host_port else None


# Configure MySQL and DB2 support based on environment
# Only add additional databases if DBLIFT_CORE_TEST_DB is not set
if not DBLIFT_CORE_TEST_DB:
    if IS_MACOS:
        # On macOS, MySQL needs special handling for Colima
        if USING_COLIMA and IS_ARM_ARCHITECTURE:
            # Add MySQL with platform override for ARM architecture with Colima
            SUPPORTED_DBS.append("mysql")
            print("Added MySQL support with ARM-specific configuration for Colima")
        else:
            print("MySQL tests on macOS require Colima with ARM configuration")

        # DB2 is not supported on macOS with containers, but allow external instances
        if EXTERNAL_DB2_HOST:
            SUPPORTED_DBS.append("db2")
            print("Added DB2 support for macOS (external instance)")
        else:
            print("WARNING: DB2 tests are disabled on macOS due to known container issues")
    else:
        # On Linux/Windows, add MySQL normally
        SUPPORTED_DBS.append("mysql")

        # DB2 is only supported on Linux (or with external instance)
        if platform.system().lower() == "linux" or EXTERNAL_DB2_HOST:
            SUPPORTED_DBS.append("db2")
            print(
                "Added DB2 support for Linux"
                + (" (external instance)" if EXTERNAL_DB2_HOST else "")
            )

# Fixed container names for each service
db_container_names = {
    "oracle": "dblift_oracle",
    "postgresql": "dblift_postgres",
    "mysql": "dblift_mysql",
    "sqlserver": "dblift_sqlserver",
    "db2": "dblift_db2",
    "cosmosdb": "dblift_cosmosdb",
}

# DEAD CODE: service_map is never referenced — db_container_names (above) is the
# authoritative container-name mapping used by all fixtures.  Kept for reference
# but DB2 and CosmosDB were never added here, confirming it drifted from the
# actual mapping.  See story 23-6 AC#6 analysis.
# service_map = {
#     k: v
#     for k, v in {
#         "oracle": "dblift_oracle",
#         "postgresql": "dblift_postgres",
#         "mysql": "dblift_mysql",
#         "sqlserver": "dblift_sqlserver",
#         # "db2": "dblift_db2",
#     }.items()
#     if k in SUPPORTED_DBS
# }

image_map = {
    k: v
    for k, v in {
        "oracle": "gvenzl/oracle-xe:latest",
        "postgresql": "postgres:15",
        "mysql": "mysql:8.0",
        "sqlserver": "mcr.microsoft.com/mssql/server:2022-latest",
        # Keep in sync with tests/integration/docker-compose.yml (CI uses compose)
        "db2": "icr.io/db2_community/db2:latest",
        "cosmosdb": "mcr.microsoft.com/cosmosdb/linux/azure-cosmos-emulator:vnext-preview",
    }.items()
    if k in SUPPORTED_DBS
}

env_map = {
    k: v
    for k, v in {
        "oracle": ["ORACLE_PASSWORD=oracle"],
        "postgresql": [
            "POSTGRES_USER=postgres",
            "POSTGRES_PASSWORD=postgres",
            "POSTGRES_DB=testdb",
        ],
        "mysql": [
            "MYSQL_ROOT_PASSWORD=root",
            "MYSQL_DATABASE=testdb",
            # Allow root connections from any host (host network -> container)
            "MYSQL_ROOT_HOST=%",
        ],
        "sqlserver": ["ACCEPT_EULA=Y", "SA_PASSWORD=YourStrong@Passw0rd"],
        "db2": [
            "LICENSE=accept",
            "DB2INSTANCE=db2inst1",
            "DB2INST1_PASSWORD=db2admin",
            "DBNAME=testdb",
            "BLU=false",
            "ENABLE_ORACLE_COMPATIBILITY=false",
        ],
        "cosmosdb": [
            "AZURE_COSMOS_EMULATOR_PARTITION_COUNT=10",
            "AZURE_COSMOS_EMULATOR_ENABLE_DATA_PERSISTENCE=true",
        ],
    }.items()
    if k in SUPPORTED_DBS
}

port_map = {
    k: v
    for k, v in {
        "oracle": {"1521/tcp": 1521},
        "postgresql": {"5432/tcp": 5432},
        "mysql": {"3306/tcp": 3306},
        "sqlserver": {"1433/tcp": 1433},
        "db2": {"50000/tcp": 50000},
        "cosmosdb": {
            "8081/tcp": 8081,  # CosmosDB Emulator HTTPS endpoint
            "10251/tcp": 10251,  # CosmosDB Emulator data port
            "10252/tcp": 10252,  # CosmosDB Emulator data port
            "10253/tcp": 10253,  # CosmosDB Emulator data port
            "10254/tcp": 10254,  # CosmosDB Emulator data port
        },
    }.items()
    if k in SUPPORTED_DBS
}


@pytest.fixture(scope="session")
def docker_client():
    """Create a Docker client."""
    client = docker.from_env()
    yield client
    # Clean up Docker client on session end
    try:
        client.close()
    except Exception as e:
        print(f"Warning: Failed to close Docker client: {str(e)}")


# DEAD FIXTURE: db_containers is not referenced by any integration test (story 23-6 H3).
# Mentioned only in README.md. All container management is done via individual fixtures
# (db_container, sqlserver_container, etc.) which handle lazy startup themselves.
@pytest.fixture(scope="session")
def db_containers(docker_client, request):
    """Start and manage all required database containers for the session."""
    all_services = SUPPORTED_DBS
    services = getattr(request, "param", all_services)

    # Skip DB2 on MacOS
    if IS_MACOS and "db2" in services:
        print("Skipping DB2 container on MacOS")
        services = [s for s in services if s != "db2"]

    for service in services:
        container_name = db_container_names[service]
        try:
            container = docker_client.containers.get(container_name)
            if container.status != "running":
                container.start()
                print(f"Started existing container {container_name}")
        except docker.errors.NotFound:
            print(f"Creating and starting new container {container_name}")
            # Configure container run options
            run_kwargs = dict(
                image=image_map[service],
                name=container_name,
                environment=env_map[service],
                ports=port_map[service],
                detach=True,
            )

            # Special handling for DB2 container
            if service == "db2" and not IS_MACOS:
                run_kwargs.update(
                    {"platform": "linux/amd64", "privileged": True}
                )  # Required for DB2

            # Special handling for MySQL on macOS with ARM architecture (M1/M2/M3)
            if service == "mysql":
                _apply_mysql_docker_run_options(run_kwargs)
            print(f"[DEBUG] Docker run arguments for {service}: {run_kwargs}")
            container = docker_client.containers.run(**run_kwargs)
        wait_for_readiness(service, container)
    yield
    # Do not remove containers after tests (leave running for reuse)


@pytest.fixture(scope="session")
def db_configs() -> Dict[str, Dict[str, Any]]:
    """Get database configurations for test containers."""
    configs = {
        "oracle": {
            "type": "oracle",
            "host": "localhost",
            "port": 1521,
            "database": "XE",  # Keep this for backward compatibility
            "service": "XEPDB1",  # Add service field for XEPDB1 (Pluggable Database)
            "username": "system",
            "password": "oracle",
        },
        "postgresql": {
            "type": "postgresql",
            "host": "localhost",
            "port": 5432,
            "database": "testdb",
            "username": "postgres",
            "password": "postgres",
        },
        "mysql": {
            "type": "mysql",
            "host": "localhost",
            "port": 3306,
            "database": "testdb",
            "username": "root",
            "password": "root",
        },
        "sqlserver": {
            "type": "sqlserver",
            "host": "localhost",
            "port": 1433,
            "database": "master",
            "username": "sa",
            "password": "YourStrong@Passw0rd",
            "encrypt": False,
            "trust_server_certificate": True,
        },
        "db2": {
            "type": "db2",
            "host": "localhost",
            "port": 50000,
            # Must match tests/integration/docker-compose.yml DBNAME + healthcheck `db2 connect to testdb`
            "database": "testdb",
            "username": "db2inst1",
            "password": "db2admin",
        },
        "cosmosdb": {
            "type": "cosmosdb",
            "account_endpoint": "http://localhost:8081/",  # CosmosDB Emulator default (HTTP only in Docker)
            "account_key": "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw==",  # CosmosDB Emulator default key
            "database_name": "testdb",
            "container_name": "test_container",
            "use_managed_identity": False,
        },
    }

    _apply_mysql_port_override(configs, EXTERNAL_MYSQL_PORT)

    if EXTERNAL_MYSQL_HOST:
        mysql_config = configs["mysql"]
        mysql_config["host"] = EXTERNAL_MYSQL_HOST
        if EXTERNAL_MYSQL_DATABASE:
            mysql_config["database"] = EXTERNAL_MYSQL_DATABASE
        else:
            # Use a sensible default schema name for migrations
            mysql_config["database"] = "mysql"
        if EXTERNAL_MYSQL_USERNAME:
            mysql_config["username"] = EXTERNAL_MYSQL_USERNAME
        if EXTERNAL_MYSQL_PASSWORD:
            mysql_config["password"] = EXTERNAL_MYSQL_PASSWORD
        # Add MySQL driver parameters for remote connections
        if "extra_params" not in mysql_config:
            mysql_config["extra_params"] = {}
        mysql_config["extra_params"]["useSSL"] = "false"
        mysql_config["extra_params"]["allowPublicKeyRetrieval"] = "true"
        print(
            "[INFO] Using external MySQL configuration: "
            f"{mysql_config['host']}:{mysql_config['port']} "
            f"(database={mysql_config['database']}, user={mysql_config['username']})"
        )

    if EXTERNAL_DB2_HOST:
        db2_config = configs["db2"]
        db2_config["host"] = EXTERNAL_DB2_HOST
        if EXTERNAL_DB2_PORT:
            try:
                db2_config["port"] = int(EXTERNAL_DB2_PORT)
            except ValueError:
                print(
                    f"[WARN] Invalid DBLIFT_DB2_PORT value '{EXTERNAL_DB2_PORT}', using default 50000"
                )
        if EXTERNAL_DB2_DATABASE:
            db2_config["database"] = EXTERNAL_DB2_DATABASE
        if EXTERNAL_DB2_USERNAME:
            db2_config["username"] = EXTERNAL_DB2_USERNAME
        if EXTERNAL_DB2_PASSWORD:
            db2_config["password"] = EXTERNAL_DB2_PASSWORD
        if EXTERNAL_DB2_SCHEMA:
            db2_config["schema"] = EXTERNAL_DB2_SCHEMA
        print(
            "[INFO] Using external DB2 configuration: "
            f"{db2_config['host']}:{db2_config['port']} "
            f"(database={db2_config['database']}, user={db2_config['username']})"
        )

    if EXTERNAL_COSMOSDB_ENDPOINT:
        cosmosdb_config = configs["cosmosdb"]
        cosmosdb_config["account_endpoint"] = EXTERNAL_COSMOSDB_ENDPOINT
        if EXTERNAL_COSMOSDB_KEY:
            cosmosdb_config["account_key"] = EXTERNAL_COSMOSDB_KEY
        if EXTERNAL_COSMOSDB_DATABASE:
            cosmosdb_config["database_name"] = EXTERNAL_COSMOSDB_DATABASE
        if EXTERNAL_COSMOSDB_CONTAINER:
            cosmosdb_config["container_name"] = EXTERNAL_COSMOSDB_CONTAINER
        print(
            "[INFO] Using external CosmosDB configuration: "
            f"{cosmosdb_config['account_endpoint']} "
            f"(database={cosmosdb_config['database_name']})"
        )

    return configs


@pytest.fixture
def db_container(docker_client, request, db_configs):
    """Start and yield a single database container for the test, using the fixed name and schema."""
    service = request.param  # e.g., 'sqlserver', 'oracle', etc.

    # Early skip if -k filter is used and this database doesn't match
    # This prevents unnecessary container startup during collection
    try:
        config = request.config
        keyword_expr = config.getoption("-k", default=None)
        if keyword_expr:
            # Check if keyword expression contains database names
            db_keywords = ["postgresql", "mysql", "sqlserver", "oracle", "db2", "cosmosdb"]
            matched_dbs = [db for db in db_keywords if db in keyword_expr.lower()]
            if matched_dbs:
                # Check if this service matches any of the matched databases
                service_lower = service.lower()
                if not any(matched_db in service_lower for matched_db in matched_dbs):
                    pytest.skip(f"Database '{service}' filtered out by -k '{keyword_expr}'")
    except Exception:
        pass  # If we can't check, continue normally

    # Skip tests for databases not in SUPPORTED_DBS
    if service not in SUPPORTED_DBS:
        pytest.skip(f"{service} tests are not enabled (not in SUPPORTED_DBS: {SUPPORTED_DBS})")

    # Skip DB2 tests on MacOS
    if IS_MACOS and service == "db2" and not EXTERNAL_DB2_HOST:
        pytest.skip("DB2 tests are not supported on MacOS")

    if service == "mysql" and EXTERNAL_MYSQL_HOST:
        print(
            f"Skipping MySQL container startup; using external instance at "
            f"{EXTERNAL_MYSQL_HOST}:{db_configs['mysql']['port']}"
        )
        config = db_configs["mysql"].copy()
        config["schema"] = _test_schema_for_service(service, config)
        yield config
        return

    if service == "db2" and EXTERNAL_DB2_HOST:
        print(
            f"Skipping DB2 container startup; using external instance at "
            f"{EXTERNAL_DB2_HOST}:{db_configs['db2']['port']}"
        )
        config = db_configs["db2"].copy()
        config["schema"] = EXTERNAL_DB2_SCHEMA if EXTERNAL_DB2_SCHEMA else "DB2INST1"
        yield config
        return

    container_name = db_container_names[service]
    try:
        container = docker_client.containers.get(container_name)
        if container.status != "running":
            container.start()
            print(f"Started existing container {container_name}")
    except docker.errors.NotFound:
        print(f"Creating and starting new container {container_name}")
        # Configure container run options
        run_kwargs = dict(
            image=image_map[service],
            name=container_name,
            environment=env_map[service],
            ports=port_map[service],
            detach=True,
        )

        # Special handling for DB2 container
        if service == "db2" and not IS_MACOS:
            run_kwargs.update({"platform": "linux/amd64", "privileged": True})  # Required for DB2

        if service == "mysql":
            _apply_mysql_docker_run_options(run_kwargs)
        container = docker_client.containers.run(**run_kwargs)
    wait_for_readiness(service, container)
    config = db_configs[service].copy()
    # Always use the same schema for all tests
    config["schema"] = _test_schema_for_service(service, config)
    config["type"] = service  # Ensure type is set
    yield config
    # Do not remove container after test (leave running for reuse)


@pytest.fixture(autouse=True)
def cleanup_database(request):
    """Clean the test schema before and after each test for all supported DBs using DBLiftClient (follows user code path)."""
    print("[DEBUG] cleanup_database fixture START")

    # Check if this test uses any database container fixture
    db_fixtures = [
        "db_container",
        "sqlserver_container",
        "oracle_container",
        "postgresql_container",
        "mysql_container",
        "db2_container",
        "cosmosdb_container",
    ]

    uses_db = any(fixture in request.fixturenames for fixture in db_fixtures)

    if not uses_db:
        print(
            f"DEBUG: cleanup_database fixture - test {request.node.name} doesn't use database, skipping"
        )
        yield
        return

    # Get the container configuration from any of the container fixtures
    container_config = None

    # First check if the test uses the parameterized 'db_container' fixture
    if "db_container" in request.fixturenames:
        try:
            container_config = request.getfixturevalue("db_container")
        except Exception as e:
            print(f"DEBUG: Failed to get db_container: {e}")
            pass  # Continue to check for specific named fixtures

    # If not found, check which specific container fixture is being used in this test
    if container_config is None:
        for fixture_name in [
            "sqlserver_container",
            "oracle_container",
            "postgresql_container",
            "mysql_container",
            "db2_container",
            "cosmosdb_container",
        ]:
            if fixture_name in request.fixturenames:
                try:
                    container_config = request.getfixturevalue(fixture_name)
                    break
                except Exception as e:
                    print(f"DEBUG: Failed to get {fixture_name}: {e}")
                    continue

    if container_config is None:
        print(
            f"DEBUG: cleanup_database fixture - no container config found for test {request.node.name}"
        )
        yield
        return
    print(
        f"DEBUG: cleanup_database fixture activated for test {request.node.name} with config: {container_config}"
    )
    db_type = container_config.get("type")
    print(f"[DEBUG] cleanup_database: db_type = {db_type}")

    # Handle CosmosDB cleanup separately (native database)
    if db_type == "cosmosdb":
        print(f"[DEBUG] cleanup_database: Performing CosmosDB cleanup")
        try:
            # Build CosmosDB config
            cosmosdb_config_dict = {
                "database": {
                    "type": "cosmosdb",
                    "url": container_config.get("url", container_config.get("account_endpoint")),
                    "account_endpoint": container_config.get("account_endpoint"),
                    "account_key": container_config.get("account_key"),
                    "database_name": container_config.get("database_name"),
                    "container_name": container_config.get("container_name", "default"),
                },
                "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
                "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_cleanup.log"},
            }

            from api import DBLiftClient

            config = DbliftConfig.from_dict(cosmosdb_config_dict)
            log_dir = Path("./logs")
            log_dir.mkdir(parents=True, exist_ok=True)

            logger = DbliftLogger(
                logfile_dir=log_dir, format=LogFormat.TEXT, level=LogLevel.DEBUG, config=config
            )

            client = DBLiftClient.from_config(config, logger=logger)
            provider = client.provider
            schema = "default"  # CosmosDB uses "default" as schema name

            # Clean before test
            print("[DEBUG] cleanup_database: cleaning CosmosDB containers (before test)")
            if hasattr(provider, "clean_schema"):
                try:
                    clean_response = provider.clean_schema(schema)
                    if clean_response and hasattr(clean_response, "statements"):
                        print(
                            f"[DEBUG] cleanup_database: cleaned {len(clean_response.statements)} containers"
                        )
                except Exception as clean_err:
                    print(
                        f"[DEBUG] cleanup_database: CosmosDB clean_schema failed (may be empty): {clean_err}"
                    )

            provider.close()
            print("[DEBUG] cleanup_database: CosmosDB cleaned successfully (before test)")
        except Exception as e:
            print(f"[DEBUG] cleanup_database: CosmosDB cleanup (before test) failed: {e}")

        # Yield control to test
        yield

        # Clean after test
        try:
            print("[DEBUG] cleanup_database: cleaning CosmosDB containers (after test)")
            client = DBLiftClient.from_config(config, logger=logger)
            provider = client.provider

            if hasattr(provider, "clean_schema"):
                try:
                    clean_response = provider.clean_schema(schema)
                    if clean_response and hasattr(clean_response, "statements"):
                        print(
                            f"[DEBUG] cleanup_database: cleaned {len(clean_response.statements)} containers (after test)"
                        )
                except Exception as clean_err:
                    print(
                        f"[DEBUG] cleanup_database: CosmosDB clean_schema failed (after test): {clean_err}"
                    )

            provider.close()
            print("[DEBUG] cleanup_database: CosmosDB cleaned successfully (after test)")
        except Exception as e:
            print(f"[DEBUG] cleanup_database: CosmosDB cleanup (after test) failed: {e}")

        return

    # Build database config
    db_config = {
        "type": db_type,
        "username": container_config["username"],
        "password": container_config["password"],
        "schema": container_config.get("schema", "TEST_SCHEMA"),
    }

    # Add database-specific fields
    if db_type == "oracle":
        db_config["host"] = container_config["host"]
        db_config["port"] = container_config["port"]
        # Determine service name (prefer explicit 'service')
        service_or_database = container_config.get(
            "service", container_config.get("database", "XE")
        )
        db_config["service_name"] = service_or_database
        # Build native URL for Oracle
        db_config["url"] = (
            f"oracle+oracledb://{container_config['host']}:{container_config['port']}?service_name={service_or_database}"
        )
    else:
        # For other databases, construct the URL
        db_config["url"] = container_config.get("url") or (
            f"mssql+pymssql://{container_config['host']}:{container_config['port']}/{container_config['database']}"
            if db_type == "sqlserver"
            else (
                f"postgresql+psycopg://{container_config['username']}:{container_config['password']}"
                f"@{container_config['host']}:{container_config['port']}/{container_config['database']}"
                if db_type == "postgresql"
                else (
                    f"mysql+pymysql://{container_config['username']}:{container_config['password']}"
                    f"@{container_config['host']}:{container_config['port']}/{container_config['database']}"
                    if db_type == "mysql"
                    else (
                        f"ibm_db_sa://{container_config['username']}:{container_config['password']}"
                        f"@{container_config['host']}:{container_config['port']}/{container_config['database']}"
                        if db_type == "db2"
                        else None
                    )
                )
            )
        )

    config_dict = {
        "database": db_config,
        "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
        "logging": {"level": "DEBUG", "file": "dblift_integration_cleanup.log"},
    }
    print(f"[DEBUG] cleanup_database: config_dict = {config_dict}")
    config = DbliftConfig.from_dict(config_dict)
    print("[DEBUG] cleanup_database: DbliftConfig created")

    # Create a logger directly for cleanup operations
    test_name = request.node.name
    log_file = f"dblift_cleanup_{test_name}.log"
    log_dir = Path("./logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = DbliftLogger(
        logfile_dir=log_dir, format=LogFormat.TEXT, level=LogLevel.DEBUG, config=config
    )

    # Use DBLiftClient to follow the same code path as users
    # This ensures we test the provider layer through the client API
    from api import DBLiftClient

    # Create a temporary migrations directory for the client (required but not used for cleanup)
    temp_migrations_dir = Path("/tmp")
    client = DBLiftClient.from_config(config, logger=logger)
    print("[DEBUG] cleanup_database: DBLiftClient created (following user code path)")

    # Clean before test - use provider's clean_schema method
    # This drops ALL objects in the schema (tables, views, sequences, etc.)
    # including the history table, giving us a clean slate
    try:
        print("[DEBUG] cleanup_database: cleaning schema objects (before test)")
        schema = config.database.schema
        provider = client.provider

        # CRITICAL: Rollback any existing aborted transaction BEFORE clean_schema
        # PostgreSQL aborts transactions on any error, and subsequent queries hang
        # However, for DB2/MySQL, transactions are already committed, so skip rollback to avoid hangs
        if db_type not in ("mysql", "db2"):
            try:
                provider.rollback_transaction()
                print(
                    "[DEBUG] cleanup_database: rolled back any existing transaction before cleanup"
                )
            except Exception as rollback_err:
                print(
                    f"[DEBUG] cleanup_database: rollback before cleanup failed (may be normal): {rollback_err}"
                )
        else:
            print(
                f"[DEBUG] cleanup_database: Skipping rollback for {db_type} before cleanup (transactions already committed)"
            )

        _ensure_schema_before_cleanup(provider, db_type, schema)

        # Use provider's clean_schema method to drop all user objects
        if hasattr(provider, "clean_schema"):
            try:
                clean_response = provider.clean_schema(schema)
                if hasattr(clean_response, "statements"):
                    statement_count = len(clean_response.statements)
                else:
                    statement_count = len(clean_response or [])
                print(f"[DEBUG] cleanup_database: cleaned {statement_count} objects from schema")

                # CRITICAL: MySQL and DB2 clean_schema already commits, so skip redundant commit
                # Committing again after clean_schema commits can cause hangs
                if db_type not in ("mysql", "db2"):
                    # Commit the cleanup changes for other databases
                    try:
                        provider.commit_transaction()
                        print("[DEBUG] cleanup_database: committed cleanup changes")
                    except Exception as commit_err:
                        print(f"[DEBUG] cleanup_database: commit failed: {commit_err}")
                        # Try rollback and then close
                        try:
                            provider.rollback_transaction()
                        except Exception:
                            pass
                else:
                    print(
                        f"[DEBUG] cleanup_database: Skipping commit for {db_type} (clean_schema already committed)"
                    )
            except Exception as clean_err:
                print(f"[DEBUG] cleanup_database: clean_schema failed: {clean_err}")
                # CRITICAL: Rollback immediately to prevent hangs
                try:
                    provider.rollback_transaction()
                except Exception:
                    pass
                # Re-raise to be caught by outer handler
                raise
        else:
            # Fallback for providers without clean_schema (shouldn't happen)
            print("[DEBUG] cleanup_database: provider doesn't have clean_schema, skipping")

        # Close connection to ensure clean state for test
        try:
            provider.close()
            print("[DEBUG] cleanup_database: closed provider connection")
        except Exception as close_err:
            print(f"[DEBUG] cleanup_database: provider close failed (not critical): {close_err}")

        print("[DEBUG] cleanup_database: schema cleaned successfully")
    except Exception as e:
        logger.warning(f"Database cleanup (before) failed but continuing: {e}")
        print(f"[DEBUG] cleanup_database: schema cleanup (before test) failed: {e}")
        # CRITICAL: Rollback any aborted transaction before continuing
        # This prevents hangs on subsequent operations
        try:
            if hasattr(client, "provider") and hasattr(client.provider, "rollback_transaction"):
                client.provider.rollback_transaction()
        except Exception:
            pass  # Ignore rollback errors

    # Reset global state before test
    try:
        print("[DEBUG] cleanup_database: cleaning up executor references")
        # No more global active_executor to reset - using dependency injection now
        print("[DEBUG] cleanup_database: executor cleanup complete")
    except Exception as e:
        logger.warning(f"Global state reset failed but continuing: {e}")
        print(f"[DEBUG] cleanup_database: cleanup failed: {e}")

    yield

    # Clean after test - use provider's clean_schema() to drop all objects within schema
    try:
        print("[DEBUG] cleanup_database: cleaning schema objects (after test)")
        schema = config.database.schema

        # Recreate client for after-test cleanup (connection may have been closed)
        client = DBLiftClient.from_config(config, logger=logger)
        provider = client.provider

        # CRITICAL: Rollback any existing aborted transaction BEFORE clean_schema
        # PostgreSQL aborts transactions on any error, and subsequent queries hang
        # However, for DB2/MySQL, transactions are already committed, so skip rollback to avoid hangs
        if db_type not in ("mysql", "db2"):
            try:
                provider.rollback_transaction()
                print(
                    "[DEBUG] cleanup_database: rolled back any existing transaction before cleanup (after test)"
                )
            except Exception as rollback_err:
                print(
                    f"[DEBUG] cleanup_database: rollback before cleanup failed (after test, may be normal): {rollback_err}"
                )
        else:
            print(
                f"[DEBUG] cleanup_database: Skipping rollback for {db_type} before cleanup (transactions already committed) (after test)"
            )

        _ensure_schema_before_cleanup(provider, db_type, schema)

        # Use provider's clean_schema method to drop all user objects (including history table)
        if hasattr(provider, "clean_schema"):
            try:
                clean_response = provider.clean_schema(schema)
                if hasattr(clean_response, "statements"):
                    statement_count = len(clean_response.statements)
                else:
                    statement_count = len(clean_response or [])
                print(f"[DEBUG] cleanup_database: cleaned {statement_count} objects from schema")

                # CRITICAL: MySQL and DB2 clean_schema already commits, so skip redundant commit
                # Committing again after clean_schema commits can cause hangs
                if db_type not in ("mysql", "db2"):
                    # Commit the cleanup changes for other databases
                    try:
                        provider.commit_transaction()
                        print("[DEBUG] cleanup_database: committed cleanup changes (after test)")
                    except Exception as commit_err:
                        print(f"[DEBUG] cleanup_database: commit failed (after test): {commit_err}")
                        # Try rollback and then close
                        try:
                            provider.rollback_transaction()
                        except Exception:
                            pass
                else:
                    print(
                        f"[DEBUG] cleanup_database: Skipping commit for {db_type} (clean_schema already committed) (after test)"
                    )
            except Exception as clean_err:
                print(f"[DEBUG] cleanup_database: clean_schema failed (after test): {clean_err}")
                # CRITICAL: Rollback immediately to prevent hangs (but skip for DB2/MySQL)
                # For DB2/MySQL, transactions are already committed, so rollback can cause hangs
                if db_type not in ("mysql", "db2"):
                    try:
                        provider.rollback_transaction()
                    except Exception:
                        pass
                else:
                    print(
                        f"[DEBUG] cleanup_database: Skipping rollback for {db_type} after clean_schema error (transactions already committed)"
                    )
                # Re-raise to be caught by outer handler
                raise
        else:
            print("[DEBUG] cleanup_database: provider doesn't have clean_schema, skipping")

        # Close connection to ensure clean state
        try:
            provider.close()
            print("[DEBUG] cleanup_database: closed provider connection (after test)")
        except Exception as close_err:
            print(f"[DEBUG] cleanup_database: provider close failed (not critical): {close_err}")

        print("[DEBUG] cleanup_database: schema cleaned successfully (after test)")
    except Exception as e:
        logger.warning(f"Database cleanup (after) failed but continuing: {e}")
        print(f"[DEBUG] cleanup_database: schema cleanup (after test) failed: {e}")
        # CRITICAL: Rollback any aborted transaction before continuing (but skip for DB2/MySQL)
        # For DB2/MySQL, transactions are already committed, so rollback can cause hangs
        if db_type not in ("mysql", "db2"):
            try:
                if (
                    "client" in locals()
                    and hasattr(client, "provider")
                    and hasattr(client.provider, "rollback_transaction")
                ):
                    client.provider.rollback_transaction()
            except Exception:
                pass  # Ignore rollback errors
        else:
            print(
                f"[DEBUG] cleanup_database: Skipping rollback for {db_type} in exception handler (transactions already committed)"
            )

    # Cleanup is handled by provider.close() above

    print("[DEBUG] cleanup_database fixture END")


@pytest.fixture
def integration_logger(request):
    """Create a logger for integration tests with unique name per test."""
    test_name = request.node.name
    log_file = f"dblift_integration_{test_name}.log"
    log_dir = Path("./logs")
    log_dir.mkdir(parents=True, exist_ok=True)  # Ensure log directory exists

    # CLEANUP: Remove any existing log file from previous test runs to prevent contamination
    log_file_path = log_dir / log_file
    if log_file_path.exists():
        try:
            log_file_path.unlink()
            print(f"DEBUG: Removed existing log file: {log_file_path}")
        except Exception as e:
            print(f"Warning: Failed to remove existing log file {log_file_path}: {str(e)}")

    # Create unique logger name to avoid conflicts
    logger_name = f"integration_logger_{test_name}_{id(request)}"

    logger = DbliftLogger(
        name=logger_name,
        level=LogLevel.DEBUG,
        format=LogFormat.TEXT,
        logfile_dir=log_dir,
        log_file_pattern=log_file,
    )

    # Ensure clean log file at start of test
    if (
        hasattr(logger, "current_log_file")
        and logger.current_log_file
        and logger.current_log_file.exists()
    ):
        try:
            # Truncate the log file to ensure clean start
            with open(logger.current_log_file, "w") as f:
                f.write("")
            print(f"DEBUG: Truncated log file for clean start: {logger.current_log_file}")
        except Exception as e:
            print(f"Warning: Failed to truncate log file: {str(e)}")

    yield logger

    # Clean up logger resources to prevent accumulation
    try:
        # Close any file handlers to free resources
        if hasattr(logger, "_logger") and hasattr(logger._logger, "handlers"):
            for handler in logger._logger.handlers[:]:
                try:
                    handler.close()
                    logger._logger.removeHandler(handler)
                except Exception as e:
                    print(f"Warning: Failed to close log handler: {str(e)}")

        # CLEANUP: Remove log file after test to prevent contamination for next test
        if (
            hasattr(logger, "current_log_file")
            and logger.current_log_file
            and logger.current_log_file.exists()
        ):
            try:
                logger.current_log_file.unlink()
                print(f"DEBUG: Cleaned up log file after test: {logger.current_log_file}")
            except Exception as e:
                print(f"Warning: Failed to remove log file after test: {str(e)}")

    except Exception as e:
        print(f"Warning: Failed to clean up logger: {str(e)}")


@pytest.fixture(scope="session", autouse=True)
def session_cleanup():
    """Ensure proper cleanup of session-scoped resources."""
    print("[DEBUG] session_cleanup fixture START")
    yield
    # Final cleanup of any remaining resources
    try:
        import gc

        gc.collect()
        print("Session cleanup completed")
    except Exception as e:
        print(f"Warning: Session cleanup failed: {str(e)}")
    print("[DEBUG] session_cleanup fixture END")


@pytest.fixture
def sqlserver_container(docker_client, db_configs):
    """Start and yield SQL Server container configuration."""
    service = "sqlserver"

    # Skip tests for databases not in SUPPORTED_DBS
    if service not in SUPPORTED_DBS:
        pytest.skip(f"{service} tests are not enabled (not in SUPPORTED_DBS: {SUPPORTED_DBS})")

    container_name = db_container_names[service]
    try:
        container = docker_client.containers.get(container_name)
        if container.status != "running":
            container.start()
            print(f"Started existing container {container_name}")
    except docker.errors.NotFound:
        print(f"Creating and starting new container {container_name}")
        run_kwargs = dict(
            image=image_map[service],
            name=container_name,
            environment=env_map[service],
            ports=port_map[service],
            detach=True,
        )
        container = docker_client.containers.run(**run_kwargs)

    wait_for_readiness(service, container)
    config = db_configs[service].copy()
    # For Oracle, use the connected user schema (SYSTEM)
    if service == "oracle":
        config["schema"] = config.get("username", "SYSTEM").upper()
        # Ensure service is present
        if "service" not in config:
            config["service"] = config.get("database", "XE")
    else:
        config["schema"] = "TEST_SCHEMA"
    yield config


@pytest.fixture
def oracle_container(docker_client, db_configs):
    """Start and yield Oracle container configuration."""
    service = "oracle"

    # Skip tests for databases not in SUPPORTED_DBS
    if service not in SUPPORTED_DBS:
        pytest.skip(f"{service} tests are not enabled (not in SUPPORTED_DBS: {SUPPORTED_DBS})")

    container_name = db_container_names[service]
    try:
        container = docker_client.containers.get(container_name)
        if container.status != "running":
            container.start()
            print(f"Started existing container {container_name}")
    except docker.errors.NotFound:
        print(f"Creating and starting new container {container_name}")
        run_kwargs = dict(
            image=image_map[service],
            name=container_name,
            environment=env_map[service],
            ports=port_map[service],
            detach=True,
        )
        container = docker_client.containers.run(**run_kwargs)

    wait_for_readiness(service, container)
    config = db_configs[service].copy()
    # For Oracle, use a dedicated test schema to avoid system objects
    if service == "oracle":
        config["schema"] = "DBLIFT_TEST"
        if "service" not in config:
            config["service"] = config.get("database", "XE")
    else:
        config["schema"] = "TEST_SCHEMA"
    yield config


@pytest.fixture
def postgresql_container(docker_client, db_configs):
    """Start and yield PostgreSQL container configuration."""
    service = "postgresql"

    # Skip tests for databases not in SUPPORTED_DBS
    if service not in SUPPORTED_DBS:
        pytest.skip(f"{service} tests are not enabled (not in SUPPORTED_DBS: {SUPPORTED_DBS})")

    container_name = db_container_names[service]
    try:
        container = docker_client.containers.get(container_name)
        if container.status != "running":
            container.start()
            print(f"Started existing container {container_name}")
    except docker.errors.NotFound:
        print(f"Creating and starting new container {container_name}")
        run_kwargs = dict(
            image=image_map[service],
            name=container_name,
            environment=env_map[service],
            ports=port_map[service],
            detach=True,
        )
        container = docker_client.containers.run(**run_kwargs)

    wait_for_readiness(service, container)
    config = db_configs[service].copy()
    config["schema"] = "TEST_SCHEMA"
    yield config


@pytest.fixture
def mysql_container(docker_client, db_configs):
    """Start and yield MySQL container configuration."""
    service = "mysql"

    # Skip tests for databases not in SUPPORTED_DBS
    if service not in SUPPORTED_DBS:
        pytest.skip(f"{service} tests are not enabled (not in SUPPORTED_DBS: {SUPPORTED_DBS})")

    if EXTERNAL_MYSQL_HOST:
        print(
            f"[MYSQL] Using external instance at {EXTERNAL_MYSQL_HOST}:{db_configs['mysql']['port']} "
            "for mysql_container fixture"
        )
        config = db_configs["mysql"].copy()
        config["schema"] = _test_schema_for_service(service, config)
        yield config
        return

    container_name = db_container_names[service]
    created_new_container = False

    try:
        container = docker_client.containers.get(container_name)
        if container.status != "running":
            container.start()
            wait_for_readiness(service, container)
            print(f"[MYSQL] Using existing container with root credentials")
    except docker.errors.NotFound:
        # Container doesn't exist, create it (inline creation logic)
        created_new_container = True
        run_kwargs = dict(
            image=image_map[service],
            name=container_name,
            environment=env_map[service],
            ports=port_map[service],
            detach=True,
        )

        if service == "mysql":
            _apply_mysql_docker_run_options(run_kwargs)

        container = docker_client.containers.run(**run_kwargs)
        wait_for_readiness(service, container)

        # For MySQL new containers, create dblift user after container is ready
        if service == "mysql" and created_new_container:
            print(f"[MYSQL] Creating dblift user via SQL execution")
            try:
                time.sleep(3)  # Extra wait for MySQL to be fully ready

                mysql_database = _test_schema_for_service(service, db_configs[service]).replace(
                    "`", "``"
                )

                # Execute SQL to create user and database
                init_sql_commands = [
                    "CREATE USER IF NOT EXISTS 'dblift'@'%' IDENTIFIED BY 'dblift'",
                    "CREATE USER IF NOT EXISTS 'dblift'@'localhost' IDENTIFIED BY 'dblift'",
                    "CREATE USER IF NOT EXISTS 'dblift'@'127.0.0.1' IDENTIFIED BY 'dblift'",
                    f"CREATE DATABASE IF NOT EXISTS `{mysql_database}`",
                    "GRANT ALL PRIVILEGES ON *.* TO 'dblift'@'%' WITH GRANT OPTION",
                    "GRANT ALL PRIVILEGES ON *.* TO 'dblift'@'localhost' WITH GRANT OPTION",
                    "GRANT ALL PRIVILEGES ON *.* TO 'dblift'@'127.0.0.1' WITH GRANT OPTION",
                    "FLUSH PRIVILEGES",
                ]

                for sql_command in init_sql_commands:
                    exec_result = container.exec_run(
                        f'mysql -uroot -proot -e "{sql_command}"', tty=True
                    )
                    if exec_result.exit_code != 0:
                        print(f"[MYSQL] Warning: SQL command failed: {sql_command}")
                        print(f"[MYSQL] Output: {exec_result.output.decode()}")

                print(f"[MYSQL] Created dblift user successfully")
            except Exception as e:
                print(f"[MYSQL] Warning: failed to create dblift user: {e}")
                print(f"[MYSQL] Will use root credentials instead")
                created_new_container = False  # Fall back to root credentials

    config = db_configs[service].copy()
    published_port = _published_host_port(container, "3306/tcp")
    if published_port is not None:
        config["port"] = published_port
    config["schema"] = _test_schema_for_service(service, config)

    # IMPORTANT: Only use dblift credentials if we successfully created a new container with dblift user
    # Existing containers use root credentials from environment variables
    if service == "mysql" and created_new_container:
        # Use the dedicated test user created via SQL
        config["username"] = "dblift"
        config["password"] = "dblift"
        print(f"[MYSQL] Using dblift credentials for new container")
    else:
        print(f"[MYSQL] Using root credentials from db_configs for existing container")

    yield config


@pytest.fixture
def db2_container(docker_client, db_configs):
    """Start and yield DB2 container configuration."""
    service = "db2"

    # Skip tests for databases not in SUPPORTED_DBS
    if service not in SUPPORTED_DBS:
        pytest.skip(f"{service} tests are not enabled (not in SUPPORTED_DBS: {SUPPORTED_DBS})")

    # Skip DB2 tests on MacOS unless an external instance is provided
    if IS_MACOS and not EXTERNAL_DB2_HOST:
        pytest.skip("DB2 tests are not supported on MacOS")

    if EXTERNAL_DB2_HOST:
        print(
            f"[DB2] Using external instance at {EXTERNAL_DB2_HOST}:{db_configs['db2']['port']} "
            "for db2_container fixture"
        )
        config = db_configs["db2"].copy()
        config["schema"] = EXTERNAL_DB2_SCHEMA if EXTERNAL_DB2_SCHEMA else "DB2INST1"
        yield config
        return

    container_name = db_container_names[service]
    try:
        container = docker_client.containers.get(container_name)
        if container.status != "running":
            container.start()
            print(f"Started existing container {container_name}")
    except docker.errors.NotFound:
        print(f"Creating and starting new container {container_name}")
        run_kwargs = dict(
            image=image_map[service],
            name=container_name,
            environment=env_map[service],
            ports=port_map[service],
            detach=True,
            platform="linux/amd64",
            privileged=True,  # Required for DB2
        )
        container = docker_client.containers.run(**run_kwargs)

    wait_for_readiness(service, container)
    config = db_configs[service].copy()
    config["schema"] = "TEST_SCHEMA"
    yield config


@pytest.fixture
def cosmosdb_container(docker_client, db_configs):
    """Start and yield CosmosDB container configuration.

    This fixture provides CosmosDB configuration that can work with:
    1. CosmosDB Emulator (default - auto-started if not running)
    2. External CosmosDB instance (via environment variables)

    Environment variables for external CosmosDB:
    - DBLIFT_COSMOSDB_ENDPOINT: CosmosDB account endpoint
    - DBLIFT_COSMOSDB_KEY: CosmosDB account key
    - DBLIFT_COSMOSDB_DATABASE: Database name
    - DBLIFT_COSMOSDB_CONTAINER: Container name (optional)
    """
    service = "cosmosdb"

    # Skip tests for databases not in SUPPORTED_DBS
    if service not in SUPPORTED_DBS:
        pytest.skip(f"{service} tests are not enabled (not in SUPPORTED_DBS: {SUPPORTED_DBS})")

    config = db_configs[service].copy()

    # Check if we have external CosmosDB configuration
    if EXTERNAL_COSMOSDB_ENDPOINT:
        print(f"[COSMOSDB] Using external CosmosDB instance at {config['account_endpoint']}")
        # Configuration is already updated in db_configs, skip container startup
    else:
        print("[COSMOSDB] Using CosmosDB Emulator - checking if container is running...")

        # Try to start or create the CosmosDB Emulator container
        container_name = db_container_names[service]
        try:
            container = docker_client.containers.get(container_name)
            if container.status != "running":
                container.start()
                print(f"[COSMOSDB] Started existing container {container_name}")
                # Wait for CosmosDB Emulator to be ready
                wait_for_readiness(service, container)
        except docker.errors.NotFound:
            print(
                f"[COSMOSDB] Creating and starting new CosmosDB Emulator container {container_name}"
            )
            try:
                run_kwargs = dict(
                    image=image_map[service],
                    name=container_name,
                    environment=env_map[service],
                    ports=port_map[service],
                    detach=True,
                )
                container = docker_client.containers.run(**run_kwargs)
                # Wait for CosmosDB Emulator to be ready
                wait_for_readiness(service, container)
            except (docker.errors.ImageNotFound, docker.errors.NotFound) as e:
                print(
                    f"[COSMOSDB] WARNING: CosmosDB Emulator Docker image not found: {image_map[service]}"
                )
                print(f"[COSMOSDB] Error details: {str(e)}")
                print(
                    "[COSMOSDB] The CosmosDB Emulator may not be available for your platform (macOS ARM64)."
                )
                print(
                    "[COSMOSDB] Please use an external CosmosDB instance by setting environment variables:"
                )
                print(
                    "[COSMOSDB]   DBLIFT_COSMOSDB_ENDPOINT=https://your-account.documents.azure.com:443/"
                )
                print("[COSMOSDB]   DBLIFT_COSMOSDB_KEY=your-account-key")
                print("[COSMOSDB]   DBLIFT_COSMOSDB_DATABASE=your-database")
                print("[COSMOSDB]   DBLIFT_COSMOSDB_CONTAINER=your-container")
                # Mark configuration as unavailable instead of skipping in fixture
                config["_skip_reason"] = (
                    "CosmosDB Emulator Docker image not available - use external CosmosDB instance"
                )

    # Add URL field for compatibility
    config["url"] = config["account_endpoint"]

    yield config

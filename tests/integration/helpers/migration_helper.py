"""
Migration file creation helper for integration tests.

Provides functions to:
- Create migration files (versioned, repeatable, undo)
- Create configuration files
- Generate test SQL scripts
"""

import textwrap
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class MigrationHelper:
    """Helper for creating migration files in tests."""

    def __init__(self, migrations_dir: Path):
        """
        Initialize migration helper.

        Args:
            migrations_dir: Directory where migrations will be created
        """
        self.migrations_dir = Path(migrations_dir)
        self.migrations_dir.mkdir(parents=True, exist_ok=True)

    def create_versioned(
        self, version: str, description: str, sql: str, tags: Optional[list] = None
    ) -> Path:
        """
        Create a versioned migration file.

        Args:
            version: Version number (e.g., "1.0.0")
            description: Migration description
            sql: SQL content
            tags: Optional list of tags

        Returns:
            Path to created migration file
        """
        version_str = version.replace(".", "_")
        filename = f"V{version_str}__{description}"

        if tags:
            filename += f"[{','.join(tags)}]"

        filename += ".sql"

        filepath = self.migrations_dir / filename
        filepath.write_text(sql)
        return filepath

    def create_repeatable(self, description: str, sql: str, tags: Optional[list] = None) -> Path:
        """
        Create a repeatable migration file.

        Args:
            description: Migration description
            sql: SQL content
            tags: Optional list of tags

        Returns:
            Path to created migration file
        """
        filename = f"R__{description}"

        if tags:
            filename += f"[{','.join(tags)}]"

        filename += ".sql"

        filepath = self.migrations_dir / filename
        filepath.write_text(sql)
        return filepath

    def create_undo(
        self, version: str, description: str, sql: str, tags: Optional[list] = None
    ) -> Path:
        """
        Create an undo migration file.

        Args:
            version: Version number (e.g., "1.0.0")
            description: Migration description
            sql: SQL content
            tags: Optional list of tags

        Returns:
            Path to created migration file
        """
        version_str = version.replace(".", "_")
        filename = f"U{version_str}__{description}"

        if tags:
            filename += f"[{','.join(tags)}]"

        filename += ".sql"

        filepath = self.migrations_dir / filename
        filepath.write_text(sql)
        return filepath


# Convenience functions


def create_migration(migrations_dir: Path, filename: str, sql: str) -> Path:
    """
    Create a migration file with the given filename and SQL content.

    Args:
        migrations_dir: Directory where migration will be created
        filename: Full filename (e.g., "V1_0_0__initial.sql")
        sql: SQL content

    Returns:
        Path to created migration file
    """
    migrations_dir = Path(migrations_dir)
    migrations_dir.mkdir(parents=True, exist_ok=True)

    filepath = migrations_dir / filename
    filepath.write_text(sql)
    return filepath


def create_versioned_migration(
    migrations_dir: Path,
    version: str,
    description: str,
    sql: str,
    tags: Optional[list] = None,
) -> Path:
    """
    Create a versioned migration file.

    Args:
        migrations_dir: Directory where migration will be created
        version: Version number (e.g., "1.0.0")
        description: Migration description
        sql: SQL content
        tags: Optional list of tags

    Returns:
        Path to created migration file
    """
    helper = MigrationHelper(migrations_dir)
    return helper.create_versioned(version, description, sql, tags)


def create_repeatable_migration(
    migrations_dir: Path,
    description: str,
    sql: str,
    tags: Optional[list] = None,
) -> Path:
    """
    Create a repeatable migration file.

    Args:
        migrations_dir: Directory where migration will be created
        description: Migration description
        sql: SQL content
        tags: Optional list of tags

    Returns:
        Path to created migration file
    """
    helper = MigrationHelper(migrations_dir)
    return helper.create_repeatable(description, sql, tags)


def create_undo_migration(
    migrations_dir: Path,
    version: str,
    description: str,
    sql: str,
    tags: Optional[list] = None,
) -> Path:
    """
    Create an undo migration file.

    Args:
        migrations_dir: Directory where migration will be created
        version: Version number (e.g., "1.0.0")
        description: Migration description
        sql: SQL content
        tags: Optional list of tags

    Returns:
        Path to created migration file
    """
    helper = MigrationHelper(migrations_dir)
    return helper.create_undo(version, description, sql, tags)


def create_config(
    tmp_path: Path,
    db_config: Dict[str, Any],
    migrations_dir: Optional[Path] = None,
    **extra_config,
) -> Path:
    """
    Create a dblift.yaml configuration file for testing.

    Args:
        tmp_path: Temporary directory path
        db_config: Database container configuration
        migrations_dir: Optional migrations directory path
        **extra_config: Additional configuration options

    Returns:
        Path to created configuration file
    """
    db_type = db_config.get("type")

    # Handle SQLite (native, file-based)
    if db_type in ("sqlite", "sqlite3"):
        config_dict = {
            "database": {
                "type": db_type,
                "path": db_config.get("path", db_config.get("database", ":memory:")),
                "schema": db_config.get("schema", "main"),
            }
        }
    # Handle CosmosDB (native, Azure SDK-based)
    elif db_type == "cosmosdb":
        config_dict = {
            "database": {
                "type": db_type,
                "url": db_config.get("url", db_config.get("account_endpoint")),
                "account_endpoint": db_config.get("account_endpoint"),
                "account_key": db_config.get("account_key"),
                "database_name": db_config.get("database_name"),
            }
        }
    # Handle MongoDB (native, pymongo — no SQLAlchemy URL)
    elif db_type in ("mongodb", "mongo"):
        config_dict = {
            "database": {
                "type": "mongodb",
                "host": db_config.get("host", "localhost"),
                "port": int(db_config.get("port", 27017)),
                "database": db_config.get("database", "testdb"),
            }
        }
        if db_config.get("username"):
            config_dict["database"]["username"] = db_config["username"]
        if db_config.get("password"):
            config_dict["database"]["password"] = db_config["password"]
        if db_config.get("url"):
            config_dict["database"]["url"] = db_config["url"]
    else:
        # Build database URL based on database type
        if db_type == "sqlserver":
            url = f"mssql+pymssql://{db_config['host']}:{db_config['port']}/{db_config['database']}"
        elif db_type == "oracle":
            service_or_database = db_config.get("service", db_config.get("database", "XE"))
            url = f"oracle+oracledb://{db_config['host']}:{db_config['port']}?service_name={service_or_database}"
        elif db_type == "postgresql":
            url = (
                f"postgresql+psycopg://{db_config['username']}:{db_config['password']}"
                f"@{db_config['host']}:{db_config['port']}/{db_config['database']}"
            )
        elif db_type == "mysql":
            url = (
                f"mysql+pymysql://{db_config['username']}:{db_config['password']}"
                f"@{db_config['host']}:{db_config['port']}/{db_config['database']}"
            )
        elif db_type == "db2":
            url = f"ibm_db_sa://{db_config['host']}:{db_config['port']}/{db_config['database']}"
        else:
            raise ValueError(f"Unsupported database type: {db_type}")

        config_dict = {
            "database": {
                "type": db_type,
                "url": url,
                "username": db_config["username"],
                "password": db_config["password"],
                "schema": db_config.get("schema", "TEST_SCHEMA"),
            }
        }

        # Ensure Oracle has service_name set for providers that require it
        if db_type == "oracle":
            config_dict["database"]["service_name"] = service_or_database

    # Add migrations directory if provided
    if migrations_dir:
        config_dict["migrations"] = {"directory": str(migrations_dir)}

    # Add logging configuration with DEBUG level for better test visibility
    if "logging" not in config_dict:
        config_dict["logging"] = {"level": "DEBUG"}

    # Add any extra configuration (this will override logging if explicitly set)
    config_dict.update(extra_config)

    # Write configuration file
    config_file = tmp_path / "dblift.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_dict, f)

    return config_file


def get_auto_increment_syntax(db_type: str) -> str:
    """
    Get database-specific auto-increment column syntax.

    Args:
        db_type: Database type (postgresql, mysql, sqlserver, oracle, db2)

    Returns:
        SQL syntax for auto-increment integer primary key column
    """
    if db_type == "postgresql":
        return "SERIAL PRIMARY KEY"
    elif db_type == "mysql":
        return "INT AUTO_INCREMENT PRIMARY KEY"
    elif db_type == "sqlserver":
        return "INT IDENTITY(1,1) PRIMARY KEY"
    elif db_type == "oracle":
        return "INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
    elif db_type == "db2":
        # DB2 LUW requires NOT NULL and an explicit IDENTITY clause for this inline form
        return "INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1) PRIMARY KEY"
    else:
        # Generic - manual ID assignment required
        return "INT PRIMARY KEY"


def generate_test_sql(
    db_type: str, table_name: str = "test_table", schema: Optional[str] = None
) -> str:
    """
    Generate database-specific test SQL.

    Args:
        db_type: Database type (postgresql, mysql, sqlserver, oracle, db2)
        table_name: Name of table to create
        schema: Optional schema name

    Returns:
        SQL string appropriate for the database type
    """
    # Build qualified name with proper quoting for each database
    if schema:
        if db_type == "postgresql":
            qualified_name = f'"{schema}"."{table_name}"'
        elif db_type in ["mysql", "sqlserver"]:
            qualified_name = f"{schema}.{table_name}"
        elif db_type == "oracle":
            # Oracle requires quoted identifiers for schema-qualified names
            qualified_name = f'"{schema}"."{table_name}"'
        elif db_type == "db2":
            qualified_name = f"{schema}.{table_name}"
        else:
            qualified_name = f"{schema}.{table_name}"
    else:
        qualified_name = table_name

    if db_type == "postgresql":
        return f"""
            CREATE TABLE {qualified_name} (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO {qualified_name} (name) VALUES
                ('Test 1'),
                ('Test 2'),
                ('Test 3');
        """
    elif db_type == "mysql":
        return f"""
            CREATE TABLE {qualified_name} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO {qualified_name} (name) VALUES
                ('Test 1'),
                ('Test 2'),
                ('Test 3');
        """
    elif db_type == "sqlserver":
        return f"""
            CREATE TABLE {qualified_name} (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                created_at DATETIME2(7) DEFAULT GETDATE()
            );

            INSERT INTO {qualified_name} (name) VALUES
                ('Test 1'),
                ('Test 2'),
                ('Test 3');
        """
    elif db_type == "oracle":
        return f"""
            CREATE TABLE {qualified_name} (
                id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name VARCHAR2(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO {qualified_name} (name) VALUES ('Test 1');
            INSERT INTO {qualified_name} (name) VALUES ('Test 2');
            INSERT INTO {qualified_name} (name) VALUES ('Test 3');
        """
    elif db_type == "db2":
        return f"""
            CREATE TABLE {qualified_name} (
                id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT TIMESTAMP
            );

            INSERT INTO {qualified_name} (name) VALUES
                ('Test 1'),
                ('Test 2'),
                ('Test 3');
        """
    else:
        # Generic SQL
        return f"""
            CREATE TABLE {qualified_name} (
                id INT PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            );

            INSERT INTO {qualified_name} (id, name) VALUES
                (1, 'Test 1'),
                (2, 'Test 2'),
                (3, 'Test 3');
        """


def generate_structured_udt_create_sql(db_type: str, schema: str, type_name: str) -> str:
    """Generate CREATE TYPE SQL for structured user-defined types."""

    if db_type == "postgresql":
        return textwrap.dedent(f"""
            CREATE TYPE "{schema}"."{type_name}" AS (
                street VARCHAR(100),
                city VARCHAR(50),
                zip_code VARCHAR(10)
            );
            """).strip()

    if db_type == "oracle":
        return textwrap.dedent(f"""
            CREATE TYPE {schema}.{type_name} AS OBJECT (
                STREET VARCHAR2(100),
                CITY VARCHAR2(50),
                ZIP_CODE VARCHAR2(10)
            );
            """).strip()

    if db_type == "sqlserver":
        return f"CREATE TYPE [{schema}].[{type_name}] FROM VARCHAR(255);"

    if db_type == "db2":
        return textwrap.dedent(f"""
            CREATE TYPE {schema}.{type_name} AS ROW (
                STREET VARCHAR(100),
                CITY VARCHAR(50),
                ZIP_CODE VARCHAR(10)
            );
            """).strip()

    raise ValueError(f"Unsupported database type for structured UDT creation: {db_type}")


def generate_structured_udt_modify_sql(db_type: str, schema: str, type_name: str) -> str:
    """Generate SQL to modify structured UDT definitions."""

    if db_type == "postgresql":
        return f'ALTER TYPE "{schema}"."{type_name}" ADD ATTRIBUTE country VARCHAR(50);'

    if db_type == "oracle":
        return f"ALTER TYPE {schema}.{type_name} ADD ATTRIBUTE COUNTRY VARCHAR2(50) CASCADE;"

    if db_type == "sqlserver":
        return textwrap.dedent(f"""
            DROP TYPE [{schema}].[{type_name}];
            CREATE TYPE [{schema}].[{type_name}] FROM NVARCHAR(50);
            """).strip()

    if db_type == "db2":
        return f"ALTER TYPE {schema}.{type_name} ADD ATTRIBUTE COUNTRY VARCHAR(50);"

    raise ValueError(f"Unsupported database type for structured UDT modification: {db_type}")


def generate_structured_udt_extra_sql(db_type: str, schema: str, type_name: str) -> str:
    """Generate SQL to create extra structured UDTs directly in the database."""

    if db_type == "postgresql":
        return textwrap.dedent(f"""
            CREATE TYPE "{schema}"."{type_name}" AS (
                legacy_id INTEGER,
                legacy_code VARCHAR(25)
            );
            """).strip()

    if db_type == "oracle":
        return textwrap.dedent(f"""
            CREATE TYPE {schema}.{type_name} AS OBJECT (
                LEGACY_ID NUMBER,
                LEGACY_CODE VARCHAR2(25)
            );
            """).strip()

    if db_type == "sqlserver":
        return f"CREATE TYPE [{schema}].[{type_name}] FROM NVARCHAR(50);"

    if db_type == "db2":
        return textwrap.dedent(f"""
            CREATE TYPE {schema}.{type_name} AS ROW (
                LEGACY_ID INTEGER,
                LEGACY_CODE VARCHAR(25)
            );
            """).strip()

    raise ValueError(f"Unsupported database type for extra structured UDTs: {db_type}")


def generate_postgresql_enum_type(schema: str, type_name: str, values: tuple[str, ...]) -> str:
    """Generate CREATE TYPE SQL for PostgreSQL ENUMs."""

    values_sql = ", ".join(f"'{value}'" for value in values)
    return f'CREATE TYPE "{schema}"."{type_name}" AS ENUM ({values_sql});'


def generate_postgresql_enum_add_value(schema: str, type_name: str, value: str) -> str:
    """Generate ALTER TYPE SQL to add a value to a PostgreSQL ENUM."""

    return f'ALTER TYPE "{schema}"."{type_name}" ADD VALUE \'{value}\';'


def generate_drop_user_defined_type_sql(db_type: str, schema: str, type_name: str) -> str:
    """Generate database-specific SQL for dropping a user-defined type."""

    if db_type == "postgresql":
        return f'DROP TYPE IF EXISTS "{schema}"."{type_name}" CASCADE;'

    if db_type == "oracle":
        return f"DROP TYPE {schema}.{type_name} FORCE"

    if db_type == "sqlserver":
        return f"DROP TYPE IF EXISTS [{schema}].[{type_name}];"

    if db_type == "db2":
        return f"DROP TYPE {schema}.{type_name} RESTRICT;"

    raise ValueError(f"Unsupported database type for dropping UDTs: {db_type}")


def generate_synonym_create_sql(
    db_type: str,
    schema: str,
    synonym_name: str,
    target_schema: str,
    target_object: str,
) -> str:
    """Generate CREATE SYNONYM SQL for supported databases."""

    if db_type == "oracle":
        return textwrap.dedent(f"""
            CREATE OR REPLACE SYNONYM {schema}.{synonym_name}
            FOR {target_schema}.{target_object};
            """).strip()

    if db_type == "sqlserver":
        return textwrap.dedent(f"""
            CREATE SYNONYM [{schema}].[{synonym_name}]
            FOR [{target_schema}].[{target_object}];
            """).strip()

    if db_type == "db2":
        return textwrap.dedent(f"""
            CREATE OR REPLACE ALIAS {schema}.{synonym_name}
            FOR {target_schema}.{target_object};
            """).strip()

    raise ValueError(f"Unsupported database type for synonym creation: {db_type}")


def generate_synonym_drop_sql(db_type: str, schema: str, synonym_name: str) -> str:
    """Generate DROP SYNONYM SQL for supported databases."""

    if db_type == "oracle":
        return f"DROP SYNONYM {schema}.{synonym_name};"

    if db_type == "sqlserver":
        return f"DROP SYNONYM IF EXISTS [{schema}].[{synonym_name}];"

    if db_type == "db2":
        # DB2 uses ALIAS (not SYNONYM) - we need to use the same as CREATE
        return f"DROP ALIAS {schema}.{synonym_name};"

    raise ValueError(f"Unsupported database type for synonym drop: {db_type}")

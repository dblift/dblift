# Configuration Guide

This guide covers all configuration options available in DBLift.

## Basic Configuration

Create a `dblift.yaml` file in your project root:

```yaml
database:
  url: "postgresql+psycopg://localhost:5432/mydb"
  schema: "public"
  username: "myuser"
  password: "mypassword"

migrations:
  directory: "./migrations"  # Single directory (legacy format)
  recursive: true  # Whether to search subdirectories (default: true)

# Snapshot configuration
snapshot_table: "dblift_schema_snapshots"  # Table name for storing schema snapshots
max_snapshots: 1  # Maximum number of snapshots to keep (default: 1, oldest deleted when limit exceeded)
```

> **`schema` is required** for every dialect except SQLite (which always uses `main`). There is no implicit default — you must set it either in `dblift.yaml` or on the command line via `--db-schema`. DBLift creates the history table, lock table, and snapshot table inside this schema, so an incorrect or missing value produces silent cross-schema mismatches (e.g. a history table written in one schema but looked up in another).

## Multiple Migration Directories

You can specify multiple migration directories. The first one is the primary directory:

```yaml
migrations:
  directories:
    - ./migrations/core      # Primary directory
    - ./migrations/features  # Additional directory
  recursive: true  # Global default for all directories
```

## Per-Directory Recursive Settings

Control recursive search per directory. Useful when some directories have subdirectories and others don't:

```yaml
migrations:
  directories:
    - path: ./migrations/core
      recursive: true    # Search subdirectories recursively
    - path: ./migrations/features
      recursive: false   # Only top-level files, no subdirectories
    - ./migrations/performance  # Uses global recursive setting (true)
  recursive: true  # Global default for directories without explicit recursive setting
```

## Mixed Format

You can mix string and dict formats in the same configuration:

```yaml
migrations:
  directories:
    - ./migrations/core                    # String format (uses global recursive)
    - path: ./migrations/features
      recursive: false                     # Dict format (per-directory setting)
```

## Supported Databases

DBLift works with these databases:

| Database | Connection URL Example | Driver extra |
|----------|------------------------|--------------|
| PostgreSQL | `postgresql+psycopg://localhost:5432/mydb` | `dblift[postgresql]` |
| CockroachDB | `postgresql+psycopg://localhost:26257/mydb` | `dblift[cockroachdb]` |
| Redshift | `postgresql+psycopg://cluster.example.com:5439/dev` | `dblift[redshift]` |
| Snowflake | `snowflake://user:password@account_identifier/database/schema?warehouse=WH&role=ROLE` | `dblift[snowflake]` |
| SQL Server | `mssql+pymssql://localhost:1433/mydb` | `dblift[sqlserver]` |
| Oracle | `oracle+oracledb://localhost:1521?sid=SID` | `dblift[oracle]` |
| MySQL | `mysql+pymysql://localhost:3306/mydb` | `dblift[mysql]` |
| MariaDB | `mysql+pymysql://localhost:3306/mydb` | `dblift[mariadb]` |
| DB2 | `ibm_db_sa://localhost:50000/mydb` | `dblift[db2]` |
| SQLite | `/path/to/database.db` or `:memory:` (see [SQLite Configuration](#sqlite-configuration)) |
| Azure Cosmos DB | `https://account.documents.azure.com:443/` (see [CosmosDB Configuration](#cosmosdb-configuration)) |

## SQLite Configuration

SQLite uses a simpler configuration format since it's a file-based database:

```yaml
database:
  type: "sqlite"
  path: "/path/to/database.db"  # Or use ":memory:" for in-memory database
  schema: "main"                 # SQLite's default schema
```

### In-Memory Database (for testing)

```yaml
database:
  type: "sqlite"
  path: ":memory:"
  schema: "main"
```

### Using Environment Variables

```bash
export DBLIFT_DB_TYPE="sqlite"
export DBLIFT_DB_PATH="/path/to/database.db"
```

### SQLite-Specific Notes

- SQLite uses Python's native `sqlite3` module
- No username/password needed (SQLite doesn't have authentication)
- Schema is always "main" (SQLite doesn't support multiple schemas)
- File path can be absolute or relative to the working directory
- Use `:memory:` for an in-memory database (useful for testing)

## CosmosDB Configuration

Azure Cosmos DB uses a different configuration format through the Azure SDK:

```yaml
database:
  type: "cosmosdb"
  account_endpoint: "https://your-account.documents.azure.com:443/"
  account_key: "your-account-key"  # Or use managed identity
  database_name: "your-database"
  # Optional: use managed identity instead of account_key
  # use_managed_identity: true
```

### For Local Development (CosmosDB Emulator)

```yaml
database:
  type: "cosmosdb"
  account_endpoint: "https://localhost:8081/"
  account_key: "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
  database_name: "your-database"
```

### Using Environment Variables

```bash
export DBLIFT_DB_TYPE="cosmosdb"
export DBLIFT_DB_ACCOUNT_ENDPOINT="https://your-account.documents.azure.com:443/"
export DBLIFT_DB_ACCOUNT_KEY="your-account-key"
export DBLIFT_DB_DATABASE_NAME="your-database"
```

## Using Environment Variables

Instead of putting passwords in `dblift.yaml`, use environment variables:

```bash
export DBLIFT_DB_URL="postgresql+psycopg://localhost:5432/mydb"
export DBLIFT_DB_USERNAME="myuser"
export DBLIFT_DB_PASSWORD="mypassword"
export DBLIFT_SNAPSHOT_TABLE="dblift_schema_snapshots"  # Optional: custom snapshot table name
export DBLIFT_MAX_SNAPSHOTS="5"  # Optional: keep up to 5 snapshots (default: 1)
```

!!! warning "Security Best Practice"
    Never commit passwords or sensitive credentials to version control. Always use environment variables for production deployments.

## File Encoding

If you're using special characters (é, ñ, ö, etc.) in your SQL files, specify the encoding:

```yaml
migrations:
  script_encoding: "utf-8"
```

`script_encoding` is strict by default. If a migration file is not valid for that encoding, DBLift reports an encoding error instead of replacing characters.

To let DBLift detect the migration script encoding before reading the file, enable `detect_encoding`:

```yaml
migrations:
  script_encoding: "utf-8"
  detect_encoding: true
```

When detection is enabled, DBLift uses the detected encoding for that file. If detection or decoding fails, the migration fails with a clear encoding error.

## Configuration Templates

Sample configuration files for different databases are available in the repository:

- [PostgreSQL Template](https://github.com/cmodiano/dblift/blob/main/dblift-postgresql.yaml.template)
- [SQL Server Template](https://github.com/cmodiano/dblift/blob/main/dblift-sqlserver.yaml.template)

## Secrets Manager Integration

Instead of storing passwords and API keys in `dblift.yaml`, you can reference
secrets stored in an external secrets manager using a URI in any string field.
DBLift resolves the URIs transparently at config load time.

DBLift core does not bundle any built-in secrets provider — it ships the
registration seam below so you can plug in whichever secrets backend your
organization uses.

### Caching

Resolved secrets are cached in process memory for a configurable TTL (default
60 seconds, set via `secrets.cache_ttl_seconds`). The cache key includes the
URI plus all provider-specific auth fields so different configs never share a
cached value. Call `config.secrets.clear_cache()` or restart the process to
force fresh resolution.

### Custom Provider Registration

If your organisation uses a secrets backend not bundled with dblift
(CyberArk, Delinea, 1Password, an internal vault, etc.), you can register
a custom provider at startup without forking dblift:

```python
from config.secrets import AbstractSecretsProvider, register_provider
from config.secrets._secrets_config import SecretsConfig
from typing import Optional

class CyberArkProvider(AbstractSecretsProvider):
    scheme = "cyberark"

    def is_available(self) -> bool:
        try:
            import conjur  # noqa: F401
            return True
        except ImportError:
            return False

    def resolve(self, uri: str) -> str:
        variable_id = uri[len("cyberark://"):]
        import conjur
        return conjur.Client().retrieve_secret(variable_id)

register_provider("cyberark", CyberArkProvider)
```

Call `register_provider` once at application startup, before any call to
`DbliftConfig.from_dict()` or `DBLiftClient`. After registration, URIs like
`cyberark://secrets/db/password` in `dblift.yaml` resolve automatically
through the same pipeline — caching, two-phase bootstrap, and offline bypass
all apply.

`register_provider` validates that:

- `scheme` is non-empty and does not contain `://`
- `cls` is a subclass of `AbstractSecretsProvider`

It raises `ValueError` or `TypeError` immediately if either check fails.

### Secret Zero

*Secret zero* is the bootstrapping problem: the credential that unlocks your
secrets manager must come from somewhere — and that somewhere is itself a
secret. A custom provider built on the registration seam above should prefer
a platform-managed identity (an IAM role, a managed identity, ambient CI/CD
credentials) over a long-lived token written into `dblift.yaml`, environment
variables, or source control. If a bootstrap credential is unavoidable, inject
it via your CI platform's native secret store rather than committing it.

## Next Steps

- Learn about **[Commands](commands.md)** to use DBLift effectively
- Check out **[Best Practices](best-practices.md)** for configuration tips
- See **[Troubleshooting](troubleshooting.md)** if you encounter issues

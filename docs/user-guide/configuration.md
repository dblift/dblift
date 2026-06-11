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

### Supported Providers

| Provider | URI scheme | Dependency |
|---|---|---|
| HashiCorp Vault | `vault://` | `hvac>=1.2.0` |
| AWS Secrets Manager | `aws-secrets://` | `boto3>=1.28.0` |
| AWS SSM Parameter Store | `aws-ssm://` | `boto3>=1.28.0` |
| Azure Key Vault | `azure-keyvault://` | `azure-identity`, `azure-keyvault-secrets` (bundled) |
| GCP Secret Manager | `gcp-secrets://` | `google-cloud-secret-manager>=2.0.0` |

### URI Formats

**HashiCorp Vault (KV v1 and v2)**

```
vault://<path>#<field>

vault://secret/data/myapp/db#password
vault://kv/myapp#api_key
```

The `#field` suffix is required. For KV v2, the path should include `/data/`
as shown above — DBLift automatically unwraps the KV v2 envelope.

Authentication uses `VAULT_TOKEN` env var or `secrets.vault.token` in config.

**AWS Secrets Manager**

```
aws-secrets://<secret-id>
aws-secrets://<secret-id>#<field>

aws-secrets://prod/myapp/db                  # plain string secret
aws-secrets://prod/myapp/db#password         # JSON object secret, extract "password" field
```

Authentication uses ambient AWS credentials (IAM role, `~/.aws`, `AWS_*` env vars).

**AWS SSM Parameter Store**

```
aws-ssm://<parameter-name>

aws-ssm:///prod/db/password    # leading slash kept as part of name
aws-ssm://prod/db/password
```

`SecureString` parameters are automatically decrypted.

**Azure Key Vault**

```
azure-keyvault://<vault-host>/secrets/<secret-name>
azure-keyvault://<vault-host>/secrets/<secret-name>/<version>

azure-keyvault://myvault.vault.azure.net/secrets/db-password
azure-keyvault://myvault.vault.azure.net/secrets/db-password/abc123
```

Authentication uses `DefaultAzureCredential` (managed identity, Azure CLI, env vars).

**GCP Secret Manager**

```
gcp-secrets://<resource-name>

gcp-secrets://projects/my-project/secrets/db-password/versions/latest
gcp-secrets://projects/my-project/secrets/db-password/versions/5
```

Authentication uses Application Default Credentials (service account, `gcloud auth`).

### Basic Usage

Place URIs in any string field of `dblift.yaml`:

```yaml
database:
  url: "postgresql+psycopg://prod-host:5432/mydb"
  username: "myuser"
  password: "vault://secret/data/myapp/db#password"

migrations:
  directory: "./migrations"
```

### Provider Configuration

Optionally configure provider settings in a `secrets:` block. All fields are
optional — providers fall back to environment variables and ambient credentials
when omitted.

```yaml
secrets:
  cache_ttl_seconds: 300   # How long to cache resolved values (default: 60)

  vault:
    url: "https://vault.example.com"     # or VAULT_ADDR env var
    token: "s.xxxx"                      # or VAULT_TOKEN env var
    namespace: "my-namespace"            # or VAULT_NAMESPACE env var

  aws:
    region: "us-east-1"                  # or AWS_DEFAULT_REGION env var

  azure:
    vault_name: "myvault"                # or use full host in URI

  gcp:
    project_id: "my-gcp-project"         # or inferred from ADC
```

The provider credentials themselves can be secret URIs (bootstrap chaining):

```yaml
secrets:
  vault:
    token: "aws-secrets://prod/vault-bootstrap-token"
```

DBLift resolves the `secrets:` block first (using ambient credentials), then
uses the bootstrapped config to resolve the rest of the file.

### Caching

Resolved secrets are cached in process memory for `cache_ttl_seconds` (default
60 seconds). The cache key includes the URI plus all provider-specific auth
fields so different configs never share a cached value. Call
`config.secrets.clear_cache()` or restart the process to force fresh resolution.

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
secret. Each provider solves it differently.

#### Cloud providers — let the platform carry it

AWS, Azure, and GCP each offer a platform-managed identity that requires no
credential to be stored anywhere:

| Platform | Mechanism | What to do |
|---|---|---|
| AWS | IAM role (EC2/ECS/EKS instance profile, Lambda execution role, IRSA) | Attach a role to the compute resource; `boto3` picks it up automatically via the instance metadata service |
| Azure | Managed Identity (system-assigned or user-assigned) | Enable managed identity on the VM/App Service/Container App; `DefaultAzureCredential` picks it up |
| GCP | Service account attached to instance / Workload Identity | Attach a service account to the GCE instance or use Workload Identity for GKE |

With any of these, there is no secret zero — the platform authenticates the
workload at the infrastructure level. No credential appears in `dblift.yaml`,
environment variables, or CI pipelines.

#### HashiCorp Vault — use platform-native auth methods

Vault's token auth is the most common cause of secret zero problems. Prefer
one of Vault's platform-native auth methods that accept the platform identity
as proof:

| Environment | Vault auth method | How it works |
|---|---|---|
| AWS EC2 / ECS | `aws` auth method | Vault verifies the signed instance identity document from the AWS metadata service |
| Kubernetes | `kubernetes` auth method | Vault verifies the pod's service account JWT projected by the kubelet |
| Azure VM / AKS | `azure` auth method | Vault verifies the Azure MSI token |
| GCP GCE / GKE | `gcp` auth method | Vault verifies the instance identity token or GKE service account JWT |
| CI/CD (GitHub Actions) | `jwt`/`oidc` auth method | Vault verifies the GitHub OIDC token issued per workflow run |

With these methods the Vault token is obtained at runtime and never stored.
If you must use Vault token auth (e.g. during a migration period), inject
it via the `VAULT_TOKEN` environment variable rather than writing it to
`dblift.yaml`.

#### Bootstrap chaining

When Vault token auth is unavoidable but the token lives in another provider
you can already access (e.g. an AWS IAM role lets you read from Secrets
Manager), use bootstrap chaining to avoid writing the token to disk:

```yaml
secrets:
  vault:
    token: "aws-secrets://prod/vault-bootstrap-token"
  aws:
    region: "us-east-1"
```

dblift resolves the `secrets:` block first using ambient AWS credentials, then
uses the resolved Vault token for the rest of the config. The token never
appears in a file.

#### CI/CD pipelines

Never inject secrets manager credentials via `dblift.yaml` checked into
source control. Use the CI platform's native secret store instead:

- **GitHub Actions**: `secrets.MY_SECRET` → environment variable in the workflow step
- **GitLab CI**: masked CI/CD variables → environment variable
- **Jenkins**: credentials binding plugin → environment variable
- **Terraform / Helm**: pass via `-var` or `--set`, not in committed values files

The recommended pattern for CI is:

```yaml
# dblift.yaml (committed — no credentials)
database:
  password: "aws-secrets://prod/db#password"

secrets:
  aws:
    region: "us-east-1"
  # No aws.access_key — rely on OIDC / instance role in CI
```

```yaml
# GitHub Actions workflow
- name: Run dblift migrate
  env:
    AWS_ROLE_ARN: ${{ vars.AWS_ROLE_ARN }}
  run: dblift migrate ...
```

## Next Steps

- Learn about **[Commands](commands.md)** to use DBLift effectively
- Check out **[Best Practices](best-practices.md)** for configuration tips
- See **[Troubleshooting](troubleshooting.md)** if you encounter issues

# NoSQL (Cosmos DB) Python Migrations

Azure Cosmos DB migrations are Python scripts. DBLift does not accept `.sql`
migrations for the `cosmosdb` dialect, and there is no pseudo-SQL layer that
turns statements like `DROP CONTAINER` into SDK calls.

!!! warning "Breaking change"
    The Cosmos DB pseudo-SQL statements (`DROP CONTAINER`, `SET THROUGHPUT`,
    `CREATE INDEX`, `SET TTL`, …) were removed with no deprecation window and
    no compatibility mode. See [Upgrading from pseudo-SQL](#upgrading-from-pseudo-sql).

## Why Python and not SQL

Cosmos DB has no DDL. Containers, throughput, indexing policy and TTL are
account-plane resources that only the Azure SDK can change, and documents are
written through the item APIs. The Cosmos DB SQL API is a *query* language: it
reads, it does not write.

DBLift therefore drives Cosmos through `azure-cosmos` directly from your
migration script instead of inventing a SQL-looking syntax for it. What you
write is what runs — no translation layer, no generated SDK code to review.

Because your migration calls the SDK itself, the SDK has to be installed. It
ships in the `cosmosdb` extra, like every other engine's driver:

```bash
pip install "dblift[cosmosdb]"
```

Two consequences:

- A `.sql` migration targeting Cosmos DB fails with
  [`DBLIFT-NOSQL-001`](#dblift-nosql-001-sql-migration-on-a-nosql-dialect).
- A write statement (`INSERT`, `UPDATE`, `DELETE`, `CREATE …`) reaching
  `context.execute()` raises `NoSqlWriteNotSupportedError`. Only native Cosmos
  `SELECT` executes.

## Migration files

Naming is identical to SQL migrations — only the extension changes:

```
migrations/
├── V1_0_0__create_users_container.py     # versioned
├── U1_0_0__drop_users_container.py       # undo companion (optional)
├── V1_1_0__users_indexing_policy.py
└── R__seed_reference_data.py             # repeatable
```

- `V<version>__<description>.py` — versioned, applied once in version order.
- `U<version>__<description>.py` — undo companion for the matching version.
- `R__<description>.py` — repeatable, re-applied whenever its checksum changes.

Ordering, checksums, history recording, `--dry-run`, tags and multiple
migration directories all behave exactly as they do for `.sql` migrations.

## The migration contract

Each file defines a top-level `migrate` function taking one argument. An
`undo` function with the same signature is optional and is what `dblift undo`
runs from the `U…` file.

```python
from api import MigrationContext


def migrate(context: MigrationContext) -> None:
    ...


def undo(context: MigrationContext) -> None:
    ...
```

### Context attributes

| Attribute | Type | What it is |
|---|---|---|
| `context.db` | `azure.cosmos.DatabaseProxy` | The configured database. Container create/replace/delete and `get_container_client()` live here. |
| `context.raw_client` | `azure.cosmos.CosmosClient` | The account-level client, for anything above the database (database management, account properties). |
| `context.log` | logger | `.debug()`, `.info()`, `.warning()`, `.error()`. |
| `context.dry_run` | `bool` | `True` under `--dry-run`. Your script must not write when it is set. |
| `context.execute(sql)` | callable | Runs a **native Cosmos `SELECT`** and returns the documents. Any write statement raises `NoSqlWriteNotSupportedError`. |
| `context.schema` | `str \| None` | Target schema from config. Cosmos is schemaless; present for parity. |
| `context.placeholders` | `Mapping[str, str]` | Effective placeholder values: `dblift_*` system placeholders, then config, then `--placeholders` / `migrate(placeholders=...)`. No automatic substitution happens — read them yourself. |

!!! note "`dry_run` is yours to honor"
    DBLift cannot intercept SDK calls you make directly, so nothing stops a
    script from writing during a dry run. Guard every mutation with
    `if context.dry_run: return` (or the per-operation form shown below).

## Converting pseudo-SQL to SDK calls

There is no conversion tool. Rewrite each removed statement by hand using the
table below; `container = context.db.get_container_client("<name>")` is assumed
where a container client is used.

| Removed pseudo-SQL | Equivalent inside `migrate(context)` |
|---|---|
| `CREATE CONTAINER c (...)` / `CREATE TABLE c (...)` | `context.db.create_container(id="c", partition_key=PartitionKey(path="/tenant_id"))` |
| `DROP CONTAINER c` | `context.db.delete_container("c")` |
| `ALTER CONTAINER c SET (...)` | Read `container.read()`, change the properties you need, then `context.db.replace_container(container, partition_key=PartitionKey(path=...), indexing_policy=..., default_ttl=...)` |
| `SET THROUGHPUT ON CONTAINER c TO 800` | `container.replace_throughput(800)` |
| `SET AUTOSCALE ON CONTAINER c MAX 4000` | `container.replace_throughput(ThroughputProperties(auto_scale_max_throughput=4000))` |
| `SET AUTOSCALE ON CONTAINER c MAX 4000 MIN 400` | Same call — Cosmos derives the autoscale floor as 10% of the maximum. There is no separate minimum to set; drop the `MIN` clause. |
| `SHOW THROUGHPUT ON CONTAINER c` | `container.get_throughput()` (`container.read_offer()` on older `azure-cosmos` releases) |
| `CREATE INDEX ix ON c (path)` | Add the path to `indexing_policy["includedPaths"]` and call `context.db.replace_container(...)` |
| `DROP INDEX ix ON c` | Remove the path from `indexing_policy["includedPaths"]` (or add it to `excludedPaths`) and call `context.db.replace_container(...)` |
| `INCLUDE INDEX PATH '/a/?' ON CONTAINER c` | `indexing_policy["includedPaths"].append({"path": "/a/?"})` + `replace_container(...)` |
| `EXCLUDE INDEX PATH '/blob/*' ON CONTAINER c` | `indexing_policy["excludedPaths"].append({"path": "/blob/*"})` + `replace_container(...)` |
| `SET TTL ON CONTAINER c TO 3600` | `context.db.replace_container(container, partition_key=..., default_ttl=3600)` |
| `SET TTL ON CONTAINER c TO OFF` | Same call with `default_ttl=None` (use `-1` to keep TTL enabled with no default expiry) |
| `INSERT INTO c ...` | `container.create_item(body={...})` or `container.upsert_item(body={...})` |
| `UPDATE c SET ...` | `container.replace_item(item=doc["id"], body=doc)` (or `upsert_item`) |
| `DELETE FROM c WHERE ...` | `container.delete_item(item=doc["id"], partition_key=doc["tenant_id"])` |
| `SELECT ...` | Unchanged — `context.execute("SELECT * FROM c")` |

Indexing policy, partition key and TTL travel together: `replace_container()`
replaces the container definition, so read the current properties first and
pass back everything you intend to keep.

!!! note "Check kwarg names against your pinned SDK"
    `azure-cosmos` has renamed throughput arguments across releases. Verify the
    signatures above against the version in your `requirements.txt` before
    shipping a migration.

## Example: create a container

`migrations/V1_0_0__create_users_container.py`:

```python
from azure.cosmos import PartitionKey

from api import MigrationContext

CONTAINER = "users"
PARTITION_KEY = "/tenant_id"


def migrate(context: MigrationContext) -> None:
    if context.dry_run:
        context.log.info(
            f"[DRY-RUN] would create container '{CONTAINER}' "
            f"(partition key {PARTITION_KEY}, 400 RU/s)"
        )
        return

    context.db.create_container(
        id=CONTAINER,
        partition_key=PartitionKey(path=PARTITION_KEY),
        offer_throughput=400,
    )
    context.log.info(f"Created container '{CONTAINER}'")


def undo(context: MigrationContext) -> None:
    if context.dry_run:
        context.log.info(f"[DRY-RUN] would delete container '{CONTAINER}'")
        return

    context.db.delete_container(CONTAINER)
    context.log.info(f"Deleted container '{CONTAINER}'")
```

## Example: indexing policy and TTL

`migrations/V1_1_0__users_indexing_policy.py`:

```python
from azure.cosmos import PartitionKey

from api import MigrationContext

CONTAINER = "users"
EXCLUDED_PATH = "/profile_blob/*"
TTL_SECONDS = 2592000  # 30 days


def migrate(context: MigrationContext) -> None:
    container = context.db.get_container_client(CONTAINER)
    properties = container.read()

    indexing_policy = properties["indexingPolicy"]
    excluded = indexing_policy.setdefault("excludedPaths", [])
    if not any(entry.get("path") == EXCLUDED_PATH for entry in excluded):
        excluded.append({"path": EXCLUDED_PATH})

    if context.dry_run:
        context.log.info(
            f"[DRY-RUN] would exclude '{EXCLUDED_PATH}' from indexing on "
            f"'{CONTAINER}' and set TTL to {TTL_SECONDS}s"
        )
        return

    context.db.replace_container(
        container,
        partition_key=PartitionKey(path=properties["partitionKey"]["paths"][0]),
        indexing_policy=indexing_policy,
        default_ttl=TTL_SECONDS,
    )
    context.log.info(f"Updated indexing policy and TTL on '{CONTAINER}'")


def undo(context: MigrationContext) -> None:
    container = context.db.get_container_client(CONTAINER)
    properties = container.read()

    indexing_policy = properties["indexingPolicy"]
    indexing_policy["excludedPaths"] = [
        entry
        for entry in indexing_policy.get("excludedPaths", [])
        if entry.get("path") != EXCLUDED_PATH
    ]

    if context.dry_run:
        context.log.info(f"[DRY-RUN] would restore indexing and TTL on '{CONTAINER}'")
        return

    context.db.replace_container(
        container,
        partition_key=PartitionKey(path=properties["partitionKey"]["paths"][0]),
        indexing_policy=indexing_policy,
        default_ttl=None,
    )
    context.log.info(f"Restored indexing policy and disabled TTL on '{CONTAINER}'")
```

## Reading data

`context.execute()` still runs native Cosmos SQL, which is useful for
conditional seeding:

```python
def migrate(context: MigrationContext) -> None:
    existing = context.execute("SELECT c.id FROM c WHERE c.kind = 'currency'")
    if existing:
        context.log.info("Reference data already present")
        return
    ...
```

Cross-partition behavior, `TOP`/`OFFSET` limits and RU cost are the Cosmos
query engine's, unchanged by DBLift.

## `DBLIFT-NOSQL-001`: SQL migration on a NoSQL dialect

```
DBLIFT-NOSQL-001: 'V1_0_0__create_users.sql' is a SQL migration, but the
'cosmosdb' dialect does not execute SQL migrations.
```

**Trigger**: a `.sql` file in your migrations directory was selected for a
Cosmos DB target. The error is raised by
`core.exceptions.UnsupportedMigrationFormatError` before anything executes, so
no partial change is applied.

**Fix**: rewrite the migration as `.py` with the same version and description,
using the [conversion table](#converting-pseudo-sql-to-sdk-calls), and delete
the `.sql` file. Keep the version identical if the migration has not been
applied anywhere yet; use a new version if it has already run in an
environment you cannot re-run.

The related runtime error `NoSqlWriteNotSupportedError` means the opposite
direction: a Python migration passed a write statement to
`context.execute()`. Replace that call with the equivalent SDK call.

## Upgrading from pseudo-SQL

This is a breaking change. There is no compatibility mode, no flag to restore
the old behavior, and no automatic converter — conversion is manual.

**Already-applied migrations are unaffected.** History rows written by
previously applied `.sql` Cosmos migrations remain valid, their checksums are
untouched, and `dblift info` / `dblift validate` keep reporting them as
applied. You do **not** need `dblift repair` and you do **not** need to
re-baseline. The cutover applies to migrations you write from now on, and to
any pending `.sql` migration that has not been applied yet.

What to do:

1. Find pending `.sql` migrations pointed at Cosmos DB — anything not listed as
   applied by `dblift info`. Rewrite them as `.py`.
2. Leave applied `.sql` files in place. They are still checksummed against
   history; deleting or editing them is what breaks validation, not the
   cutover.
3. Update existing `.py` Cosmos migrations for the context rename below.

### `context.database` / `context.client` renamed

The context attributes were renamed in the same release, with no aliases:

| Old | New |
|---|---|
| `context.database` | `context.db` |
| `context.client` | `context.raw_client` |

Existing Python Cosmos migrations that use the old names raise
`AttributeError`. Since only unapplied migrations execute, this affects
scripts you are about to run and any repeatable (`R__`) migration — update
them before the next `dblift migrate`.

## Next Steps

- **[Configuration](configuration.md#cosmosdb-configuration)** — account endpoint, key, and emulator settings
- **[Python migrations](../examples/python-migrations.md)** — the general `.py` migration API, shared with relational dialects
- **[Troubleshooting](troubleshooting.md)** — connection and execution problems

# SQLAlchemy Integration

Use `DBLiftClient.from_sqlalchemy` when your application already owns a
SQLAlchemy `Engine` or `Connection`.

```python
from sqlalchemy import create_engine

from dblift.api import DBLiftClient

engine = create_engine("postgresql+psycopg://user:password@localhost/app")

with DBLiftClient.from_sqlalchemy(
    engine=engine,
    migrations_dir="migrations",
) as client:
    client.validate()
    client.migrate()
```

## Engine Or Connection

Pass an engine:

```python
client = DBLiftClient.from_sqlalchemy(
    engine=engine,
    migrations_dir="migrations",
)
```

Or pass a live connection:

```python
with engine.connect() as connection:
    client = DBLiftClient.from_sqlalchemy(
        connection=connection,
        migrations_dir="migrations",
    )
    client.migrate()
    client.close()
```

Do not pass both `engine=` and `connection=` in the same call.

## Ownership Rules

When you provide an external engine or connection, DBLift does not own it.
Calling `client.close()` releases DBLift resources but does not dispose your
engine or close your externally supplied connection. Your application remains
responsible for its normal SQLAlchemy lifecycle.

## MySQL and MariaDB Engines

A migration unit that holds several statements (for example `INSERT ...; INSERT ...`
under `DELIMITER //`) runs as one query, as the `mysql` client runs it. On an engine
DBLift builds, multi-statements are enabled. On an engine you pass in, enable them
yourself if your scripts rely on it:
`create_engine(url, connect_args={"client_flag": CLIENT.MULTI_STATEMENTS | CLIENT.FOUND_ROWS})`
with `CLIENT` from `pymysql.constants`.

## Read-Only Status Checks

Use `info()` for startup guards, health endpoints, and deployment checks:

```python
with DBLiftClient.from_sqlalchemy(engine=engine, migrations_dir="migrations") as client:
    info = client.info()
    pending = getattr(info, "pending_migrations", []) or []
```

`info()` does not apply migrations.

## Python Migrations

Python migration files receive a `MigrationContext` with access to the active
engine, connection, schema, config, placeholders, logger, and `execute` helper:

```python
from dblift.api import MigrationContext


def migrate(context: MigrationContext) -> None:
    context.execute("CREATE TABLE app_users (id INTEGER PRIMARY KEY)")
```

## Sync-Only Limitation

The current integration accepts synchronous SQLAlchemy `Engine` and
`Connection` objects. For async applications, use a sync engine for migration
work or wrap DBLift calls with `AsyncDBLiftClient`.

See [SQLAlchemy Integration Example](../examples/sqlalchemy-integration.md) for
a complete runnable script.

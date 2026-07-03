# How to Write and Apply Your First Migration

This recipe assumes DBLift is already installed (see
[Getting Started](../user-guide/getting-started.md)). Activate a license first
when using the commercial distribution. You also need database connection
details on hand.

## 1. Configure your database connection

Create `dblift.yaml` in your project root:

```yaml
database:
  url: "postgresql+psycopg://localhost:5432/mydb"
  schema: "public"
  username: "myuser"
  password: "mypassword"

migrations:
  directory: "./migrations"
```

Replace the `database` values with your own connection details. See the
[Configuration Guide](../user-guide/configuration.md) for the connection
format and required keys for each supported dialect.

## 2. Create the migrations directory

```bash
mkdir migrations
```

## 3. Write a versioned migration file

Create `migrations/V1_0_0__create_users_table.sql`:

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE
);
```

The filename format is `V<version>__<description>.sql`:

- `V` marks it as a versioned migration (runs once, in order)
- `1_0_0` is the version number
- everything after the `__` separator is a free-text description

## 4. Apply the migration

```bash
dblift migrate
```

DBLift creates the `users` table and records the migration as applied, so
running `dblift migrate` again is a no-op.

## Next steps

- [Configuration Guide](../user-guide/configuration.md) — all configuration options
- [Commands Reference](../user-guide/commands.md) — full command list
- [Best Practices](../user-guide/best-practices.md) — tips for effective migrations

# Django External Databases

DBLift works the same whether the main application uses the Django ORM or not. Use `DBLiftClient.from_sqlalchemy` for any database or schema that lives outside Django's model and migration system (configured via a second `DATABASES` entry that Django's `migrate` command does not own).

## Use Cases

- **Data warehouses / analytics databases** — separate read-optimized stores with their own schema lifecycle, often populated by ETL.
- **Legacy schemas** — pre-existing databases whose structure is not (or not fully) expressed as Django models.
- **Multi-database setups** — applications declaring several `DATABASES` aliases where only a subset are managed by Django models and `manage.py migrate`.
- **Non-Django-managed schemas** — any schema (even on the same host) whose tables, views, or objects are deliberately kept outside Django's migration framework and model layer.

## Integration Pattern

Declare the external database as a second entry in `DATABASES`. Django will be aware of the alias but will not manage its schema via the ORM unless you explicitly point `makemigrations` / `migrate` at it.

```python
# settings.py (excerpt)
DATABASES = {
    "default": {
        # Django ORM + makemigrations / migrate managed database
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "app_db",
        # ...
    },
    "external": {
        # NOT managed by Django migrations. Use DBLift here.
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "warehouse",
        "USER": os.environ["WAREHOUSE_USER"],
        "PASSWORD": os.environ["WAREHOUSE_PASSWORD"],
        "HOST": os.environ.get("WAREHOUSE_HOST", "localhost"),
        "PORT": os.environ.get("WAREHOUSE_PORT", "5432"),
    },
}
```

In a script, custom management command, or deploy step, construct a SQLAlchemy `Engine` for the external alias (re-using the same credentials) and hand it to `DBLiftClient.from_sqlalchemy`. Migrations for this database live in a `migrations_dir` you control with plain SQL or Python files.

```python
from sqlalchemy import create_engine
from django.conf import settings

from api import DBLiftClient

# Build (or obtain) an engine for the non-Django alias only.
# Keep credential handling consistent with how you configure Django.
ext = settings.DATABASES["external"]
engine = create_engine(
    f"postgresql+psycopg://{ext['USER']}:{ext['PASSWORD']}@"
    f"{ext['HOST']}:{ext['PORT']}/{ext['NAME']}"
)

migrations_dir = "migrations/external"  # your DBLift migration scripts for this DB

# from_sqlalchemy re-uses your engine; it does not take ownership.
with DBLiftClient.from_sqlalchemy(
    engine=engine, migrations_dir=migrations_dir
) as client:
    # Read-only guard / health use:
    # info = client.info()
    # if info.pending_count: ...

    result = client.migrate()
```

**Engine ownership, `migrations_dir`, and `close` semantics**
- The `engine` (and its pool / lifecycle) remains yours. `client.close()` or exiting the `with` block never calls `engine.dispose()`.
- `migrations_dir` (string, Path, or list) is independent of Django's migration directories and of any `MIGRATION_MODULES` settings.
- You may also pass a live `connection=` (SQLAlchemy `Connection`) when you need the migration to participate in an existing transaction.
- The client and `MigrationContext` (when using `.py` migrations) expose `context.engine` / `context.connection` pointing back at what you supplied.

The same `from_sqlalchemy` call works in plain Python, pytest, FastAPI lifespans, Flask, or here — the client surface is framework-agnostic.

## Non-goals

This guide is **positioning only**. DBLift does not replace Django's migration tooling for Django-managed databases.

- **Do not** point DBLift (or the pattern above) at the `'default'` alias or any alias whose schema is defined by Django models and applied with `python manage.py makemigrations` / `migrate` (or `migrate --database=...`).
- DBLift has zero knowledge of Django models, the Django migration autodetector, `django.db.migrations`, or the `django_migrations` table. It cannot generate, detect, or apply Django migration files.
- If you have chosen to manage a schema with Django, keep using Django's commands for it. Mixing the two systems on the same objects is your responsibility to avoid.
- This manual `from_sqlalchemy` pattern is an **alternative** to the built-in `integrations.django` package, which ships `dblift_migrate` / `dblift_info` / `dblift_validate` management commands plus a system check for pending migrations. Reach for the pattern above when you want the external database wired up by hand instead of through those commands.

Use DBLift where you have already decided the schema lives outside Django's migration system. Keep the two tools in their respective lanes.
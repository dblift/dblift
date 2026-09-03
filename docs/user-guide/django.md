# Django integration

dblift ships a Django app exposing migration commands and a pending-migrations
system check. It **complements** Django's ORM migrations: use it for raw SQL,
multiple or heterogeneous databases, cross-dialect work, and rollback. dblift
keeps its own history table and never touches `django_migrations`.

## Setup

```bash
pip install "dblift[django]"
```

```python
# settings.py
INSTALLED_APPS = [
    # ...
    "dblift.integrations.django",
]

DBLIFT_MIGRATIONS_DIR = BASE_DIR / "migrations"

# Optional:
# DBLIFT_DATABASE_ALIAS = "default"
# DBLIFT_DATABASE_URL = "postgresql+psycopg://user:pass@host/db"
```

The DB connection is read from `settings.DATABASES[DBLIFT_DATABASE_ALIAS]`.
PostgreSQL, MySQL, SQLite, Oracle, and SQL Server backends are mapped directly.
Set `DBLIFT_DATABASE_URL` to bypass mapping for another backend.

## Commands

```bash
python manage.py dblift_migrate
python manage.py dblift_validate
python manage.py dblift_info
```

`dblift_migrate` applies pending dblift migrations. `dblift_validate` checks
checksums, order, and applied state. `dblift_info` prints current pending status.

## System check

`manage.py check` and `runserver` emit warning `dblift.W001` when dblift
migrations are pending. The check is non-blocking and returns no messages when
the DB is unreachable or configuration is incomplete.

To make stale schema state fail deployment, run `python manage.py dblift_migrate`
as a deploy step or register your own Django check that escalates `dblift.W001`
to an error.

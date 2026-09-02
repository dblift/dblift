"""Build a DBLiftClient from Django settings."""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

from dblift.api import DBLiftClient

from ._engine import build_url

_ENGINES: dict[tuple[str, str, str], Engine] = {}


def _url_cache_key(url: object, migrations_dir: str) -> tuple[str, str, str]:
    return ("url", str(url), migrations_dir)


def _database_cache_key(db: dict[str, object], migrations_dir: str) -> tuple[str, str, str]:
    url = build_url(db)
    return ("database", url.render_as_string(hide_password=False), migrations_dir)


def _engine_for_key(key: tuple[str, str, str], url: str | URL) -> Engine:
    engine = _ENGINES.get(key)
    if engine is None:
        engine = create_engine(url)
        _ENGINES[key] = engine
    return engine


def get_client() -> DBLiftClient:
    """Construct a DBLiftClient from Django settings."""
    migrations_dir = getattr(settings, "DBLIFT_MIGRATIONS_DIR", None)
    if not migrations_dir:
        raise ImproperlyConfigured("dblift: set DBLIFT_MIGRATIONS_DIR in settings.")

    url = getattr(settings, "DBLIFT_DATABASE_URL", None)
    if url:
        migrations_dir_str = str(migrations_dir)
        engine = _engine_for_key(_url_cache_key(url, migrations_dir_str), str(url))
    else:
        alias = getattr(settings, "DBLIFT_DATABASE_ALIAS", "default")
        databases = getattr(settings, "DATABASES", {})
        if alias not in databases:
            raise ImproperlyConfigured(f"dblift: DATABASES['{alias}'] not found.")
        migrations_dir_str = str(migrations_dir)
        db = databases[alias]
        key = _database_cache_key(db, migrations_dir_str)
        engine = _engine_for_key(key, build_url(db))

    return DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations_dir_str)

"""Django DATABASES -> SQLAlchemy URL mapping."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from dblift.integrations.django._engine import build_url


def test_postgresql_mapping():
    url = build_url(
        {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "app",
            "USER": "u",
            "PASSWORD": "p",
            "HOST": "localhost",
            "PORT": "5432",
        }
    )
    assert url.drivername == "postgresql+psycopg"
    assert url.database == "app"
    assert url.host == "localhost"
    assert url.port == 5432


def test_sqlite_mapping():
    url = build_url({"ENGINE": "django.db.backends.sqlite3", "NAME": "/tmp/x.db"})
    assert url.drivername == "sqlite"
    assert url.database == "/tmp/x.db"


def test_mssql_backend_mapping():
    url = build_url({"ENGINE": "mssql", "NAME": "app", "HOST": "h"})
    assert url.drivername == "mssql+pymssql"


def test_unknown_backend_raises():
    with pytest.raises(ImproperlyConfigured):
        build_url({"ENGINE": "django.db.backends.cockroach", "NAME": "x"})

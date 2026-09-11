"""The assembled MongoDB URI must name the database, or auth goes to ``admin``.

``host``/``port``/``database``/``username``/``password`` is a documented config
shape. It assembled ``mongodb://user:pass@host:port`` with no database path, so
pymongo defaulted ``authSource`` to ``admin`` and a user created in the
application database — the ordinary way to create one — failed to authenticate.
"""

from __future__ import annotations

import pytest

from dblift.config import DatabaseConfig


def _cfg(**overrides):
    kwargs = dict(
        type="mongodb",
        host="localhost",
        port=27017,
        database="dblift_test",
        username="dblift_test",
        password="dblift_test",
    )
    kwargs.update(overrides)
    return DatabaseConfig(**kwargs)


@pytest.mark.unit
def test_assembled_uri_carries_the_database_as_the_auth_source():
    assert _cfg().build_connection_string() == (
        "mongodb://dblift_test:dblift_test@localhost:27017/dblift_test"
    )


@pytest.mark.unit
def test_assembled_uri_carries_the_database_without_credentials():
    """No credentials still means the driver should land on the right database."""
    assert _cfg(username=None, password=None).build_connection_string() == (
        "mongodb://localhost:27017/dblift_test"
    )


@pytest.mark.unit
def test_database_name_is_percent_encoded_like_the_credentials():
    assert "/db%20name" in _cfg(database="db name").build_connection_string()


@pytest.mark.unit
def test_an_explicit_url_is_returned_untouched():
    """``url`` wins and carries its own auth source; we must not rewrite it."""
    url = "mongodb+srv://u:p@cluster.example.mongodb.net/?authSource=admin"
    assert _cfg(url=url).build_connection_string() == url


@pytest.mark.unit
def test_masked_url_still_hides_the_password_with_a_database_path():
    masked = _cfg().build_database_url()
    assert masked == "mongodb://dblift_test:***@localhost:27017/dblift_test"
    assert "dblift_test:dblift_test" not in masked

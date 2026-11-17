"""How ``ConfigBuilder.build`` turns keyword overrides into raw config data.

The raw data handed to ``ConfigBuilder.from_dict`` is captured, so these tests pin the mapping
itself rather than what a particular database config class keeps of it.
"""

import os

import pytest

from dblift.config.config_builder import ConfigBuilder

pytestmark = pytest.mark.unit


@pytest.fixture
def raw_config(monkeypatch):
    """Capture the raw data ``build`` passes to ``from_dict``; no DBLIFT_* variable leaks in."""
    for name in list(os.environ):
        if name.startswith("DBLIFT"):
            monkeypatch.delenv(name)
    seen = {}

    def capture(cls, config_dict):
        seen["data"] = config_dict
        return object()

    monkeypatch.setattr(ConfigBuilder, "from_dict", classmethod(capture))
    return seen


@pytest.mark.parametrize(
    "keyword, field",
    [
        ("db_username", "username"),
        ("database_password", "password"),
        ("db_schema", "schema"),
        ("database_type", "type"),
        ("db_type", "type"),
        ("account_endpoint", "account_endpoint"),
    ],
)
def test_a_connection_keyword_alone_starts_the_database_section(raw_config, keyword, field):
    """Without a URL keyword, the first connection keyword creates the database section."""
    ConfigBuilder.build(env_overrides=False, **{keyword: "value"})

    assert raw_config["data"] == {"database": {field: "value"}}


def test_a_database_type_joins_the_url_in_the_same_section(raw_config):
    """A later connection keyword adds to the database section the URL keyword started."""
    ConfigBuilder.build(
        env_overrides=False, db_url="postgresql+psycopg://u:p@h/db", database_type="postgresql"
    )

    assert raw_config["data"] == {
        "database": {"url": "postgresql+psycopg://u:p@h/db", "type": "postgresql"}
    }


def test_an_empty_database_type_falls_back_to_db_type(raw_config):
    """``database_type`` wins over ``db_type`` only when it is truthy."""
    ConfigBuilder.build(env_overrides=False, database_type="", db_type="mysql")

    assert raw_config["data"] == {"database": {"type": "mysql"}}


def test_service_keywords_are_nested_under_database_in_order(raw_config):
    """Account, container and identity keywords join the URL inside the database section."""
    ConfigBuilder.build(
        env_overrides=False,
        use_managed_identity=True,
        account_key="key==",
        db_url="postgresql+psycopg://u:p@h/db",
        container_name="items",
        database="main",
        database_name="appdb",
        account_endpoint="https://account.example",
    )

    database = raw_config["data"]["database"]
    assert database == {
        "url": "postgresql+psycopg://u:p@h/db",
        "account_endpoint": "https://account.example",
        "account_key": "key==",
        "database": "main",
        "database_name": "appdb",
        "container_name": "items",
        "use_managed_identity": True,
    }
    assert list(database) == [
        "url",
        "account_endpoint",
        "account_key",
        "database",
        "database_name",
        "container_name",
        "use_managed_identity",
    ]

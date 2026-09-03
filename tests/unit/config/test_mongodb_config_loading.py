"""``MongoDbConfig`` — URI-first, host/port fallback.

Every MongoDB option is a URI query parameter, so the config carries no
tls / replica_set / auth_source fields: a URI is the one place to put them.
"""

import pytest

from dblift.db.plugins.mongodb.config import MongoDbConfig


def test_url_form_is_accepted():
    config = MongoDbConfig(
        type="mongodb",
        url="mongodb://localhost:27017",
        database="appdb",
    )
    assert config.build_connection_string() == "mongodb://localhost:27017"


def test_host_port_form_builds_a_uri():
    config = MongoDbConfig(
        type="mongodb",
        host="localhost",
        port=27017,
        username="app",
        password="s3cret",
        database="appdb",
    )
    assert config.build_connection_string() == "mongodb://app:s3cret@localhost:27017"


def test_host_form_without_credentials():
    config = MongoDbConfig(type="mongodb", host="localhost", port=27017, database="appdb")
    assert config.build_connection_string() == "mongodb://localhost:27017"


def test_port_defaults_to_27017():
    config = MongoDbConfig(type="mongodb", host="localhost", database="appdb")
    assert config.build_connection_string() == "mongodb://localhost:27017"


def test_url_wins_over_host():
    config = MongoDbConfig(
        type="mongodb",
        url="mongodb+srv://cluster0.example.net",
        host="ignored",
        port=1234,
        database="appdb",
    )
    assert config.build_connection_string() == "mongodb+srv://cluster0.example.net"


def test_database_is_required():
    with pytest.raises(ValueError, match="database"):
        MongoDbConfig(type="mongodb", url="mongodb://localhost:27017")


def test_host_or_url_is_required():
    with pytest.raises(ValueError, match="Either url or host"):
        MongoDbConfig(type="mongodb", database="appdb")


def test_display_url_masks_the_password():
    config = MongoDbConfig(
        type="mongodb",
        url="mongodb://app:s3cret@localhost:27017",
        database="appdb",
    )
    assert "s3cret" not in config.build_database_url()
    assert "***" in config.build_database_url()


def test_display_url_masks_password_from_host_form():
    config = MongoDbConfig(
        type="mongodb", host="h", port=27017, username="app", password="s3cret", database="appdb"
    )
    assert "s3cret" not in config.build_database_url()


def test_repr_does_not_leak_the_password():
    """BaseDatabaseConfig.__repr__ is credential-masked; the dataclass
    decorator must not regenerate it."""
    config = MongoDbConfig(
        type="mongodb", host="h", username="app", password="s3cret", database="appdb"
    )
    assert "s3cret" not in repr(config)


def test_connection_props_expose_database_and_uri():
    config = MongoDbConfig(type="mongodb", url="mongodb://localhost:27017", database="appdb")
    props = config.get_connection_props()
    assert props["database"] == "appdb"
    assert props["uri"] == "mongodb://localhost:27017"


def test_registered_under_its_type_name():
    from dblift.config.database_config import BaseDatabaseConfig

    assert BaseDatabaseConfig._registry["mongodb"] is MongoDbConfig

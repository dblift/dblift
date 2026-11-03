"""The SQLite URL builder names, through SQLAlchemy's own reading, the file it was given."""

import pytest
from sqlalchemy.engine import make_url

from dblift.db.plugins.sqlite.sqlalchemy_url import build_sqlalchemy_url

pytestmark = pytest.mark.unit


def _config(**fields):
    return type("_C", (), {"url": None, "path": None, "database": None, **fields})()


@pytest.mark.parametrize(
    "target",
    ["/t/h#ash/x.db", "/t/a%20b/x.db", "/t/p%23q/x.db", "/t/a b/x.db", "/t/db:2024.db", "x.db"],
)
@pytest.mark.parametrize("attr", ["path", "database"])
def test_built_url_names_the_configured_file(attr, target):
    built = make_url(build_sqlalchemy_url(_config(**{attr: target})))
    assert (built.drivername, built.database, dict(built.query)) == ("sqlite", target, {})


def test_built_url_keeps_a_query_the_user_wrote():
    built = make_url(build_sqlalchemy_url(_config(path="/t/a%20b/x.db?mode=ro")))
    assert (built.database, dict(built.query)) == ("/t/a%20b/x.db", {"mode": "ro"})


def test_memory_and_raw_url():
    assert build_sqlalchemy_url(_config(path=":memory:")) == "sqlite:///:memory:"
    assert build_sqlalchemy_url(_config(url="sqlite:///x.db?mode=ro")) == "sqlite:///x.db?mode=ro"

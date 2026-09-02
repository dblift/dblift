"""URL → database.type inference — the pattern behind 4+ recent bugs (P6).

When ``--db-url`` is passed without ``--db-type``, or when a config file
declares ``type: sqlserver`` but ``--db-url sqlite:///…`` overrides it, the
final ``config.database.type`` must match the URL, not the default.

Bugs this guards against:
  * 3a8a6a44 — SqlServerConfig.__post_init__ reset type on sqlite URL override
  * 6f52c797 — guard against None db_type on refresh after URL parsing
  * 77f6768b — refresh db_type after URL parsing
  * c92a0e90 BUG-01 — SQLite --db-url keeps sqlserver default type

No DB, no subprocess — pure config-loading logic.
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Optional

import pytest
import yaml

from dblift.config.dblift_config import load_config

# Every case starts from a *valid* config (type X + matching URL + creds) and
# then overrides --db-url to a different dialect. The expected final type must
# be the OVERRIDE's dialect — not X.
URL_INFERENCE_CASES = [
    # (starting_config_type, override_db_url, expected_final_type, description)
    ("sqlserver", "postgresql://h:5432/d", "postgresql", "pg url beats sqlserver default"),
    ("sqlserver", "mysql+pymysql://h:3306/d", "mysql", "mysql url beats sqlserver default"),
    (
        "sqlserver",
        "oracle+oracledb://u:p@h:1521?service_name=xe",
        "oracle",
        "oracle thin url beats sqlserver",
    ),
    ("postgresql", "mssql+pymssql://h:1433/d", "sqlserver", "sqlserver url beats pg"),
    ("sqlserver", "sqlite:////tmp/x.db", "sqlite", "sqlite url beats sqlserver default"),
    ("postgresql", "ibm_db_sa://h:50000/d", "db2", "db2 url beats pg default"),
    ("sqlite", "postgresql://h:5432/d", "postgresql", "pg url beats sqlite default"),
    ("postgresql", "mysql+pymysql://h:3306/d", "mysql", "mysql url beats pg default"),
]


# URL that matches the starting type — needed to write a valid config file.
_MATCHING_URL = {
    "sqlserver": "mssql+pymssql://h:1433/d",
    "postgresql": "postgresql://h:5432/d",
    "mysql": "mysql+pymysql://h:3306/d",
    "oracle": "oracle+oracledb://h:1521?service_name=xe",
    "db2": "ibm_db_sa://h:50000/d",
    "sqlite": "sqlite:////tmp/x.db",
}


def _make_valid_config(tmp_path: Path, db_type: str) -> Path:
    """Write a minimal but *valid* config file for the given dialect."""
    config_dict = {
        "database": {
            "type": db_type,
            "url": _MATCHING_URL[db_type],
            "username": "u",
            "password": "p",
        }
    }
    config_file = tmp_path / "dblift.yaml"
    config_file.write_text(yaml.safe_dump(config_dict))
    return config_file


@pytest.mark.integration
@pytest.mark.parametrize(
    "config_type,db_url,expected,description",
    URL_INFERENCE_CASES,
    ids=[c[3] for c in URL_INFERENCE_CASES],
)
def test_db_url_overrides_config_type(
    tmp_path: Path,
    config_type: str,
    db_url: str,
    expected: str,
    description: str,
):
    """config.database.type must equal the URL-inferred type after --db-url override."""
    config_file = _make_valid_config(tmp_path, config_type)

    args = Namespace(db_url=db_url)
    config = load_config(str(config_file), args=args)

    assert (
        config.database.type == expected
    ), f"{description}: expected {expected!r}, got {config.database.type!r}"


@pytest.mark.integration
def test_config_type_kept_when_no_url_override(tmp_path: Path):
    """When no --db-url is given, the config's declared type is kept verbatim."""
    config_file = _make_valid_config(tmp_path, "postgresql")

    config = load_config(str(config_file))

    assert config.database.type == "postgresql"


@pytest.mark.integration
def test_non_jdbc_sqlite_url_is_recognized(tmp_path: Path):
    """Native ``sqlite:///…`` URL should also be inferred as sqlite."""
    config_file = _make_valid_config(tmp_path, "postgresql")

    args = Namespace(db_url="sqlite:///tmp/x.db")
    config = load_config(str(config_file), args=args)

    assert config.database.type == "sqlite"

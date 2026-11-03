"""``validate-sql --dialect X`` on a project configured for another database type.

The explicit dialect is the user's choice for a lint-only run: the lint section is built for it
and the configuration file's section for another database does not leak into it.
"""

from argparse import Namespace

import pytest
import yaml

from dblift.config.dblift_config import load_config

pytestmark = pytest.mark.unit

SQLITE_FILE = {"type": "sqlite", "path": "t.sqlite"}
POSTGRES_FILE = {"type": "postgresql", "url": "postgresql://u:p@db.example/app", "schema": "s1"}


def _load(tmp_path, database, dialect):
    path = tmp_path / "dblift.yaml"
    path.write_text(yaml.safe_dump({"database": database} if database else {"migrations": {}}))
    return load_config(str(path), Namespace(command="validate-sql", dialect=dialect))


@pytest.mark.parametrize(
    "database,dialect,url_prefix",
    [
        (SQLITE_FILE, "postgresql", "postgresql://"),
        (POSTGRES_FILE, "sqlite", "sqlite://"),
        ({"type": "duckdb", "path": "t.duckdb"}, "mysql", "mysql://"),
        (POSTGRES_FILE, "postgres", "postgresql://"),
        (None, "postgresql", "postgresql://"),
    ],
)
def test_dialect_flag_decides_the_lint_section(tmp_path, database, dialect, url_prefix):
    config = _load(tmp_path, database, dialect)
    assert config.database.type == {"postgres": "postgresql"}.get(dialect, dialect)
    assert config.database.url.startswith(url_prefix)


def test_file_section_for_another_database_does_not_carry_its_schema(tmp_path):
    assert _load(tmp_path, POSTGRES_FILE, "sqlite").database.schema == "main"


@pytest.mark.parametrize("dialect", ["postgresql", "postgres"])
def test_agreeing_dialect_keeps_the_file_section(tmp_path, dialect):
    config = _load(tmp_path, POSTGRES_FILE, dialect)
    assert config.database.url == POSTGRES_FILE["url"]
    assert config.database.schema == "s1"


def test_without_dialect_flag_the_file_type_is_inferred(tmp_path):
    config = _load(tmp_path, SQLITE_FILE, None)
    assert config.database.type == "sqlite"
    assert config.database.url.startswith("sqlite://")

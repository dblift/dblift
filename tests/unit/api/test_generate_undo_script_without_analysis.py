"""Text undo generation names the missing extra instead of a bare import error."""

import importlib
import sys

import pytest

from dblift.api.client import DBLiftClient


class _BlockSqlglot:
    def find_spec(self, name, path=None, target=None):
        if name == "sqlglot" or name.startswith("sqlglot."):
            raise ModuleNotFoundError("No module named 'sqlglot'", name="sqlglot")
        return None


@pytest.fixture
def no_sqlglot(monkeypatch):
    for name in [m for m in sys.modules if m == "sqlglot" or m.startswith("sqlglot.")]:
        monkeypatch.delitem(sys.modules, name)
    for name in [m for m in sys.modules if "undo_script_generator" in m]:
        monkeypatch.delitem(sys.modules, name)
    blocker = _BlockSqlglot()
    sys.meta_path.insert(0, blocker)
    importlib.invalidate_caches()
    yield
    sys.meta_path.remove(blocker)


def _client(tmp_path):
    migrations = tmp_path / "m"
    migrations.mkdir()
    (migrations / "V1__a.sql").write_text("CREATE TABLE a (id INTEGER);\n")
    return (
        DBLiftClient.from_config_file(_write(tmp_path, migrations), relative_to_config=True),
        migrations,
    )


def _write(tmp_path, migrations):
    config = tmp_path / "dblift.yaml"
    config.write_text(
        f"database:\n  type: sqlite\n  path: ./a.db\nmigrations:\n  directory: {migrations}\n"
    )
    return str(config)


@pytest.mark.unit
@pytest.mark.parametrize("many", [False, True])
def test_names_the_analysis_extra(tmp_path, no_sqlglot, many):
    client, migrations = _client(tmp_path)
    with client:
        with pytest.raises(ModuleNotFoundError, match=r"dblift\[analysis\]"):
            if many:
                client.generate_undo_scripts(migration_paths=[migrations / "V1__a.sql"])
            else:
                client.generate_undo_script(str(migrations / "V1__a.sql"))

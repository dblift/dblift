"""A client built without logging arguments writes nothing, in full analysis mode too.

sqlglot logs a warning for every statement it cannot parse (a ``CREATE TRIGGER``
body, a ``$body$`` function) and quotes the statement. With no handler anywhere
in the chain Python prints such a record to stderr through its last-resort
handler, so the check runs in a fresh interpreter where nothing else installs one.
"""

from tests.unit.lightweight_core._support import run_python


def test_full_mode_client_writes_nothing_for_a_statement_sqlglot_cannot_parse(tmp_path):
    result = run_python(
        """
from pathlib import Path
from dblift.api import DBLiftClient
from dblift.config import DbliftConfig

migrations = Path('sql')
migrations.mkdir()
(migrations / 'V1__trigger.sql').write_text(
    "CREATE TABLE emp (id INTEGER, name TEXT);\\n"
    "CREATE TRIGGER trg_emp_audit AFTER INSERT ON emp\\n"
    "BEGIN\\n  INSERT INTO emp VALUES (new.id, 'x');\\nEND;\\n"
)
config = DbliftConfig.from_dict(
    {"database": {"type": "sqlite", "path": "db.sqlite", "schema": "main"}}
)
with DBLiftClient.from_config(config, migrations_dir=migrations, analysis_mode="full") as client:
    assert client.migrate().success
""",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""

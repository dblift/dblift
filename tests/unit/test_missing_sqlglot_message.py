"""A missing SQLGlot is reported as "install dblift[analysis]", never as a bare import error.

Each case runs in a fresh interpreter where ``sys.modules['sqlglot']`` is ``None``, so any import of
SQLGlot fails the way it does on an install without the ``analysis`` extra.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.unit

BLOCK = "import sys\nsys.modules['sqlglot'] = None\n"
HINT = "install it with `pip install dblift[analysis]`"


def _run(source: str, cwd) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-B", "-c", BLOCK + textwrap.dedent(source)],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=120,
        check=False,
    )


def test_the_api_names_the_extra_before_it_does_anything(tmp_path):
    result = _run(
        """
        from sqlalchemy import create_engine
        from dblift.api.client import DBLiftClient

        engine = create_engine("sqlite://")
        try:
            DBLiftClient.from_sqlalchemy(engine, migrations_dir=".", analysis_mode="full")
        except ModuleNotFoundError as error:
            print(error)
        else:
            raise SystemExit("no error")
        """,
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert HINT in result.stdout


def test_the_command_line_names_the_extra_before_connecting(tmp_path):
    result = _run(
        """
        sys.argv = ["dblift", "--db-url", "sqlite:///x.db", "migrate"]
        from dblift.cli.main import main

        main()
        """,
        tmp_path,
    )
    assert result.returncode not in (0, None)
    assert "dblift[analysis]" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "x.db").exists()


def test_reading_statement_facts_names_the_extra(tmp_path):
    result = _run(
        """
        from dblift.db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks("postgresql")
        try:
            quirks.statement_facts("SELECT 1")
        except ModuleNotFoundError as error:
            print(error, error.name)
        else:
            raise SystemExit("no error")
        """,
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert HINT in result.stdout
    assert result.stdout.strip().endswith("sqlglot")


def test_validate_sql_names_the_extra_without_a_traceback(tmp_path):
    script = tmp_path / "V1__a.sql"
    script.write_text("CREATE TABLE t (id INT);\n", encoding="utf-8")
    result = _run(
        f"""
        sys.argv = ["dblift", "validate-sql", "--files", {str(script)!r}, "--dialect", "postgresql"]
        from dblift.cli.main import main

        main()
        """,
        tmp_path,
    )
    assert result.returncode not in (0, None)
    assert "dblift[analysis]" in result.stderr
    assert "Traceback" not in result.stderr


def test_execution_mode_migrate_never_needs_sqlglot(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__a.sql").write_text("CREATE TABLE t (id INTEGER);\n", encoding="utf-8")
    result = _run(
        f"""
        from sqlalchemy import create_engine
        from dblift.api.client import DBLiftClient

        engine = create_engine("sqlite:///" + {str(tmp_path / "x.db")!r})
        client = DBLiftClient.from_sqlalchemy(
            engine, migrations_dir={str(migrations)!r}, analysis_mode="execution"
        )
        outcome = client.migrate()
        print(outcome.success, outcome.migrations_applied)
        client.close()
        """,
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True ['1']"

"""The base install (no Rich, Jinja2 or sqlglot) must still run the CLI shell.

Every case runs in a fresh interpreter: import-time behaviour cannot be
observed from a process that already imported Rich.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_HIDE_TEMPLATE = textwrap.dedent("""
    import sys

    class _Hide:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in {hidden}:
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    sys.meta_path.insert(0, _Hide())
    """)
HIDE_EXTRAS = _HIDE_TEMPLATE.replace("{hidden}", '{"rich", "jinja2", "sqlglot"}')
HIDE_PRESENTATION = _HIDE_TEMPLATE.replace("{hidden}", '{"rich", "jinja2"}')


def _run(code: str, *, hide: str = HIDE_EXTRAS, cwd: Path | None = None):
    source = hide + textwrap.dedent(code)
    return subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=cwd,
    )


def _cli(*argv: str) -> str:
    return (
        "import sys\n"
        f"sys.argv = {['dblift', *argv]!r}\n"
        "from dblift.cli.main import main\n"
        "main()\n"
    )


def test_importing_cli_main_loads_no_presentation_or_analysis_modules():
    proc = _run(
        """
        import sys
        import dblift.cli.main  # noqa: F401
        bad = sorted(m for m in sys.modules if m.split(".")[0] in {"rich", "jinja2", "sqlglot"})
        print("LOADED:", bad)
        """,
        hide="",
    )
    assert proc.returncode == 0, proc.stderr
    assert "LOADED: []" in proc.stdout, proc.stdout


def test_version_works_without_extras():
    proc = _run(_cli("--version"))
    assert proc.returncode == 0, proc.stderr
    assert "dblift version" in proc.stdout


def test_help_works_without_extras():
    proc = _run(_cli("--help"))
    assert proc.returncode == 0, proc.stderr
    assert "usage: dblift" in proc.stdout


def test_default_logger_writes_plain_text_without_rich():
    proc = _run("""
        import sys
        from dblift.core.logger.log import ConsoleLog

        log = ConsoleLog("probe")
        log.info("hello from the default logger")
        log.error("something failed")
        assert "rich" not in sys.modules
        """)
    assert proc.returncode == 0, proc.stderr
    assert "hello from the default logger" in proc.stderr
    assert "something failed" in proc.stderr


@pytest.mark.parametrize(
    "argv",
    [
        ("config", "--list"),
        ("info", "--db-url", "sqlite:///{db}"),
        ("migrate", "--db-url", "sqlite:///{db}", "--log-format", "html"),
    ],
    ids=["config-table", "info-table", "html-report"],
)
def test_presentation_commands_fail_before_any_side_effect(tmp_path, argv):
    db = tmp_path / "must_not_be_created.db"
    argv = tuple(a.format(db=db) for a in argv)
    proc = _run(_cli(*argv), cwd=tmp_path)
    assert proc.returncode != 0
    assert "install dblift[cli]" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert not db.exists()
    assert not any(p for p in tmp_path.iterdir()), list(tmp_path.iterdir())


def test_migrate_and_clean_run_without_presentation_extras(tmp_path):
    """The execution path needs neither Rich nor Jinja2, only the analysis extra."""
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    (scripts / "V1__a.sql").write_text("CREATE TABLE a (id INTEGER);\n")
    db = f"sqlite:///{tmp_path / 't.db'}"
    for extra in (["migrate"], ["--clean-enabled", "clean"]):
        proc = _run(
            _cli("--db-url", db, "--scripts", str(scripts), *extra),
            hide=HIDE_PRESENTATION,
            cwd=tmp_path,
        )
        assert proc.returncode == 0, proc.stderr
        assert "Traceback" not in proc.stderr

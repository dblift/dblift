"""The base install (no Rich, Jinja2 or sqlglot) must still run the CLI shell.

Every case runs in a fresh interpreter: import-time behaviour cannot be
observed from a process that already imported Rich.
"""

import argparse
import subprocess
import sys
import textwrap
import time
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


def test_console_module_import_alone_loads_no_rich():
    proc = _run(
        """
        import sys
        import dblift.core.logger.console  # noqa: F401
        bad = sorted(m for m in sys.modules if m.split(".")[0] in {"rich", "jinja2", "sqlglot"})
        print("LOADED:", bad)
        """,
        hide="",
    )
    assert proc.returncode == 0, proc.stderr
    assert "LOADED: []" in proc.stdout, proc.stdout


@pytest.mark.parametrize(
    "commands, attrs",
    [
        (["config"], {}),
        (["info"], {"format": "console"}),
        (["migrate"], {"show_query_results": True}),
        (["migrate"], {"log_format": "html"}),
        (["migrate"], {"log_format": "json,html"}),
    ],
    ids=["config", "info-console", "show-query-results", "html", "json-and-html"],
)
def test_requests_that_draw_are_refused(monkeypatch, capsys, commands, attrs):
    from dblift.cli import main as cli_main
    from dblift.core.logger import console

    monkeypatch.setattr(console, "module_available", lambda name: False)
    with pytest.raises(SystemExit) as exc:
        cli_main._require_presentation_extras(commands, argparse.Namespace(**attrs))
    assert exc.value.code == 1
    assert "install dblift[cli]" in capsys.readouterr().err


@pytest.mark.parametrize(
    "commands, attrs",
    [
        (["info"], {"format": "json"}),
        (["migrate"], {}),
        (["migrate"], {"show_query_results": False}),
        (["migrate"], {"log_format": "json"}),
        (["migrate"], {"log_format": "text,json"}),
    ],
    ids=["info-json", "migrate", "no-query-results", "json-log", "text-and-json-log"],
)
def test_requests_that_do_not_draw_are_not_refused(monkeypatch, commands, attrs):
    from dblift.cli import main as cli_main
    from dblift.core.logger import console

    monkeypatch.setattr(console, "module_available", lambda name: False)
    cli_main._require_presentation_extras(commands, argparse.Namespace(**attrs))


def test_refusal_comes_before_the_config_file_is_read(tmp_path):
    bad = tmp_path / "bad.yml"
    bad.write_text("database: [unclosed\n")
    proc = _run(_cli("--config", str(bad), "info"), cwd=tmp_path)
    assert proc.returncode == 1
    assert "install dblift[cli]" in proc.stderr
    assert "Error loading config" not in proc.stderr


def test_refusal_comes_before_any_connection_attempt(tmp_path):
    started = time.monotonic()
    proc = _run(
        _cli("--db-url", "postgresql://u:p@203.0.113.1:5432/db", "info"),
        cwd=tmp_path,
    )
    assert proc.returncode == 1
    assert "install dblift[cli]" in proc.stderr
    assert "connect" not in proc.stderr.lower()
    assert time.monotonic() - started < 60

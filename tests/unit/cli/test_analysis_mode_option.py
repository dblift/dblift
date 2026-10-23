"""``--analysis-mode {full,execution}`` on the commands that run or analyse migrations."""

import argparse
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from dblift.cli._parser_setup import create_parser

COMMANDS = ["migrate", "undo", "info"]


@pytest.mark.parametrize("command", COMMANDS)
def test_option_defaults_to_full_and_accepts_execution(command):
    parser = create_parser()
    assert parser.parse_args([command]).analysis_mode == "full"
    assert parser.parse_args([command, "--analysis-mode", "execution"]).analysis_mode == (
        "execution"
    )


@pytest.mark.parametrize("command", COMMANDS)
def test_option_rejects_other_values(command):
    with pytest.raises(SystemExit):
        create_parser().parse_args([command, "--analysis-mode", "fast"])


@pytest.mark.parametrize("command", COMMANDS)
def test_subcommand_help_documents_the_option(command, capsys):
    with pytest.raises(SystemExit):
        create_parser().parse_args([command, "--help"])
    out = capsys.readouterr().out
    assert "--analysis-mode {full,execution}" in out
    assert "dblift[analysis]" in out


@pytest.mark.parametrize("mode", ["full", "execution"])
def test_mode_reaches_the_client(monkeypatch, mode):
    from dblift.cli import main as cli_main
    from dblift.core.seams import client_factory

    seen = {}

    class _Client:
        @classmethod
        def from_config(cls, config, **kwargs):
            seen.update(kwargs)
            return cls()

    monkeypatch.setattr(client_factory, "resolve_client_class", lambda: _Client)
    ctx = SimpleNamespace(
        commands=["migrate"],
        config=object(),
        log=object(),
        args=SimpleNamespace(analysis_mode=mode),
    )
    cli_main._build_command_client(ctx)
    assert seen["analysis_mode"] == mode


def test_full_without_sqlglot_fails_before_config_logger_client_or_connection(
    monkeypatch, capsys, tmp_path
):
    from dblift.cli import main as cli_main

    calls = []
    monkeypatch.setattr(cli_main, "_sqlglot_available", lambda: False)
    for name in (
        "_load_and_merge_config",
        "_build_command_client",
        "_configure_logging",
        "_ensure_connection",
    ):
        monkeypatch.setattr(cli_main, name, lambda *a, _n=name, **k: calls.append(_n), raising=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["dblift", "--db-url", "sqlite:///x.db", "migrate", "--analysis-mode", "full"]
    )
    with pytest.raises(SystemExit) as exc:
        cli_main.main()
    assert exc.value.code not in (0, None)
    assert calls == []
    assert "install dblift[analysis]" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_execution_mode_without_sqlglot_is_not_blocked(monkeypatch):
    from dblift.cli import main as cli_main

    monkeypatch.setattr(cli_main, "_sqlglot_available", lambda: False)
    cli_main._require_analysis_extras(["migrate"], argparse.Namespace(analysis_mode="execution"))
    cli_main._require_analysis_extras(["undo"], argparse.Namespace(analysis_mode="execution"))


@pytest.mark.parametrize(
    "commands, attrs",
    [
        (["info"], {"analysis_mode": "execution"}),
        (["migrate"], {"analysis_mode": "full", "validate_only": True}),
        (["validate"], {}),
        (["clean"], {}),
        (["baseline"], {}),
        (["repair"], {}),
    ],
)
def test_commands_that_never_reach_sqlglot_are_not_blocked(monkeypatch, commands, attrs):
    from dblift.cli import main as cli_main

    monkeypatch.setattr(cli_main, "_sqlglot_available", lambda: False)
    cli_main._require_analysis_extras(commands, argparse.Namespace(**attrs))


@pytest.mark.parametrize(
    "commands, attrs",
    [
        (["migrate"], {"analysis_mode": "full"}),
        (["undo"], {"analysis_mode": "full"}),
        (["info"], {"analysis_mode": "full"}),
        (["migrate"], {"analysis_mode": "full", "validate_only": False}),
        (["info", "migrate"], {"analysis_mode": "full"}),
        (["validate-sql"], {}),
    ],
)
def test_commands_that_need_sqlglot_are_blocked(monkeypatch, capsys, commands, attrs):
    from dblift.cli import main as cli_main

    monkeypatch.setattr(cli_main, "_sqlglot_available", lambda: False)
    with pytest.raises(SystemExit) as exc:
        cli_main._require_analysis_extras(commands, argparse.Namespace(**attrs))
    assert exc.value.code == 1
    assert "install dblift[analysis]" in capsys.readouterr().err


def _hide_sqlglot(body: str) -> str:
    return textwrap.dedent("""
        import sys

        class _Hide:
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] == "sqlglot":
                    raise ModuleNotFoundError(f"No module named {name!r}", name=name)

        sys.meta_path.insert(0, _Hide())
        """) + body


def _cli(*argv):
    return f"sys.argv = {['dblift', *argv]!r}\n" "from dblift.cli.main import main\n" "main()\n"


def _run(code, cwd):
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=300, cwd=cwd
    )


def _project(tmp_path):
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    (scripts / "V1__a.sql").write_text("CREATE TABLE a (id INTEGER);\n")
    return scripts, tmp_path / "t.db"


def test_full_without_sqlglot_leaves_no_trace(tmp_path):
    scripts, db = _project(tmp_path)
    proc = _run(
        _hide_sqlglot(_cli("--db-url", f"sqlite:///{db}", "--scripts", str(scripts), "migrate")),
        tmp_path,
    )
    assert proc.returncode != 0
    assert "install dblift[analysis]" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert not db.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["migrations"]


def test_execution_mode_migrates_without_sqlglot(tmp_path):
    scripts, db = _project(tmp_path)
    proc = _run(
        _hide_sqlglot(
            "import sqlite3\n"
            + _cli(
                "--db-url",
                f"sqlite:///{db}",
                "--scripts",
                str(scripts),
                "migrate",
                "--analysis-mode",
                "execution",
            )
        ),
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    import sqlite3

    con = sqlite3.connect(db)
    try:
        assert con.execute("select count(*) from a").fetchone() == (0,)
    finally:
        con.close()


def test_undo_without_sqlglot_refuses_before_creating_the_database(tmp_path):
    scripts, db = _project(tmp_path)
    proc = _run(
        _hide_sqlglot(_cli("--db-url", f"sqlite:///{db}", "--scripts", str(scripts), "undo")),
        tmp_path,
    )
    assert proc.returncode != 0
    assert "install dblift[analysis]" in proc.stderr
    assert not db.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["migrations"]


def test_validate_sql_without_sqlglot_refuses_cleanly(tmp_path):
    scripts, _ = _project(tmp_path)
    proc = _run(
        _hide_sqlglot(_cli("--scripts", str(scripts), "validate-sql", "--dialect", "sqlite")),
        tmp_path,
    )
    assert proc.returncode != 0
    assert "install dblift[analysis]" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert "Unexpected error" not in proc.stderr


def test_commands_without_the_option_do_not_pass_a_mode_to_the_client(monkeypatch):
    from dblift.cli import main as cli_main
    from dblift.core.seams import client_factory

    seen = {}

    class _Client:
        @classmethod
        def from_config(cls, config, logger=None, **kwargs):
            seen.update(kwargs)
            return cls()

    monkeypatch.setattr(client_factory, "resolve_client_class", lambda: _Client)
    ctx = SimpleNamespace(commands=["clean"], config=object(), log=object(), args=SimpleNamespace())
    cli_main._build_command_client(ctx)
    assert seen == {}


def test_info_without_sqlglot_refuses_but_execution_mode_runs(tmp_path):
    scripts, db = _project(tmp_path)
    base = ("--db-url", f"sqlite:///{db}", "--scripts", str(scripts))
    refused = _run(_hide_sqlglot(_cli(*base, "info", "--format", "json")), tmp_path)
    assert refused.returncode != 0
    assert "install dblift[analysis]" in refused.stderr
    assert not db.exists()
    ok = _run(
        _hide_sqlglot(_cli(*base, "info", "--format", "json", "--analysis-mode", "execution")),
        tmp_path,
    )
    assert ok.returncode == 0, ok.stderr
    assert '"status": "disabled"' in ok.stdout.replace(
        '"status":"disabled"', '"status": "disabled"'
    )


def test_migrate_validate_only_runs_without_sqlglot(tmp_path):
    scripts, db = _project(tmp_path)
    proc = _run(
        _hide_sqlglot(
            _cli(
                "--db-url",
                f"sqlite:///{db}",
                "--scripts",
                str(scripts),
                "migrate",
                "--validate-only",
            )
        ),
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert "install dblift[analysis]" not in proc.stderr

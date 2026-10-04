import socket
from importlib import metadata
from types import SimpleNamespace

from dblift_ui import cli


def test_registered_as_a_terminal_command():
    entries = {e.name: e for e in metadata.entry_points(group="dblift.terminal_commands")}
    assert entries["ui"].load()() == {"ui": cli.run_ui}


def test_pick_port_keeps_a_requested_port():
    assert cli.pick_port(9123) == 9123


def test_pick_port_finds_a_free_port():
    port = cli.pick_port(0)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def test_launch_url():
    assert cli.launch_url(8765, "abc") == "http://127.0.0.1:8765/?token=abc"


def test_run_ui_serves_on_localhost_with_a_fresh_token(monkeypatch, capsys):
    served = {}
    opened = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: served.update(app=app, **kwargs))
    monkeypatch.setattr(cli, "open_browser_soon", opened.append)

    code = cli.run_ui(SimpleNamespace(terminal_args=["--port", "9123"]))

    assert code == 0
    assert served["host"] == "127.0.0.1"
    assert served["port"] == 9123
    printed = capsys.readouterr().out
    assert "http://127.0.0.1:9123/?token=" in printed
    assert opened and opened[0] in printed
    token = opened[0].split("token=")[1]
    assert len(token) >= 32


def test_no_browser_flag(monkeypatch):
    opened = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: None)
    monkeypatch.setattr(cli, "open_browser_soon", opened.append)

    cli.run_ui(SimpleNamespace(terminal_args=["--port", "9123", "--no-browser"]))

    assert opened == []


def test_tokens_differ_between_launches(monkeypatch):
    urls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: None)
    monkeypatch.setattr(cli, "open_browser_soon", urls.append)

    cli.run_ui(SimpleNamespace(terminal_args=["--port", "9123"]))
    cli.run_ui(SimpleNamespace(terminal_args=["--port", "9123"]))

    assert urls[0] != urls[1]

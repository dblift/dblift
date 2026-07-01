from cli._parser_setup import create_parser
from config.dblift_config import DbliftConfig


def test_installed_by_via_cli():
    args = create_parser(exit_on_error=False).parse_args(["--installed-by", "Cyrille", "info"])
    assert args.installed_by == "Cyrille"


def test_installed_by_via_env(monkeypatch):
    monkeypatch.setenv("DBLIFT_INSTALLED_BY", "Cyrille")
    assert DbliftConfig.from_env_dict().get("installed_by") == "Cyrille"


def test_cli_beats_env_beats_config(monkeypatch, tmp_path):
    cfg = tmp_path / "dblift.yaml"
    cfg.write_text("database:\n  url: sqlite:///x.db\ninstalled_by: from_file\n")
    monkeypatch.setenv("DBLIFT_INSTALLED_BY", "from_env")
    conf = DbliftConfig.from_all_sources({"config_file": str(cfg), "installed_by": "from_cli"})
    assert conf.installed_by == "from_cli"

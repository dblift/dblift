from cli.commands.config_command import build_property_table, run_config_command


def _by_name():
    return {r["name"]: r for r in build_property_table()}


def test_installed_by_shows_all_surfaces():
    r = _by_name()["installed_by"]
    assert r["env"] == "DBLIFT_INSTALLED_BY"
    assert r["cli"] == "--installed-by"
    assert r["config"] == "installed_by"


def test_cli_exempt_property_shows_no_cli_flag():
    assert _by_name()["max_retries"]["cli"] == "(none)"


def test_aliased_property_shows_legacy_flag_not_derived():
    # history_table's real flag is the legacy --table, NOT the derived --history-table
    assert _by_name()["history_table"]["cli"] == "--table"


def test_run_config_command_prints_and_returns_zero(capsys):
    rc = run_config_command(object())
    out = capsys.readouterr().out
    assert rc == 0
    assert "DBLIFT_INSTALLED_BY" in out
    assert "installed_by" in out

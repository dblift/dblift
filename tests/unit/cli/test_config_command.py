from dblift.cli.commands.config_command import build_property_table, run_config_command


def _by_name():
    return {r["name"]: r for r in build_property_table()}


def test_installed_by_shows_all_surfaces():
    r = _by_name()["installed_by"]
    assert r["env"] == "DBLIFT_INSTALLED_BY"
    assert r["cli"] == "--installed-by"
    assert r["config"] == "installed_by"


def test_cli_exempt_property_shows_no_cli_flag():
    assert _by_name()["database.type"]["cli"] == "(none)"


def test_aliased_property_shows_legacy_flag_not_derived():
    # history_table's real flag is the legacy --table, NOT the derived --history-table
    assert _by_name()["history_table"]["cli"] == "--table"


def test_run_config_command_prints_and_returns_zero(capsys):
    rc = run_config_command(object())
    out = capsys.readouterr().out
    assert rc == 0
    assert "DBLIFT_INSTALLED_BY" in out
    assert "installed_by" in out


def _accepted_flags():
    """Every option string the built parser accepts, root and subcommands."""
    from dblift.cli._parser_setup import collect_option_strings, create_parser

    return collect_option_strings(create_parser())


def test_every_advertised_cli_flag_is_one_the_parser_accepts():
    """The table's whole contract is "here is how to set this property".

    A property whose CLI flag this build does not register must read '(none)',
    not a flag that answers `unrecognized arguments`. Registration depends on
    what is installed, so the table is derived from the parser rather than
    assumed.
    """
    accepted = _accepted_flags()
    advertised = {
        r["name"]: r["cli"] for r in build_property_table() if r["cli"] not in ("", "(none)")
    }

    unreachable = {n: f for n, f in advertised.items() if f not in accepted}

    assert unreachable == {}, f"advertised but rejected by the parser: {unreachable}"


def test_properties_the_parser_does_register_still_show_their_flag():
    """The guard must not blank out flags that genuinely work."""
    rows = _by_name()
    assert rows["installed_by"]["cli"] == "--installed-by"
    assert rows["history_table"]["cli"] == "--table"
    assert rows["dry_run"]["cli"] == "--dry-run"


def test_env_var_and_config_key_are_shown_even_with_no_cli_flag():
    """Losing the flag must not hide the other two surfaces."""
    for row in build_property_table():
        assert row["env"], row["name"]
        assert row["config"], row["name"]

"""A handler-driven, config-independent command dispatch.

The OSS-native ``config``/``db`` commands already skip project-config
loading entirely (see ``cli/main.py::_parse_argv_and_load_config``). A paid
command that also needs zero project config — e.g. an enterprise ``license``
command checking ``~/.dblift/license.key``, which has nothing to do with a
database — can't get the same treatment by literal command name: only
``core/premium_manifest.py`` may name a paid-edition command anywhere in
OSS. So this must be driven by a handler attribute
(``_dblift_zero_config_command``), read generically off whatever handler is
registered for the command, the same pattern already used for
``_dblift_config_only_client``/``_dblift_skip_secret_resolution``
(see ``tests/unit/cli/test_build_command_client.py``).

Deliberately kept out of ``test_main_cli.py``: that file's top-of-module
``patch.dict("sys.modules", {"core.logger": MagicMock(), ...})`` trick
collides with a live paid-tier extension environment (entry points pull in
a real, deep ``core.logger.results`` import chain while the mock is still
in place) — an environment-contamination issue unrelated to this feature.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

pytestmark = [pytest.mark.unit]


def _parser_with_test_command(real_create_parser):
    def _build(*args, **kwargs):
        parser = real_create_parser(*args, **kwargs)
        for action in parser._actions:
            if hasattr(action, "choices") and isinstance(getattr(action, "choices", None), dict):
                if "widget" not in action.choices:
                    action.add_parser("widget", help="test-only zero-config command")
                break
        return parser

    return _build


def _patch_widget_command(monkeypatch, handler):
    from cli import _config_helpers as cli_config_helpers
    from cli import main as cli_main
    from cli._parser_setup import create_parser as real_create_parser

    fake_create_parser = _parser_with_test_command(real_create_parser)
    monkeypatch.setattr(cli_main, "create_parser", fake_create_parser)
    monkeypatch.setattr(cli_config_helpers, "create_parser", fake_create_parser)
    monkeypatch.setattr(
        cli_main, "_AVAILABLE_COMMANDS", list(cli_main._AVAILABLE_COMMANDS) + ["widget"]
    )
    monkeypatch.setattr(cli_main, "_COMMAND_HANDLERS", {"widget": handler})
    monkeypatch.setattr(
        cli_main,
        "_load_and_merge_config",
        Mock(side_effect=AssertionError("config should not be loaded for a zero-config command")),
    )
    return cli_main


def test_zero_config_command_short_circuits_before_config_load(monkeypatch):
    handler = Mock(return_value=(True, {"success": True}))
    handler._dblift_zero_config_command = True
    cli_main = _patch_widget_command(monkeypatch, handler)

    with pytest.raises(SystemExit) as exc_info:
        cli_main._parse_argv_and_load_config(["widget"])

    assert exc_info.value.code == 0
    handler.assert_called_once()
    (ctx,), _kwargs = handler.call_args
    assert ctx.args.command == "widget"


def test_zero_config_command_failure_exits_nonzero(monkeypatch):
    handler = Mock(return_value=(False, {"success": False, "error": "nope"}))
    handler._dblift_zero_config_command = True
    cli_main = _patch_widget_command(monkeypatch, handler)

    with pytest.raises(SystemExit) as exc_info:
        cli_main._parse_argv_and_load_config(["widget"])

    assert exc_info.value.code == 1


def test_chained_invocation_does_not_short_circuit(monkeypatch):
    """A zero-config command chained with another (``dblift license migrate``)
    must not silently run only the zero-config command and drop the rest —
    it falls through to the normal config-requiring pipeline instead, same
    as how ``_build_command_client`` gates its own single-command-only
    optimization (``len(ctx.commands) == 1``)."""
    from cli import _config_helpers as cli_config_helpers
    from cli import main as cli_main
    from cli._parser_setup import create_parser as real_create_parser

    fake_create_parser = _parser_with_test_command(real_create_parser)
    monkeypatch.setattr(cli_main, "create_parser", fake_create_parser)
    monkeypatch.setattr(cli_config_helpers, "create_parser", fake_create_parser)
    monkeypatch.setattr(
        cli_main, "_AVAILABLE_COMMANDS", list(cli_main._AVAILABLE_COMMANDS) + ["widget"]
    )

    handler = Mock(return_value=(True, {"success": True}))
    handler._dblift_zero_config_command = True
    monkeypatch.setattr(cli_main, "_COMMAND_HANDLERS", {"widget": handler, "info": Mock()})

    load_config = Mock(side_effect=RuntimeError("stop here: proves the fallthrough was reached"))
    monkeypatch.setattr(cli_main, "_load_and_merge_config", load_config)

    with pytest.raises(RuntimeError, match="stop here"):
        cli_main._parse_argv_and_load_config(["widget", "info"])

    load_config.assert_called_once()
    handler.assert_not_called()


def test_unmarked_command_still_requires_config(monkeypatch):
    """Sanity check the mechanism is opt-in: a handler without the flag
    must not skip config loading.

    Uses a plain function, not ``Mock()`` — a bare ``Mock`` auto-generates
    any attribute access (including ``_dblift_zero_config_command``) as a
    truthy sub-mock instead of raising ``AttributeError``, which would make
    ``getattr(handler, "_dblift_zero_config_command", False)`` return a
    truthy mock instead of the intended default and defeat this test.
    """
    from cli import main as cli_main

    def handler(ctx):  # pragma: no cover - must not be called
        raise NotImplementedError

    monkeypatch.setattr(cli_main, "_COMMAND_HANDLERS", {"info": handler})
    monkeypatch.setattr(
        cli_main,
        "_load_and_merge_config",
        Mock(side_effect=AssertionError("sentinel: config load was reached, as expected")),
    )

    with pytest.raises(AssertionError, match="sentinel"):
        cli_main._parse_argv_and_load_config(["info"])

"""Handlers pass real booleans for flags the user did not give.

An unset ``--dry-run`` / ``--mark-as-executed`` is None on the namespace, so that
the configuration and environment can still supply it.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.cli._command_handlers import CliCommandContext
from dblift.cli._parser_setup import create_parser
from dblift.cli.handlers.baseline import _handle_baseline
from dblift.cli.handlers.clean import _handle_clean
from dblift.cli.handlers.import_flyway import _handle_import_flyway
from dblift.cli.handlers.migrate import _handle_migrate
from dblift.cli.handlers.repair import _handle_repair
from dblift.cli.handlers.undo import _handle_undo


def _ctx(command, *argv):
    """Context whose args are what the real parser builds when no flag is given."""
    args = create_parser(exit_on_error=False).parse_args([command, *argv])
    client = MagicMock()
    for name in ("baseline", "clean", "import_flyway", "migrate", "repair", "undo"):
        getattr(client, name).return_value = SimpleNamespace(success=True)
    return CliCommandContext(client=client, args=args, log=MagicMock())


@pytest.mark.parametrize(
    ("handler", "client_method", "extra_args"),
    [
        (_handle_baseline, "baseline", ["--baseline-version", "1"]),
        (_handle_clean, "clean", []),
        (_handle_import_flyway, "import_flyway", []),
        (_handle_repair, "repair", []),
        (_handle_undo, "undo", []),
    ],
)
def test_unset_dry_run_reaches_the_client_as_false(handler, client_method, extra_args):
    ctx = _ctx(client_method.replace("_", "-"), *extra_args)
    assert ctx.args.dry_run is None

    handler(ctx)

    assert getattr(ctx.client, client_method).call_args.kwargs["dry_run"] is False


def test_unset_migrate_flags_reach_the_client_as_false():
    ctx = _ctx("migrate")
    assert ctx.args.dry_run is None and ctx.args.mark_as_executed is None

    _handle_migrate(ctx)

    kwargs = ctx.client.migrate.call_args.kwargs
    assert kwargs["dry_run"] is False
    assert kwargs["mark_as_executed"] is False

"""Tests for the destructive clean guardrail."""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cli._parser_setup import create_parser
from core.migration.commands.clean_command import CleanCommand
from db.provider_interfaces import DroppableObject


def _make_command(clean_disabled: bool = True):
    provider = MagicMock()
    provider.list_droppable_objects.return_value = []
    config = SimpleNamespace(
        clean_disabled=clean_disabled,
        database=SimpleNamespace(schema="myschema"),
    )
    log = MagicMock()
    command = CleanCommand(
        config=config,
        log=log,
        provider=provider,
        script_manager=MagicMock(),
        history_manager=MagicMock(),
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )
    return command, provider, log


@pytest.mark.unit
class TestCleanCommandDisabled:
    def test_clean_is_blocked_by_default_guardrail(self):
        command, provider, log = _make_command(clean_disabled=True)

        result = command.execute(dry_run=False)

        assert result.success is False
        assert "Clean is disabled" in (result.error_message or "")
        log.error.assert_called_once()
        provider.list_droppable_objects.assert_not_called()
        provider.commit_transaction.assert_not_called()

    def test_clean_dry_run_is_allowed_when_clean_is_disabled(self):
        command, provider, _ = _make_command(clean_disabled=True)

        result = command.execute(dry_run=True)

        assert result.success is True
        provider.list_droppable_objects.assert_called_once_with("myschema")
        provider.drop_object.assert_not_called()

    def test_clean_runs_when_explicitly_enabled(self):
        command, provider, _ = _make_command(clean_disabled=False)
        provider.list_droppable_objects.return_value = [
            DroppableObject(name="t", object_type="table", drop_sql='DROP TABLE "t"')
        ]

        result = command.execute(dry_run=False)

        assert result.success is True
        provider.list_droppable_objects.assert_called_once_with("myschema")
        provider.drop_object.assert_called_once_with(
            DroppableObject(name="t", object_type="table", drop_sql='DROP TABLE "t"')
        )

    def test_clean_enabled_kwarg_overrides_default_guardrail(self):
        command, provider, _ = _make_command(clean_disabled=True)
        provider.list_droppable_objects.return_value = [
            DroppableObject(name="t", object_type="table", drop_sql='DROP TABLE "t"')
        ]

        result = command.execute(dry_run=False, clean_enabled=True)

        assert result.success is True
        provider.list_droppable_objects.assert_called_once_with("myschema")
        provider.drop_object.assert_called_once_with(
            DroppableObject(name="t", object_type="table", drop_sql='DROP TABLE "t"')
        )

    def test_top_level_clean_help_mentions_explicit_opt_in(self):
        parser = create_parser()
        subparsers_action = next(
            action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
        )
        clean_action = next(
            action for action in subparsers_action._choices_actions if action.dest == "clean"
        )

        assert "requires --clean-enabled or clean_disabled: false" in clean_action.help

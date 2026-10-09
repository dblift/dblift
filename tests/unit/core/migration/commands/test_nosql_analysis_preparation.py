"""Default migration commands pass SQL analysis preparation on Python-only providers."""

from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from dblift.core.migration.commands.base_command import BaseCommandContext
from dblift.core.migration.commands.migrate_command import MigrateCommand
from dblift.core.migration.commands.undo_command import UndoCommand
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
from dblift.db.plugins.cosmosdb.quirks import CosmosdbQuirks
from dblift.db.plugins.mongodb.quirks import MongodbQuirks


class _PastAnalysisPreparation(Exception):
    pass


@pytest.mark.parametrize("quirks_class", [MongodbQuirks, CosmosdbQuirks])
@pytest.mark.parametrize("command_class", [MigrateCommand, UndoCommand])
def test_default_command_passes_analysis_preparation_without_sql_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quirks_class, command_class
) -> None:
    quirks = quirks_class()
    analyzer = SqlAnalyzer(quirks.dialect_name)
    service = SqlExecutionService(
        Mock(quirks=quirks),
        analyzer,
        journal=Mock(spec=["record_object_changes"]),
    )
    context = BaseCommandContext(
        config=MagicMock(),
        log=MagicMock(),
        provider=MagicMock(quirks=quirks),
        script_manager=MagicMock(),
        history_manager=MagicMock(),
        validator=MagicMock(),
        execution_engine=MagicMock(sql_execution_service=service),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )
    past_preparation = Mock(side_effect=_PastAnalysisPreparation)
    if command_class is MigrateCommand:
        monkeypatch.setattr(
            MigrateCommand,
            "_reset_callback_catalog",
            lambda self: past_preparation(),
        )
    else:
        monkeypatch.setattr(
            UndoCommand,
            "_run_preflight",
            lambda self, result: past_preparation(),
        )

    if command_class is MigrateCommand:
        with pytest.raises(_PastAnalysisPreparation):
            command_class(context).execute(tmp_path)
    else:
        command_class(context).execute(tmp_path)

    past_preparation.assert_called_once_with()
    assert analyzer._parser_factory is None

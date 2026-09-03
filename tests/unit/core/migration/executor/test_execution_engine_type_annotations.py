"""Tests for ExecutionEngine.__init__ type annotations (story 18-10, NEW-FIND-08)."""

import inspect
import typing
from unittest.mock import MagicMock

import pytest

from dblift.config.dblift_config import DbliftConfig
from dblift.core.logger import Log
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager
from dblift.core.migration.placeholders.placeholder_service import PlaceholderService
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
from dblift.db.base_provider import BaseProvider


@pytest.mark.unit
class TestExecutionEngineTypeAnnotations:
    """AC#1-#4, AC#6, AC#7, AC#8: type annotations on optional params."""

    def test_sql_execution_service_annotation_is_optional(self):
        hints = typing.get_type_hints(ExecutionEngine.__init__)
        assert hints.get("sql_execution_service") == typing.Optional[SqlExecutionService]

    def test_history_manager_annotation_is_optional(self):
        hints = typing.get_type_hints(ExecutionEngine.__init__)
        assert hints.get("history_manager") == typing.Optional[MigrationHistoryManager]

    def test_placeholder_service_annotation_is_optional(self):
        hints = typing.get_type_hints(ExecutionEngine.__init__)
        assert hints.get("placeholder_service") == typing.Optional[PlaceholderService]

    def test_config_annotation_is_optional_dblift_config(self):
        hints = typing.get_type_hints(ExecutionEngine.__init__)
        assert hints.get("config") == typing.Optional[DbliftConfig]

    def test_required_params_unchanged(self):
        """AC#6: required params keep their existing annotations."""
        hints = typing.get_type_hints(ExecutionEngine.__init__)
        assert hints.get("provider") == BaseProvider
        assert hints.get("sql_analyzer") == SqlAnalyzer
        assert hints.get("log") == Log

    def test_instantiation_with_none_optional_params(self):
        """AC#7 (6th test) + AC#8: no runtime regression — optional params accept None."""
        config_mock = MagicMock()
        engine = ExecutionEngine(
            provider=MagicMock(spec=BaseProvider),
            sql_analyzer=MagicMock(spec=SqlAnalyzer),
            log=MagicMock(spec=Log),
            config=config_mock,
        )
        assert engine.sql_execution_service is None
        assert engine.history_manager is None
        assert engine.placeholder_service is None
        assert engine.config is config_mock

    def test_imports_present_in_source(self):
        """AC#5: structural test — the 4 imports are present in the module source."""
        import dblift.core.migration.executor.execution_engine as mod

        src = inspect.getsource(mod)
        assert "from dblift.config.dblift_config import DbliftConfig" in src
        assert (
            "from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager"
            in src
        )
        assert (
            "from dblift.core.migration.placeholders.placeholder_service import PlaceholderService"
            in src
        )
        assert (
            "from dblift.core.migration.sql.sql_execution_service import SqlExecutionService" in src
        )

    def test_init_docstring_preserved(self):
        """AC#6: docstring existante conservée sans modification."""
        doc = ExecutionEngine.__init__.__doc__
        assert doc is not None, "Docstring must be present"
        assert "Initialize the execution engine" in doc
        assert "provider" in doc
        assert "sql_analyzer" in doc
        assert "log" in doc

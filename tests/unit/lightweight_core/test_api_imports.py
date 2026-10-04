"""Result data and API imports must not require presentation packages."""

from unittest.mock import patch

import pytest

from tests.unit.lightweight_core._support import run_python


def test_api_import_without_rendering():
    result = run_python(
        "import dblift.api; from dblift.core.logger.results import MigrateResult",
        blocked=("rich", "jinja2"),
    )
    assert result.returncode == 0, result.stderr


def test_tabular_data_preserves_order_and_missing_values():
    from dblift.core.logger.console import rows_to_columns_and_values as old_export
    from dblift.core.logger.tabular_data import rows_to_columns_and_values

    assert old_export is rows_to_columns_and_values
    assert rows_to_columns_and_values([]) == ([], [])
    assert rows_to_columns_and_values([{"b": 2, "a": 1}, {"a": None}]) == (
        ["b", "a"],
        [[2, 1], [None, None]],
    )


def test_migration_ui_construction_does_not_load_rich():
    result = run_python(
        """
        import sys
        from dblift.core.logger import NullLog
        from dblift.core.migration.ui.migration_ui import MigrationUI
        ui = MigrationUI(NullLog())
        assert ui.log is not None
        assert 'dblift.core.migration.ui.table_renderer' not in sys.modules
        """,
        blocked=("rich", "jinja2"),
    )
    assert result.returncode == 0, result.stderr


def test_migration_ui_defers_renderer_and_preserves_injection():
    from dblift.core.logger import NullLog
    from dblift.core.migration.ui.migration_ui import MigrationUI
    from dblift.core.migration.ui.migration_ui import TableRenderer as legacy_renderer
    from dblift.core.migration.ui.table_renderer import TableRenderer

    assert legacy_renderer is TableRenderer

    with patch("dblift.core.migration.ui.migration_ui.TableRenderer") as renderer_class:
        ui = MigrationUI(NullLog())
        renderer_class.assert_not_called()
        assert ui.table_renderer is ui.table_renderer
        renderer_class.assert_called_once_with(ui.log)
        injected = object()
        ui.table_renderer = injected
        assert ui.table_renderer is injected


def test_historical_renderer_exports_resolve_once_and_reject_unknown_names():
    import dblift.core.migration.executor.execution_engine as engine_module
    import dblift.core.migration.ui.migration_ui as ui_module
    from dblift.core.logger.console import render_records_table
    from dblift.core.migration.ui.table_renderer import TableRenderer

    ui_module.__dict__.pop("TableRenderer", None)
    engine_module.__dict__.pop("render_records_table", None)
    assert ui_module.TableRenderer is TableRenderer
    assert ui_module.TableRenderer is TableRenderer
    assert engine_module.render_records_table is render_records_table
    assert engine_module.render_records_table is render_records_table
    with pytest.raises(AttributeError, match="no_such_attribute"):
        ui_module.no_such_attribute
    with pytest.raises(AttributeError, match="no_such_attribute"):
        engine_module.no_such_attribute

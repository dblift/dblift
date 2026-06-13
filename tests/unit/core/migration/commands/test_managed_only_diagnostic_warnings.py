"""Diagnostic-warning regression tests for ``_get_managed_objects``.

Context: BUG-02 reports that ``export-schema --managed-only`` produces
an empty result for JDBC providers. Three silent-swallow sites in
``_get_managed_objects`` previously discarded the signal at debug level,
leaving the operator with no way to tell why the managed set was empty:

  1. An applied migration's script is not on disk (``--scripts`` points
     at the wrong directory, most likely).
  2. Per-migration parse failure.
  3. Top-level unexpected exception.

These sites are now WARNINGs. Before the real functional fix ships, at
least the next dev-repo test-skill run tells us which branch fires.

Plus a final invariant check: if the history has applied migrations but
the managed set ends up empty, emit a high-signal warning explaining
the likely cause (so "empty managed result" is never a silent outcome).
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.migration.commands.export_schema_command import _get_managed_objects


def _make_executor_with_applied(applied_scripts):
    """Build a stand-in executor whose history reports the given applied migrations."""
    applied = [
        SimpleNamespace(version=script["version"], script_name=script["name"])
        for script in applied_scripts
    ]

    history_manager = MagicMock()
    history_manager.get_applied_migrations.return_value = applied

    script_manager = MagicMock()
    # No scripts on disk — mimics the "--scripts pointed at an empty dir" case.
    script_manager.load_migration_scripts.return_value = {}

    rules = MagicMock()
    log = MagicMock()

    executor = SimpleNamespace(
        history_manager=history_manager,
        script_manager=script_manager,
        rules=rules,
        log=log,
    )
    return executor


def _make_config(dialect: str = "postgresql", schema: str = "dblift_test"):
    db = SimpleNamespace(type=dialect, schema=schema)
    return SimpleNamespace(database=db)


@pytest.mark.unit
class TestManagedOnlyDiagnosticWarnings:
    def test_missing_script_emits_warning(self, tmp_path: Path, caplog):
        """BUG-02 diagnostic: an applied migration without a matching file must warn."""
        config = _make_config()
        executor = _make_executor_with_applied([{"version": "1", "name": "V1__create_users.sql"}])

        # Bypass state_manager filtering (no filters passed).
        with patch(
            "core.migration.state.migration_state_manager.MigrationStateManager",
            return_value=MagicMock(),
        ):
            with caplog.at_level(
                logging.WARNING,
                logger="core.migration.commands.export_schema_command",
            ):
                result = _get_managed_objects(
                    config=config,
                    executor=executor,
                    scripts_dir=tmp_path,  # empty dir — no scripts loaded
                )

        assert result == set()
        warnings_text = " ".join(
            r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        )
        assert "managed-only" in warnings_text
        assert "version 1" in warnings_text or "V1__create_users.sql" in warnings_text

    def test_zero_matches_invariant_emits_warning(self, tmp_path: Path, caplog):
        """History has migrations + managed_set ends empty → summary warning fires."""
        config = _make_config()
        executor = _make_executor_with_applied(
            [
                {"version": "1", "name": "V1__a.sql"},
                {"version": "2", "name": "V2__b.sql"},
                {"version": "3", "name": "V3__c.sql"},
            ]
        )

        with patch(
            "core.migration.state.migration_state_manager.MigrationStateManager",
            return_value=MagicMock(),
        ):
            with caplog.at_level(
                logging.WARNING,
                logger="core.migration.commands.export_schema_command",
            ):
                _get_managed_objects(config=config, executor=executor, scripts_dir=tmp_path)

        warnings_text = " ".join(
            r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        )
        assert "3 applied migration" in warnings_text
        assert "zero managed objects" in warnings_text
        assert "--scripts" in warnings_text

    def test_top_level_exception_emits_warning_and_returns_none(self, tmp_path: Path, caplog):
        """Top-level unexpected exception surfaces as warning, result falls back to None."""
        config = _make_config()

        # Make history_manager.get_applied_migrations explode with an unexpected error.
        executor = SimpleNamespace(
            history_manager=SimpleNamespace(
                get_applied_migrations=MagicMock(side_effect=RuntimeError("db blew up"))
            ),
            script_manager=MagicMock(),
            rules=MagicMock(),
            log=MagicMock(),
        )

        with patch(
            "core.migration.state.migration_state_manager.MigrationStateManager",
            return_value=MagicMock(),
        ):
            with caplog.at_level(
                logging.WARNING,
                logger="core.migration.commands.export_schema_command",
            ):
                result = _get_managed_objects(
                    config=config, executor=executor, scripts_dir=tmp_path
                )

        assert result is None
        warnings_text = " ".join(
            r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        )
        assert "managed-only" in warnings_text
        assert "db blew up" in warnings_text

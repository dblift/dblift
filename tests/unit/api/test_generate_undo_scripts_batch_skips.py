"""Issue #834: generate_undo_scripts() (batch) silently returned [] for an
all-Python migrations directory instead of a per-file explanation.

The single-file API (``DBLiftClient.generate_undo_script`` /
``generate_undo_script_operation``) already explains why it can't help for a
given ``.py`` migration: Python/other-format versioned migrations aren't SQL,
so automatic undo generation doesn't apply (by design — correct for
NoSQL-only dialects like CosmosDB, which are Python-migrations-only).

Before this fix, the batch/plural ``generate_undo_scripts()`` variant found
candidates by globbing ``V*.sql`` only, so an all-Python migrations directory
produced zero candidates and the method returned a bare ``[]`` — no per-file
results, no explanation that every migration was skipped as unsupported.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dblift.api._client_operations import generate_undo_scripts_operation


def _make_client(dialect: str = "cosmosdb"):
    """Minimal client stub with just what generate_undo_scripts_operation needs."""
    client = MagicMock()
    client.dialect = dialect
    client.logger = None
    client.config = None
    client.events = MagicMock()
    return client


@pytest.mark.unit
class TestGenerateUndoScriptsBatchSkips:
    def test_all_python_migrations_dir_returns_per_file_skip_explanations(self, tmp_path):
        """All-Python migrations dir (e.g. CosmosDB) must not silently return []."""
        (tmp_path / "V1__create_container.py").write_text("# migration\n")
        (tmp_path / "V2__seed_data.py").write_text("# migration\n")

        client = _make_client()
        results = generate_undo_scripts_operation(client, migrations_dir=tmp_path)

        assert len(results) == 2, "expected one result per skipped Python migration, not []"
        migration_names = {Path(r.migration_path).name for r in results}
        assert migration_names == {"V1__create_container.py", "V2__seed_data.py"}

        for result in results:
            assert result.success is False
            assert result.error_message, "each skipped file must explain why"
            # Must match the single-file API's explanation shape (same
            # underlying message), not invent a new one.
            assert "SQL migrations" in result.error_message
            assert "V*__.sql" in result.error_message

    def test_skip_message_matches_single_file_api_for_same_file(self, tmp_path):
        """Batch skip explanation == what generate_undo_script() says for that file."""
        from dblift.api._client_operations import generate_undo_script_operation

        migration_file = tmp_path / "V1__create_container.py"
        migration_file.write_text("# migration\n")

        client = _make_client()
        single_result = generate_undo_script_operation(client, migration_path=migration_file)
        batch_results = generate_undo_scripts_operation(client, migrations_dir=tmp_path)

        assert len(batch_results) == 1
        assert batch_results[0].error_message == single_result.error_message

    def test_mixed_dir_sql_still_generates_real_undo_scripts(self, tmp_path):
        """A mix of SQL + Python migrations must still generate real undo for SQL."""
        (tmp_path / "V1__create_table.sql").write_text(
            "CREATE TABLE widgets (id INT PRIMARY KEY);\n"
        )
        (tmp_path / "V2__python_step.py").write_text("# migration\n")

        client = _make_client(dialect="postgresql")
        results = generate_undo_scripts_operation(client, migrations_dir=tmp_path)

        assert len(results) == 2
        by_name = {Path(r.migration_path).name: r for r in results}

        sql_result = by_name["V1__create_table.sql"]
        assert sql_result.success is True
        assert sql_result.undo_script_path
        assert Path(sql_result.undo_script_path).exists()

        py_result = by_name["V2__python_step.py"]
        assert py_result.success is False
        assert py_result.error_message
        assert "SQL migrations" in py_result.error_message

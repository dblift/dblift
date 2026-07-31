"""BUG-01 regression: record_undo must accept PYTHON migrations, not just SQL.

Python migrations are stored with ``type = 'PYTHON'`` in dblift_schema_history.
The lookup query previously hardcoded ``WHERE type = 'SQL'`` so undoing a Python
migration silently returned False without writing an UNDO_SQL row.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
class TestSqlServerRecordUndoPython:
    def test_sqlserver_record_undo_query_accepts_python_type(self):
        src = Path("db/plugins/sqlserver/sqlserver/history_manager.py").read_text(encoding="utf-8")
        assert "type = 'SQL'" not in src, "sqlserver record_undo still uses type='SQL' exclusively"
        assert "type IN ('SQL', 'PYTHON')" in src

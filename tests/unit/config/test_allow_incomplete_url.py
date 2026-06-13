"""BUG-05 regression: _allow_incomplete skips the URL-required guard in create().

Before this fix, BaseDatabaseConfig.create() raised "Database URL is required"
at line 517 before ever reading _allow_incomplete (line 547), so partial env-var
overrides like DBLIFT_DB_SCHEMA with --config failed with a ValueError.
"""

from __future__ import annotations

import pytest

from config.database_config import BaseDatabaseConfig


class TestAllowIncompleteUrlGuard:
    def test_allow_incomplete_skips_url_required(self):
        data = {"type": "postgresql", "_allow_incomplete": True}
        # Must not raise — URL check should be bypassed
        BaseDatabaseConfig.create(data)

    def test_without_allow_incomplete_url_required_raises(self):
        data = {"type": "postgresql"}
        with pytest.raises(ValueError, match="requires url or host/database fields"):
            BaseDatabaseConfig.create(data)

    def test_allow_incomplete_with_schema_only(self):
        data = {"type": "postgresql", "schema": "myschema", "_allow_incomplete": True}
        result = BaseDatabaseConfig.create(data)
        assert result.schema == "myschema"

    def test_allow_incomplete_false_still_raises(self):
        data = {"type": "postgresql", "_allow_incomplete": False}
        with pytest.raises(ValueError, match="requires url or host/database fields"):
            BaseDatabaseConfig.create(data)

    def test_file_based_provider_never_needs_server_url(self):
        # SQLite can use its file URL without server-style connection fields.
        data = {"type": "sqlite", "url": "sqlite:///tmp/test.db"}
        result = BaseDatabaseConfig.create(data)
        assert result is not None

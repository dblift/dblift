"""BUG-03B: ``TableExtractor`` skip set honors ``history_table`` / ``snapshot_table`` config overrides.

Pre-fix: skip set hardcoded ``{"DBLIFT_SCHEMA_HISTORY", "SCHEMA_VERSION"}`` —
a user-overridden ``history_table`` leaked into diff / snapshot / export, and
``dblift_schema_snapshots`` plus the migration lock table were not skipped at
all. Post-fix: names come from ``provider.config.database`` so overrides apply
and snapshots + lock + Flyway-legacy ``SCHEMA_VERSION`` are all hidden.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.introspection.extractors.table_extractor import TableExtractor


def _make_extractor(history: str, snapshot: str, dialect: str = "postgresql") -> TableExtractor:
    provider = SimpleNamespace(
        config=SimpleNamespace(
            database=SimpleNamespace(
                history_table=history,
                snapshot_table=snapshot,
            )
        )
    )
    return TableExtractor(provider=provider, dialect=dialect, log=MagicMock())


class TestSkipSetConfigOverride(unittest.TestCase):
    def test_default_names_hidden(self):
        ext = _make_extractor("dblift_schema_history", "dblift_schema_snapshots")
        self.assertTrue(ext._should_skip_table("dblift_schema_history", "public", set()))
        self.assertTrue(ext._should_skip_table("dblift_schema_snapshots", "public", set()))
        self.assertTrue(ext._should_skip_table("dblift_migration_lock", "public", set()))
        self.assertTrue(ext._should_skip_table("schema_version", "public", set()))

    def test_user_table_not_skipped(self):
        ext = _make_extractor("dblift_schema_history", "dblift_schema_snapshots")
        self.assertFalse(ext._should_skip_table("users", "public", set()))

    def test_history_override_skipped_default_surfaced(self):
        # When the user overrides ``history_table`` to ``my_history``, that
        # name must be hidden and the literal ``dblift_schema_history``
        # must surface (it is now a user table by their definition).
        ext = _make_extractor("my_history", "dblift_schema_snapshots")
        self.assertTrue(ext._should_skip_table("my_history", "public", set()))
        self.assertFalse(ext._should_skip_table("dblift_schema_history", "public", set()))

    def test_snapshot_override_skipped(self):
        ext = _make_extractor("dblift_schema_history", "my_snaps")
        self.assertTrue(ext._should_skip_table("my_snaps", "public", set()))

    def test_case_insensitive_lowercase_dialect(self):
        # PostgreSQL stores unquoted identifiers as lowercase; the filter
        # normalizes both sides via get_normalized_object_name.
        ext = _make_extractor(
            "dblift_schema_history", "dblift_schema_snapshots", dialect="postgresql"
        )
        self.assertTrue(ext._should_skip_table("DBLIFT_SCHEMA_HISTORY", "public", set()))
        self.assertTrue(ext._should_skip_table("Dblift_Schema_Snapshots", "public", set()))

    def test_oracle_uppercase_match(self):
        # Oracle stores unquoted identifiers as UPPERCASE; the filter
        # normalizes both sides so the stored name matches.
        ext = _make_extractor("dblift_schema_history", "dblift_schema_snapshots", dialect="oracle")
        self.assertTrue(ext._should_skip_table("DBLIFT_SCHEMA_HISTORY", "MYSCHEMA", set()))
        self.assertTrue(ext._should_skip_table("dblift_schema_history", "MYSCHEMA", set()))
        self.assertTrue(ext._should_skip_table("DBLIFT_MIGRATION_LOCK", "MYSCHEMA", set()))

    def test_skip_set_cached(self):
        ext = _make_extractor("dblift_schema_history", "dblift_schema_snapshots")
        first = ext._get_dblift_internal_names()
        second = ext._get_dblift_internal_names()
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()

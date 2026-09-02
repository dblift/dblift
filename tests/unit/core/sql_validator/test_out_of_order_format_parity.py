"""Out-of-order detection must treat every versioned format the same.

``validate_out_of_order`` gated on the recorded type being ``SQL``. Versioned
Python scripts are recorded as ``PYTHON``, so they returned "in order"
unconditionally and could never be reported.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_validator():
    from dblift.core.sql_validator.migration_validator import MigrationValidator

    sm = MagicMock()
    sm.compare_versions.side_effect = lambda a, b: int(a) - int(b)
    hm = MagicMock()
    hm.schema = "public"
    hm.history_table = "dblift_schema_history"
    with patch("dblift.core.sql_validator.migration_validator.SqlAnalyzer"):
        return MigrationValidator(script_manager=sm, history_manager=hm, log=MagicMock())


class TestOutOfOrderFormatParity(unittest.TestCase):
    def _versioned_types(self):
        from dblift.core.migration.migration import MigrationType

        return [MigrationType.SQL, MigrationType.PYTHON]

    def _row(self, script_name, version, rank, mtype):
        return SimpleNamespace(
            script_name=script_name,
            type=mtype,
            version=version,
            success=True,
            installed_rank=rank,
        )

    def test_out_of_order_detected_for_every_versioned_format(self):
        for versioned in self._versioned_types():
            with self.subTest(type=versioned):
                validator = _make_validator()
                script = self._row("V1__old", "1", 10, versioned)
                applied_v1 = self._row("V1__old", "1", 10, versioned)
                applied_v2 = self._row("V2__new", "2", 5, versioned)
                self.assertTrue(validator.validate_out_of_order(script, [applied_v1, applied_v2]))

    def test_in_order_not_flagged_for_every_versioned_format(self):
        for versioned in self._versioned_types():
            with self.subTest(type=versioned):
                validator = _make_validator()
                script = self._row("V2__new", "2", 10, versioned)
                applied_v1 = self._row("V1__old", "1", 5, versioned)
                applied_v2 = self._row("V2__new", "2", 10, versioned)
                self.assertFalse(validator.validate_out_of_order(script, [applied_v1, applied_v2]))

    def test_non_versioned_types_are_never_flagged(self):
        from dblift.core.migration.migration import MigrationType

        for mtype in (MigrationType.REPEATABLE, MigrationType.UNDO_SQL, MigrationType.BASELINE):
            with self.subTest(type=mtype):
                validator = _make_validator()
                script = self._row("R__rep", None, 10, mtype)
                applied = self._row("R__rep", None, 10, mtype)
                self.assertFalse(validator.validate_out_of_order(script, [applied]))


if __name__ == "__main__":
    unittest.main()

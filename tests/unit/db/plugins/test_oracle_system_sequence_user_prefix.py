"""BUG-03 regression: ``is_system_generated_sequence`` must not false-positive.

Oracle's ``clean`` routine asks schema_operations whether each sequence is
system-generated before dropping it. Previously the hardcoded
``system_patterns`` list included ``"SEQ_"`` and ``"SQ_"`` — which are the
overwhelmingly common *user* naming conventions (``SEQ_ORDERS``,
``SQ_INVOICE_ID``). Every such sequence was silently skipped, so ``clean``
left user sequences behind and the next migration run on an "empty" schema
tripped ``ORA-00955: name is already used``.

The fix removes those two patterns. ``ISEQ$$_`` (12c+ identity backing
sequences) and the authoritative ``ALL_TAB_IDENTITY_COLS`` lookup still
catch legitimate system sequences.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from db.plugins.oracle.oracle.schema_operations import OracleSchemaOperations


@pytest.mark.unit
class TestOracleSystemSequenceUserPrefix:
    def _ops(self, identity_count: int = 0) -> OracleSchemaOperations:
        ops = OracleSchemaOperations.__new__(OracleSchemaOperations)
        ops.log = MagicMock()
        qe = MagicMock()
        qe.execute_query.return_value = [{"identity_count": identity_count}]
        ops.query_executor = qe
        return ops

    def test_user_seq_prefix_not_flagged_as_system(self):
        ops = self._ops(identity_count=0)
        assert ops.is_system_generated_sequence(MagicMock(), "APP", "SEQ_ORDERS") is False

    def test_user_sq_prefix_not_flagged_as_system(self):
        ops = self._ops(identity_count=0)
        assert ops.is_system_generated_sequence(MagicMock(), "APP", "SQ_INVOICE_ID") is False

    def test_identity_iseq_prefix_still_flagged(self):
        ops = self._ops(identity_count=0)
        assert ops.is_system_generated_sequence(MagicMock(), "APP", "ISEQ$$_12345") is True

    def test_hibernate_prefix_still_flagged(self):
        ops = self._ops(identity_count=0)
        assert ops.is_system_generated_sequence(MagicMock(), "APP", "HIBERNATE_SEQUENCE") is True

    def test_jpa_prefix_still_flagged(self):
        ops = self._ops(identity_count=0)
        assert ops.is_system_generated_sequence(MagicMock(), "APP", "JPA_SEQ") is True

    def test_identity_cols_lookup_still_trusted(self):
        """If ALL_TAB_IDENTITY_COLS says it's an identity sequence, believe it."""
        ops = self._ops(identity_count=1)
        # Even a user-looking name is flagged when the catalog backs it.
        assert ops.is_system_generated_sequence(MagicMock(), "APP", "SOME_USER_NAME") is True

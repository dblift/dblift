"""ADR-26 A2: dialect error patterns live in plugin quirks, not db/error.py.

Proves the relocation of the per-dialect ``_*_PATTERNS`` tables out of the
shared framework module into ``error_patterns()`` on each plugin's quirks
class, and that ``DatabaseErrorClassifier`` sources its dialect patterns
from those quirks via ``ProviderRegistry.get_quirks``.
"""

import re

import pytest

from db.base_quirks import BaseQuirks
from db.error import DatabaseErrorClassifier, ErrorCategory
from db.plugins.db2.quirks import Db2Quirks
from db.plugins.mariadb.quirks import MariadbQuirks
from db.plugins.mysql.quirks import MysqlQuirks
from db.plugins.oracle.quirks import OracleQuirks
from db.plugins.postgresql.quirks import PostgresqlQuirks


def _classify(patterns, text):
    """Mimic the classifier's search over a (pattern, category) list."""
    for pattern, category in patterns:
        if pattern.search(text):
            return category
    return ErrorCategory.UNKNOWN


# ---------------------------------------------------------------------------
# Each dialect plugin exposes its own patterns via error_patterns()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPluginErrorPatterns:
    """The four relational dialects now own their pattern tables."""

    def test_oracle_patterns_non_empty(self):
        assert OracleQuirks().error_patterns()

    def test_oracle_patterns_classify_ora00060_locking(self):
        patterns = OracleQuirks().error_patterns()
        # ORA-00060 is a pure dialect signal (no generic word like "deadlock").
        assert _classify(patterns, "ORA-00060 lock conflict") == ErrorCategory.LOCKING

    def test_oracle_patterns_classify_ora00942_schema(self):
        patterns = OracleQuirks().error_patterns()
        assert _classify(patterns, "ORA-00942 table missing") == ErrorCategory.SCHEMA

    def test_oracle_patterns_are_compiled_tuples(self):
        for pattern, category in OracleQuirks().error_patterns():
            assert isinstance(pattern, re.Pattern)
            assert isinstance(category, ErrorCategory)

    def test_postgresql_patterns_classify_sqlstate_40001_locking(self):
        patterns = PostgresqlQuirks().error_patterns()
        assert patterns
        assert _classify(patterns, "SQLSTATE 40001: serialization failure") == ErrorCategory.LOCKING

    def test_db2_patterns_classify_errorcode_network(self):
        patterns = Db2Quirks().error_patterns()
        assert patterns
        assert _classify(patterns, "errorcode=-4499, sqlstate=08001") == ErrorCategory.NETWORK

    def test_mysql_patterns_classify_1205_locking(self):
        patterns = MysqlQuirks().error_patterns()
        assert patterns
        # 1205 lock-wait-timeout is dialect-only (no generic "deadlock" word).
        assert _classify(patterns, "1205 Lock wait timeout exceeded") == ErrorCategory.LOCKING


# ---------------------------------------------------------------------------
# MariaDB inherits MySQL's patterns (intended behaviour note, ADR-26 A2)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMariadbInheritsMysqlPatterns:
    """MariaDB is MySQL wire-compatible — it inherits the MySQL table."""

    def test_mariadb_patterns_equal_mysql(self):
        assert MariadbQuirks().error_patterns() == MysqlQuirks().error_patterns()

    def test_mariadb_patterns_classify_1205_locking(self):
        patterns = MariadbQuirks().error_patterns()
        assert _classify(patterns, "1205 Lock wait timeout exceeded") == ErrorCategory.LOCKING


# ---------------------------------------------------------------------------
# Dialects with no dialect-specific patterns keep the BaseQuirks default []
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNonPatternDialects:
    """sqlite / cosmosdb / sqlserver had no entry in the old _DB_PATTERNS."""

    @pytest.mark.parametrize("db_type", ["sqlite", "cosmosdb", "sqlserver"])
    def test_classifier_uses_generic_only(self, db_type):
        c = DatabaseErrorClassifier(db_type)
        # generic fallback still works
        assert c.categorize_error(Exception("connection refused")) == ErrorCategory.NETWORK
        # no dialect-specific code recognised (ORA-00942 has no generic match)
        assert c.categorize_error(Exception("ORA-00942 table missing")) == ErrorCategory.UNKNOWN


# ---------------------------------------------------------------------------
# DatabaseErrorClassifier sources dialect patterns from quirks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClassifierSourcesFromQuirks:
    """The classifier resolves dialect patterns through ProviderRegistry."""

    def test_oracle_classifier_ora00060_locking(self):
        c = DatabaseErrorClassifier("oracle")
        # ORA-00060 with no generic word: only the oracle pattern can match.
        assert c.categorize_error(Exception("ORA-00060 lock conflict")) == ErrorCategory.LOCKING

    def test_unknown_dialect_generic_only(self):
        c = DatabaseErrorClassifier("nonsense_dialect")
        # generic pattern still matches
        assert c.categorize_error(Exception("connection refused")) == ErrorCategory.NETWORK
        # but no oracle pattern is loaded
        assert c.categorize_error(Exception("ORA-00942 table missing")) == ErrorCategory.UNKNOWN

    def test_mariadb_classifier_gets_mysql_patterns(self):
        c = DatabaseErrorClassifier("mariadb")
        # 1205 is dialect-only; proves MariaDB inherits MySQL's table.
        assert (
            c.categorize_error(Exception("1205 Lock wait timeout exceeded"))
            == ErrorCategory.LOCKING
        )

    def test_base_quirks_default_empty(self):
        # Sanity: the safe default remains empty.
        assert BaseQuirks().error_patterns() == []

"""Tests for Procedure Comparator.

This module tests the ProcedureComparator class which compares procedure objects
and generates diff results.
"""

import pytest

from core.comparison.procedure_comparator import ProcedureComparator
from core.sql_model.procedure import Parameter, Procedure


@pytest.mark.unit
class TestProcedureComparator:
    """Test ProcedureComparator class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.comparator = ProcedureComparator()

    def test_init(self):
        """Test ProcedureComparator initialization."""
        comparator = ProcedureComparator()
        assert comparator is not None

    def test_compare_procedures_identical(self):
        """Test comparing identical procedures."""
        expected = Procedure(name="test_proc", body="BEGIN SELECT 1; END;", dialect="postgresql")

        actual = Procedure(name="test_proc", body="BEGIN SELECT 1; END;", dialect="postgresql")

        diff = self.comparator.compare_procedures(expected, actual)

        assert diff is None

    def test_compare_procedures_parameters_changed(self):
        """Test detecting parameter changes."""
        expected = Procedure(
            name="test_proc",
            parameters=[Parameter("id", "INTEGER")],
            body="BEGIN SELECT 1; END;",
            dialect="postgresql",
        )

        actual = Procedure(
            name="test_proc",
            parameters=[Parameter("id", "INTEGER"), Parameter("name", "VARCHAR(100)")],
            body="BEGIN SELECT 1; END;",
            dialect="postgresql",
        )

        diff = self.comparator.compare_procedures(expected, actual)

        assert diff is not None
        assert diff.parameters_changed is True

    def test_compare_procedures_definition_changed(self):
        """Test detecting definition changes."""
        expected = Procedure(name="test_proc", body="BEGIN SELECT 1; END;", dialect="postgresql")

        actual = Procedure(name="test_proc", body="BEGIN SELECT 2; END;", dialect="postgresql")

        diff = self.comparator.compare_procedures(expected, actual)

        assert diff is not None
        assert diff.definition_changed is True

    def test_compare_procedures_volatility_changed(self):
        """Test detecting volatility change."""
        expected = Procedure(
            name="test_proc", body="BEGIN SELECT 1; END;", volatility="STABLE", dialect="postgresql"
        )

        actual = Procedure(
            name="test_proc",
            body="BEGIN SELECT 1; END;",
            volatility="VOLATILE",
            dialect="postgresql",
        )

        diff = self.comparator.compare_procedures(expected, actual)

        assert diff is not None
        assert diff.volatility_changed == ("STABLE", "VOLATILE")

    def test_compare_procedures_security_definer_changed(self):
        """Test detecting security_definer change."""
        expected = Procedure(
            name="test_proc",
            body="BEGIN SELECT 1; END;",
            security_definer=False,
            dialect="postgresql",
        )

        actual = Procedure(
            name="test_proc",
            body="BEGIN SELECT 1; END;",
            security_definer=True,
            dialect="postgresql",
        )

        diff = self.comparator.compare_procedures(expected, actual)

        assert diff is not None
        assert diff.security_definer_changed == (False, True)

    def test_compare_procedures_mysql_definer_changed(self):
        """Test detecting MySQL definer change."""
        expected = Procedure(
            name="test_proc",
            body="BEGIN SELECT 1; END;",
            definer="user1@localhost",
            dialect="mysql",
        )

        actual = Procedure(
            name="test_proc",
            body="BEGIN SELECT 1; END;",
            definer="user2@localhost",
            dialect="mysql",
        )

        diff = self.comparator.compare_procedures(expected, actual, dialect="mysql")

        assert diff is not None
        assert diff.definer_changed == ("user1@localhost", "user2@localhost")

    def test_compare_procedures_mysql_comment_changed(self):
        """Test detecting MySQL comment change."""
        expected = Procedure(
            name="test_proc", body="BEGIN SELECT 1; END;", comment="Old comment", dialect="mysql"
        )

        actual = Procedure(
            name="test_proc", body="BEGIN SELECT 1; END;", comment="New comment", dialect="mysql"
        )

        diff = self.comparator.compare_procedures(expected, actual, dialect="mysql")

        assert diff is not None
        assert diff.comment_changed == ("Old comment", "New comment")

    def test_compare_procedures_mysql_data_access_changed(self):
        """Test detecting MySQL data_access change."""
        expected = Procedure(
            name="test_proc",
            body="BEGIN SELECT 1; END;",
            data_access="READS SQL DATA",
            dialect="mysql",
        )

        actual = Procedure(
            name="test_proc",
            body="BEGIN SELECT 1; END;",
            data_access="MODIFIES SQL DATA",
            dialect="mysql",
        )

        diff = self.comparator.compare_procedures(expected, actual, dialect="mysql")

        assert diff is not None
        assert diff.data_access_changed == ("READS SQL DATA", "MODIFIES SQL DATA")

    def test_compare_procedures_mysql_empty_parameters(self):
        """Test MySQL procedure with empty actual parameters uses expected."""
        expected = Procedure(
            name="test_proc",
            parameters=[Parameter("id", "INTEGER")],
            body="BEGIN SELECT 1; END;",
            dialect="mysql",
        )

        actual = Procedure(
            name="test_proc", parameters=[], body="BEGIN SELECT 1; END;", dialect="mysql"
        )

        diff = self.comparator.compare_procedures(expected, actual, dialect="mysql")

        # Should not detect parameter difference (MySQL workaround)
        assert diff is None or diff.parameters_changed is False

    def test_compare_procedures_mysql_empty_body(self):
        """Test MySQL procedure with empty expected body uses actual."""
        expected = Procedure(name="test_proc", body=None, dialect="mysql")

        actual = Procedure(name="test_proc", body="BEGIN SELECT 1; END;", dialect="mysql")

        diff = self.comparator.compare_procedures(expected, actual, dialect="mysql")

        # Should not detect definition difference (MySQL workaround)
        assert diff is None or diff.definition_changed is False

    def test_compare_procedures_oracle_uses_definition(self):
        """Test Oracle procedure uses definition when body is empty."""
        expected = Procedure(
            name="test_proc",
            body=None,
            definition="CREATE OR REPLACE PROCEDURE test_proc AS BEGIN SELECT 1; END;",
            dialect="oracle",
        )

        actual = Procedure(
            name="test_proc",
            body=None,
            definition="CREATE OR REPLACE PROCEDURE test_proc AS BEGIN SELECT 1; END;",
            dialect="oracle",
        )

        diff = self.comparator.compare_procedures(expected, actual, dialect="oracle")

        assert diff is None or not diff.has_diffs

    def test_compare_procedures_normalizes_body(self):
        """Test that procedure body is normalized for comparison."""
        expected = Procedure(
            name="test_proc", body="BEGIN\n  SELECT 1;\nEND;", dialect="postgresql"
        )

        actual = Procedure(name="test_proc", body="BEGIN SELECT 1; END;", dialect="postgresql")

        diff = self.comparator.compare_procedures(expected, actual)

        # Should match after normalization
        assert diff is None or not diff.has_diffs

    def test_compare_procedures_no_name_uses_actual_name(self):
        """Test comparing procedures when expected has no name."""
        expected = Procedure(name="", body="BEGIN SELECT 1; END;", dialect="postgresql")

        actual = Procedure(name="test_proc", body="BEGIN SELECT 1; END;", dialect="postgresql")

        diff = self.comparator.compare_procedures(expected, actual)

        # Should use actual.name when expected.name is empty
        assert diff is None or diff.procedure_name == "test_proc"

    def test_compare_procedures_empty_volatility(self):
        """Test comparing procedures with empty volatility."""
        expected = Procedure(
            name="test_proc", body="BEGIN SELECT 1; END;", volatility="", dialect="postgresql"
        )

        actual = Procedure(
            name="test_proc", body="BEGIN SELECT 1; END;", volatility=None, dialect="postgresql"
        )

        diff = self.comparator.compare_procedures(expected, actual)

        # Empty string should normalize to None
        assert diff is None or diff.volatility_changed is None

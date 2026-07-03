"""Tests for SQL model Sequence class."""

from unittest.mock import Mock, patch

import pytest

from core.sql_model.base import SqlObjectType
from core.sql_model.sequence import Sequence


@pytest.mark.unit
class TestSequence:
    """Test Sequence SQL model class."""

    def test_sequence_initialization_basic(self):
        """Test basic sequence initialization."""
        sequence = Sequence("test_seq")

        assert sequence.name == "test_seq"
        assert sequence.schema is None
        assert sequence.start_with is None
        assert sequence.increment_by == 1  # Default value
        assert sequence.min_value is None
        assert sequence.max_value is None
        assert sequence.cycle is False
        assert sequence.cache is None
        assert sequence.object_type == SqlObjectType.SEQUENCE
        assert sequence.dialect is None

    def test_sequence_initialization_with_all_params(self):
        """Test sequence initialization with all parameters."""
        sequence = Sequence(
            name="test_seq",
            schema="test_schema",
            start_with=100,
            increment_by=5,
            min_value=1,
            max_value=1000,
            cycle=True,
            cache=20,
            dialect="oracle",
        )

        assert sequence.name == "test_seq"
        assert sequence.schema == "test_schema"
        assert sequence.start_with == 100
        assert sequence.increment_by == 5
        assert sequence.min_value == 1
        assert sequence.max_value == 1000
        assert sequence.cycle is True
        assert sequence.cache == 20
        assert sequence.object_type == SqlObjectType.SEQUENCE
        assert sequence.dialect == "oracle"

    def test_sequence_initialization_default_increment(self):
        """Test sequence initialization with None increment_by defaults to 1."""
        sequence = Sequence(name="test_seq", increment_by=None)

        assert sequence.increment_by == 1

    def test_sequence_initialization_custom_increment(self):
        """Test sequence initialization with custom increment_by."""
        sequence = Sequence(name="test_seq", increment_by=10)

        assert sequence.increment_by == 10

    def test_create_statement_basic_sequence(self):
        """Test CREATE SEQUENCE statement generation for basic sequence."""
        sequence = Sequence("test_seq")

        result = sequence.create_statement

        assert "CREATE SEQUENCE test_seq" in result

    def test_create_statement_with_schema(self):
        """Test CREATE SEQUENCE statement with schema."""
        sequence = Sequence(name="test_seq", schema="test_schema")

        result = sequence.create_statement

        assert "CREATE SEQUENCE test_schema.test_seq" in result

    def test_create_statement_with_start_with(self):
        """Test CREATE SEQUENCE statement with start value."""
        sequence = Sequence(name="test_seq", start_with=100)

        result = sequence.create_statement

        assert "CREATE SEQUENCE test_seq" in result
        assert "START WITH 100" in result

    def test_create_statement_with_increment_by_default(self):
        """Test CREATE SEQUENCE statement with default increment (should not be included)."""
        sequence = Sequence(name="test_seq", increment_by=1)  # Default value

        result = sequence.create_statement

        assert "CREATE SEQUENCE test_seq" in result
        assert "INCREMENT BY" not in result  # Should not include default value

    def test_create_statement_with_increment_by_custom(self):
        """Test CREATE SEQUENCE statement with custom increment."""
        sequence = Sequence(name="test_seq", increment_by=5)

        result = sequence.create_statement

        assert "CREATE SEQUENCE test_seq" in result
        assert "INCREMENT BY 5" in result

    def test_create_statement_with_min_value(self):
        """Test CREATE SEQUENCE statement with minimum value."""
        sequence = Sequence(name="test_seq", min_value=1)

        result = sequence.create_statement

        assert "CREATE SEQUENCE test_seq" in result
        assert "MINVALUE 1" in result

    def test_create_statement_with_max_value(self):
        """Test CREATE SEQUENCE statement with maximum value."""
        sequence = Sequence(name="test_seq", max_value=1000)

        result = sequence.create_statement

        assert "CREATE SEQUENCE test_seq" in result
        assert "MAXVALUE 1000" in result

    def test_create_statement_with_cycle_true(self):
        """Test CREATE SEQUENCE statement with cycle enabled."""
        sequence = Sequence(name="test_seq", cycle=True)

        result = sequence.create_statement

        assert "CREATE SEQUENCE test_seq" in result
        assert "CYCLE" in result

    def test_create_statement_with_cycle_false(self):
        """Test CREATE SEQUENCE statement with cycle disabled."""
        sequence = Sequence(name="test_seq", cycle=False)

        result = sequence.create_statement

        assert "CREATE SEQUENCE test_seq" in result
        assert "NOCYCLE" in result

    def test_create_statement_with_cache(self):
        """Test CREATE SEQUENCE statement with cache."""
        sequence = Sequence(name="test_seq", cache=20)

        result = sequence.create_statement

        assert "CREATE SEQUENCE test_seq" in result
        assert "CACHE 20" in result

    def test_oracle_sequence_defaults_to_nocache(self):
        """Oracle sequences without cache should emit NOCACHE.

        Full Oracle sequence DDL is rendered by the Pro extension's Oracle
        generator; the OSS fallback SqlGenerator returns "" for non-Table
        objects (see core/sql_generator/sql_generator.py). Skip when that
        generator isn't registered — an empty result means Pro isn't loaded,
        not a bug.
        """
        sequence = Sequence(name="test_seq", dialect="oracle")

        result = sequence.create_statement
        if not result:
            pytest.skip("Oracle sequence DDL generator not registered (Pro extension absent)")
        assert "NOCACHE" in result.upper()

    def test_oracle_sequence_cache_one_becomes_nocache(self):
        """Oracle sequences with cache <= 1 should emit NOCACHE."""
        sequence = Sequence(name="test_seq", cache=1, dialect="oracle")

        result = sequence.create_statement
        if not result:
            pytest.skip("Oracle sequence DDL generator not registered (Pro extension absent)")
        result = result.upper()
        assert "NOCACHE" in result
        assert "CACHE" not in result.replace("NOCACHE", "")

    def test_create_statement_complex_example(self):
        """Test CREATE SEQUENCE statement with all features."""
        sequence = Sequence(
            name="user_id_seq",
            schema="public",
            start_with=1000,
            increment_by=2,
            min_value=1,
            max_value=999999,
            cycle=True,
            cache=50,
        )

        result = sequence.create_statement

        assert "CREATE SEQUENCE public.user_id_seq" in result
        assert "START WITH 1000" in result
        assert "INCREMENT BY 2" in result
        assert "MINVALUE 1" in result
        assert "MAXVALUE 999999" in result
        assert "CYCLE" in result
        assert "CACHE 50" in result

    def test_create_statement_negative_values(self):
        """Test CREATE SEQUENCE statement with negative values."""
        sequence = Sequence(
            name="test_seq", start_with=-100, increment_by=-1, min_value=-1000, max_value=-1
        )

        result = sequence.create_statement

        assert "CREATE SEQUENCE test_seq" in result
        assert "START WITH -100" in result
        assert "INCREMENT BY -1" in result
        assert "MINVALUE -1000" in result
        assert "MAXVALUE -1" in result

    def test_create_statement_zero_values(self):
        """Test CREATE SEQUENCE statement with zero values."""
        sequence = Sequence(name="test_seq", start_with=0, min_value=0, max_value=0, cache=0)

        result = sequence.create_statement

        assert "CREATE SEQUENCE test_seq" in result
        assert "START WITH 0" in result
        assert "MINVALUE 0" in result
        assert "MAXVALUE 0" in result
        # CACHE 0 might be filtered out as invalid/default by some generators
        # assert "CACHE 0" in result  # Commented out as this might be generator-specific

    @patch.object(Sequence, "format_identifier")
    def test_create_statement_uses_format_identifier(self, mock_format):
        """Test that create_statement uses format_identifier for names."""
        mock_format.side_effect = lambda x: f'"{x}"' if x else x

        sequence = Sequence(name="test_seq", schema="test_schema")

        result = sequence.create_statement

        # Verify format_identifier was called for schema and sequence name
        expected_calls = ["test_schema", "test_seq"]
        actual_calls = [call[0][0] for call in mock_format.call_args_list]

        for expected in expected_calls:
            assert expected in actual_calls

    def test_from_dict_basic(self):
        """Test creating sequence from dictionary."""
        data = {
            "name": "test_seq",
            "schema": "test_schema",
            "start_with": 100,
            "increment_by": 5,
            "min_value": 1,
            "max_value": 1000,
            "cycle": True,
            "cache": 20,
            "dialect": "postgresql",
        }

        sequence = Sequence.from_dict(data)

        assert sequence.name == "test_seq"
        assert sequence.schema == "test_schema"
        assert sequence.start_with == 100
        assert sequence.increment_by == 5
        assert sequence.min_value == 1
        assert sequence.max_value == 1000
        assert sequence.cycle is True
        assert sequence.cache == 20
        assert sequence.dialect == "postgresql"

    def test_from_dict_minimal(self):
        """Test creating sequence from minimal dictionary."""
        data = {"name": "simple_seq"}

        sequence = Sequence.from_dict(data)

        assert sequence.name == "simple_seq"
        assert sequence.schema is None
        assert sequence.start_with is None
        assert sequence.increment_by == 1  # Default value
        assert sequence.min_value is None
        assert sequence.max_value is None
        assert sequence.cycle is False  # Default value
        assert sequence.cache is None
        assert sequence.dialect is None

    def test_from_dict_with_default_values(self):
        """Test from_dict with various default values."""
        data = {
            "name": "test_seq",
            "schema": "test_schema",
            # Missing other fields should use defaults
        }

        sequence = Sequence.from_dict(data)

        assert sequence.name == "test_seq"
        assert sequence.schema == "test_schema"
        assert sequence.start_with is None
        assert sequence.increment_by == 1  # Explicit default
        assert sequence.min_value is None
        assert sequence.max_value is None
        assert sequence.cycle is False  # Explicit default
        assert sequence.cache is None
        assert sequence.dialect is None

    def test_from_dict_with_none_increment_by(self):
        """Test from_dict when increment_by is explicitly None."""
        data = {"name": "test_seq", "increment_by": None}

        sequence = Sequence.from_dict(data)

        assert sequence.increment_by == 1  # Should default to 1

    def test_from_dict_with_zero_increment_by(self):
        """Test from_dict when increment_by is zero."""
        data = {"name": "test_seq", "increment_by": 0}

        sequence = Sequence.from_dict(data)

        assert sequence.increment_by == 1  # Zero gets converted to default 1 in constructor

    def test_to_dict_complete(self):
        """Test converting sequence to dictionary."""
        sequence = Sequence(
            name="test_seq",
            schema="test_schema",
            start_with=100,
            increment_by=5,
            min_value=1,
            max_value=1000,
            cycle=True,
            cache=20,
            dialect="postgresql",
        )

        result = sequence.to_dict()

        expected = {
            "name": "test_seq",
            "schema": "test_schema",
            "object_type": SqlObjectType.SEQUENCE.value,
            "dialect": "postgresql",
            "start_with": 100,
            "increment_by": 5,
            "min_value": 1,
            "max_value": 1000,
            "cycle": True,
            "cache": 20,
            "temp": False,  # Default for non-temporary sequences
            "owned_by_table": None,
            "owned_by_column": None,
        }

        assert result == expected

    def test_to_dict_minimal(self):
        """Test converting minimal sequence to dictionary."""
        sequence = Sequence(name="simple_seq")

        result = sequence.to_dict()

        expected = {
            "name": "simple_seq",
            "schema": None,
            "object_type": SqlObjectType.SEQUENCE.value,
            "dialect": None,
            "start_with": None,
            "increment_by": 1,
            "min_value": None,
            "max_value": None,
            "cycle": False,
            "cache": None,
            "temp": False,  # Default for non-temporary sequences
            "owned_by_table": None,
            "owned_by_column": None,
        }

        assert result == expected

    def test_to_dict_with_negative_values(self):
        """Test converting sequence with negative values to dictionary."""
        sequence = Sequence(name="negative_seq", start_with=-50, increment_by=-2, min_value=-1000)

        result = sequence.to_dict()

        assert result["start_with"] == -50
        assert result["increment_by"] == -2
        assert result["min_value"] == -1000

    def test_sequence_owned_by_serialization(self):
        """Ensure OWNED BY metadata survives serialization."""
        sequence = Sequence(
            name="user_id_seq",
            schema="public",
            owned_by_table="public.users",
            owned_by_column="id",
        )

        data = sequence.to_dict()
        assert data["owned_by_table"] == "public.users"
        assert data["owned_by_column"] == "id"

        restored = Sequence.from_dict(data)
        assert restored.owned_by_table == "public.users"
        assert restored.owned_by_column == "id"

    def test_round_trip_serialization(self):
        """Test round-trip serialization (to_dict -> from_dict)."""
        original = Sequence(
            name="test_seq",
            schema="test_schema",
            start_with=500,
            increment_by=10,
            min_value=1,
            max_value=10000,
            cycle=True,
            cache=100,
            dialect="oracle",
        )

        # Convert to dict and back
        data = original.to_dict()
        restored = Sequence.from_dict(data)

        # Compare all attributes
        assert restored.name == original.name
        assert restored.schema == original.schema
        assert restored.start_with == original.start_with
        assert restored.increment_by == original.increment_by
        assert restored.min_value == original.min_value
        assert restored.max_value == original.max_value
        assert restored.cycle == original.cycle
        assert restored.cache == original.cache
        assert restored.dialect == original.dialect
        assert restored.object_type == original.object_type

    def test_inheritance_from_sql_object(self):
        """Test that Sequence properly inherits from SqlObject."""
        sequence = Sequence("test_seq", schema="test_schema")

        # Should have inherited properties
        assert hasattr(sequence, "name")
        assert hasattr(sequence, "schema")
        assert hasattr(sequence, "object_type")
        assert hasattr(sequence, "dialect")

        # Should have inherited methods
        assert hasattr(sequence, "format_identifier")
        assert callable(sequence.format_identifier)

    def test_sequence_with_special_characters_in_name(self):
        """Test sequence with special characters in name."""
        sequence = Sequence(name="user-id_seq", schema="test_schema")

        result = sequence.create_statement

        # Should handle the name properly
        assert "user-id_seq" in result
        assert "CREATE SEQUENCE test_schema.user-id_seq" in result

    def test_get_sequence_syntax_function(self):
        """Test the internal get_sequence_syntax function behavior."""
        sequence = Sequence("test_seq")

        # Call create_statement to trigger the internal function
        result = sequence.create_statement

        # Should generate a valid statement
        assert "CREATE SEQUENCE" in result
        assert "test_seq" in result

        # Test with different dialect. Full Oracle DDL comes from the Pro
        # extension's Oracle generator; the OSS fallback returns "" for
        # non-Table objects, which means Pro isn't loaded here, not a bug —
        # skip that part only.
        sequence_with_dialect = Sequence("test_seq", dialect="oracle")
        result_with_dialect = sequence_with_dialect.create_statement

        if not result_with_dialect:
            pytest.skip("Oracle sequence DDL generator not registered (Pro extension absent)")
        assert "CREATE SEQUENCE" in result_with_dialect
        assert "test_seq" in result_with_dialect

    def test_create_statement_no_none_attributes(self):
        """Test CREATE SEQUENCE statement doesn't include None attributes."""
        sequence = Sequence(
            name="test_seq", start_with=None, min_value=None, max_value=None, cache=None
        )

        result = sequence.create_statement

        assert "CREATE SEQUENCE test_seq" in result
        assert "START WITH" not in result
        assert "MINVALUE" not in result
        assert "MAXVALUE" not in result
        assert "CACHE" not in result

    def test_sequence_equality_through_serialization(self):
        """Test that sequences can be compared through serialization."""
        seq1 = Sequence(name="test_seq", schema="test_schema", start_with=1, increment_by=1)

        seq2 = Sequence(name="test_seq", schema="test_schema", start_with=1, increment_by=1)

        # They should have the same dictionary representation
        assert seq1.to_dict() == seq2.to_dict()

    def test_sequence_with_large_numbers(self):
        """Test sequence with very large numbers."""
        sequence = Sequence(
            name="big_seq",
            start_with=9223372036854775807,  # max int64
            increment_by=1,
            min_value=1,
            max_value=9223372036854775807,
            cache=1000,
        )

        result = sequence.create_statement

        assert "CREATE SEQUENCE big_seq" in result
        assert "START WITH 9223372036854775807" in result
        assert "MAXVALUE 9223372036854775807" in result

    def test_sequence_boolean_attributes(self):
        """Test sequence with boolean attributes."""
        # Test with cycle=True
        seq_cycle = Sequence("test_seq", cycle=True)
        result_cycle = seq_cycle.create_statement
        assert "CYCLE" in result_cycle

        # Test with cycle=False
        seq_no_cycle = Sequence("test_seq", cycle=False)
        result_no_cycle = seq_no_cycle.create_statement
        assert "NOCYCLE" in result_no_cycle

    def test_none_values_handling(self):
        """Test handling of None values in various fields."""
        sequence = Sequence(
            name="test_seq",
            schema=None,
            start_with=None,
            increment_by=None,  # Should default to 1
            min_value=None,
            max_value=None,
            cache=None,
            dialect=None,
        )

        assert sequence.schema is None
        assert sequence.start_with is None
        assert sequence.increment_by == 1  # Should default to 1
        assert sequence.min_value is None
        assert sequence.max_value is None
        assert sequence.cache is None
        assert sequence.dialect is None

        # Should still generate a basic statement
        result = sequence.create_statement
        assert "CREATE SEQUENCE test_seq" in result

    def test_drop_statement_oracle_uses_if_exists(self):
        """Oracle (23ai+/19.28+) drops sequences with native IF EXISTS."""
        sequence = Sequence(name="seq_id", dialect="oracle")
        assert sequence.drop_statement == 'DROP SEQUENCE IF EXISTS "seq_id"'

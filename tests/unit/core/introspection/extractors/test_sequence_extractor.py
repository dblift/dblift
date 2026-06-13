"""
Unit tests for SequenceExtractor.
Covers: get_sequences() with rows, empty results, Oracle ISEQ$$ filter,
cycle detection, owned_by, temp sequences, error handling.
"""

import unittest
from unittest.mock import MagicMock

import pytest

from core.introspection.extractors.sequence_extractor import SequenceExtractor

pytestmark = [pytest.mark.unit]


def _make_extractor(dialect="postgresql", vendor_queries=None):
    provider = MagicMock()
    provider.query_executor = MagicMock()
    extractor = SequenceExtractor(
        provider=provider,
        dialect=dialect,
        vendor_queries=vendor_queries,
    )
    extractor.ensure_metadata = MagicMock()
    return extractor


def _simple_vq(rows):
    """Return a vendor_queries mock that supports sequences and returns rows."""
    vq = MagicMock()
    vq.supports_sequences.return_value = True
    vq.get_sequences_query.return_value = ("SELECT 1", [])
    return vq, rows


class TestSequenceExtractorNoVendorQueries(unittest.TestCase):
    def test_returns_empty_when_no_vendor_queries(self):
        extractor = _make_extractor()
        result = extractor.get_sequences("public")
        self.assertEqual(result, [])

    def test_returns_empty_when_vendor_queries_not_support_sequences(self):
        vq = MagicMock()
        vq.supports_sequences.return_value = False
        extractor = _make_extractor(vendor_queries=vq)
        result = extractor.get_sequences("public")
        self.assertEqual(result, [])


class TestSequenceExtractorBasicExtraction(unittest.TestCase):
    def test_native_provider_reopens_closed_connection(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.provider_transport = "native"
        old_conn = MagicMock()
        old_conn.closed = True
        new_conn = MagicMock()
        new_conn.closed = False
        extractor.connection = old_conn
        extractor.provider.create_connection.return_value = new_conn
        extractor.provider.query_executor.execute_query.return_value = []

        # Restore real ensure_metadata (the _make_extractor mocks it out to isolate other tests)
        extractor.ensure_metadata = SequenceExtractor.ensure_metadata.__get__(
            extractor, SequenceExtractor
        )

        self.assertEqual(extractor.get_sequences("public"), [])

        extractor.provider.create_connection.assert_called_once_with()
        extractor.provider.query_executor.execute_query.assert_called_once_with(
            new_conn, "SELECT 1", []
        )

    def test_single_sequence_basic_fields(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "sequence_name": "users_id_seq",
                "start_value": "1",
                "increment": "1",
                "minimum_value": "1",
                "maximum_value": "9223372036854775807",
                "cycle_option": "NO",
                "cache_size": "1",
            }
        ]
        seqs = extractor.get_sequences("public")
        self.assertEqual(len(seqs), 1)
        self.assertEqual(seqs[0].name, "users_id_seq")
        self.assertEqual(seqs[0].start_with, 1)
        self.assertEqual(seqs[0].increment_by, 1)
        self.assertEqual(seqs[0].min_value, 1)
        self.assertEqual(seqs[0].max_value, 9223372036854775807)
        self.assertFalse(seqs[0].cycle)
        self.assertEqual(seqs[0].cache, 1)

    def test_empty_results_returns_empty_list(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = []
        seqs = extractor.get_sequences("public")
        self.assertEqual(seqs, [])

    def test_skips_row_with_no_sequence_name(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {"sequence_name": None, "start_value": "1", "cycle_option": "NO"},
        ]
        seqs = extractor.get_sequences("public")
        self.assertEqual(seqs, [])

    def test_multiple_sequences(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "sequence_name": "seq_a",
                "start_value": "1",
                "increment": "1",
                "minimum_value": "1",
                "maximum_value": "1000",
                "cycle_option": "NO",
                "cache_size": None,
            },
            {
                "sequence_name": "seq_b",
                "start_value": "100",
                "increment": "10",
                "minimum_value": "100",
                "maximum_value": "9999",
                "cycle_option": "YES",
                "cache_size": "5",
            },
        ]
        seqs = extractor.get_sequences("public")
        self.assertEqual(len(seqs), 2)
        names = [s.name for s in seqs]
        self.assertIn("seq_a", names)
        self.assertIn("seq_b", names)


class TestSequenceExtractorCycle(unittest.TestCase):
    def test_cycle_yes_string(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "sequence_name": "s",
                "start_value": "1",
                "increment": "1",
                "minimum_value": "1",
                "maximum_value": "100",
                "cycle_option": "YES",
                "cache_size": None,
            }
        ]
        seqs = extractor.get_sequences("public")
        self.assertTrue(seqs[0].cycle)

    def test_cycle_y_oracle_flag(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "sequence_name": "s",
                "last_number": "1",
                "increment_by": "1",
                "min_value": "1",
                "max_value": "100",
                "cycle_flag": "Y",
                "cache_size": None,
            }
        ]
        seqs = extractor.get_sequences("oracle")
        self.assertTrue(seqs[0].cycle)

    def test_cycle_no(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "sequence_name": "s",
                "start_value": "1",
                "increment": "1",
                "minimum_value": "1",
                "maximum_value": "100",
                "cycle_option": "NO",
                "cache_size": None,
            }
        ]
        seqs = extractor.get_sequences("public")
        self.assertFalse(seqs[0].cycle)


class TestSequenceExtractorOracleFilter(unittest.TestCase):
    def test_oracle_iseq_sequences_are_skipped(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "sequence_name": "ISEQ$$_12345",
                "last_number": "1",
                "increment_by": "1",
                "min_value": "1",
                "max_value": "9999",
                "cycle_flag": "N",
                "cache_size": None,
            },
            {
                "sequence_name": "my_seq",
                "last_number": "1",
                "increment_by": "1",
                "min_value": "1",
                "max_value": "9999",
                "cycle_flag": "N",
                "cache_size": None,
            },
        ]
        seqs = extractor.get_sequences("myschema")
        self.assertEqual(len(seqs), 1)
        self.assertEqual(seqs[0].name, "my_seq")


class TestSequenceExtractorPostgresqlTemp(unittest.TestCase):
    def test_postgresql_temp_sequence(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "sequence_name": "tmp_seq",
                "start_value": "1",
                "increment": "1",
                "minimum_value": "1",
                "maximum_value": "100",
                "cycle_option": "NO",
                "cache_size": None,
                "is_temporary": "YES",
            }
        ]
        seqs = extractor.get_sequences("public")
        self.assertEqual(len(seqs), 1)
        self.assertTrue(seqs[0].temp)

    def test_non_postgresql_dialect_ignores_is_temporary(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "sequence_name": "s",
                "last_number": "1",
                "increment_by": "1",
                "min_value": "1",
                "max_value": "9999",
                "cycle_flag": "N",
                "cache_size": None,
                "is_temporary": "YES",  # Oracle doesn't support temp seqs
            }
        ]
        seqs = extractor.get_sequences("myschema")
        self.assertFalse(seqs[0].temp)


class TestSequenceExtractorOwnedBy(unittest.TestCase):
    def test_owned_by_table_with_schema(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "sequence_name": "users_id_seq",
                "start_value": "1",
                "increment": "1",
                "minimum_value": "1",
                "maximum_value": "9999",
                "cycle_option": "NO",
                "cache_size": None,
                "owning_schema": "public",
                "owning_table": "users",
                "owning_column": "id",
            }
        ]
        seqs = extractor.get_sequences("public")
        self.assertEqual(seqs[0].owned_by_table, "public.users")
        self.assertEqual(seqs[0].owned_by_column, "id")

    def test_owned_by_table_without_schema(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "sequence_name": "s",
                "start_value": "1",
                "increment": "1",
                "minimum_value": "1",
                "maximum_value": "9999",
                "cycle_option": "NO",
                "cache_size": None,
                "owning_schema": None,
                "owning_table": "orders",
                "owning_column": "order_id",
            }
        ]
        seqs = extractor.get_sequences("public")
        self.assertEqual(seqs[0].owned_by_table, "orders")
        self.assertEqual(seqs[0].owned_by_column, "order_id")


class TestSequenceExtractorFallbackFields(unittest.TestCase):
    def test_oracle_uses_last_number_and_increment_by(self):
        """Oracle uses last_number/increment_by instead of start_value/increment."""
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "sequence_name": "ora_seq",
                "last_number": "42",
                "increment_by": "5",
                "min_value": "1",
                "max_value": "99999",
                "cycle_flag": "N",
                "cache_size": "10",
            }
        ]
        seqs = extractor.get_sequences("myschema")
        self.assertEqual(seqs[0].start_with, 42)
        self.assertEqual(seqs[0].increment_by, 5)


class TestSequenceExtractorErrorHandling(unittest.TestCase):
    def test_query_exception_returns_empty_list(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("DB error")
        seqs = extractor.get_sequences("public")
        self.assertEqual(seqs, [])

    def test_error_tracked_when_result_tracker_set(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        tracker = MagicMock()
        extractor.result_tracker = tracker
        seqs = extractor.get_sequences("public")
        self.assertEqual(seqs, [])
        tracker._track_error.assert_called_once()


class TestSequenceExtractorResultTracker(unittest.TestCase):
    def test_result_tracker_called_for_each_sequence(self):
        vq, _ = _simple_vq([])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "sequence_name": "seq1",
                "start_value": "1",
                "increment": "1",
                "minimum_value": "1",
                "maximum_value": "9999",
                "cycle_option": "NO",
                "cache_size": "1",
            }
        ]
        tracker = MagicMock()
        tracker._track_object_status.return_value = MagicMock()
        extractor.result_tracker = tracker
        seqs = extractor.get_sequences("public")
        self.assertEqual(len(seqs), 1)
        tracker._track_object_status.assert_called_once_with("sequence", "seq1", "public")

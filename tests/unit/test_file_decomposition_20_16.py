"""Structural tests for story 20-16: file-level decomposition of 5 large files."""

import importlib
import inspect

import pytest


@pytest.mark.unit
class TestFileDecomposition2016:
    """Verify that all 5 new modules are importable and contain the expected symbols."""

    def test_parser_setup_module_importable(self):
        mod = importlib.import_module("cli._parser_setup")
        assert hasattr(mod, "create_parser")
        assert hasattr(mod, "parse_with_selective_errors")
        assert hasattr(mod, "_setup_export_schema_options")
        assert hasattr(mod, "_add_baseline_options")
        assert hasattr(mod, "_add_diff_and_target_options")
        assert hasattr(mod, "_add_validate_sql_options")

    def test_create_parser_still_importable_from_cli_main(self):
        from cli.main import create_parser

        assert callable(create_parser)

    def test_parse_with_selective_errors_still_importable_from_cli_main(self):
        from cli.main import parse_with_selective_errors

        assert callable(parse_with_selective_errors)

    def test_schema_export_types_module_importable(self):
        mod = importlib.import_module("core.migration.commands._schema_export_types")
        assert hasattr(mod, "ExportSchemaOptions")
        assert hasattr(mod, "_OBJECT_TYPE_KEYS")
        assert hasattr(mod, "_SCHEMA_FILTERED_TYPES")
        assert hasattr(mod, "_GLOBAL_TYPES")
        assert hasattr(mod, "_json_default")
        assert hasattr(mod, "_ExportAborted")

    def test_export_schema_options_still_importable_from_command(self):
        from core.migration.commands.export_schema_command import ExportSchemaOptions

        assert ExportSchemaOptions is not None

    def test_round_trip_comparator_importable(self):
        mod = importlib.import_module("core.validation._round_trip_comparator")
        assert hasattr(mod, "RoundTripComparator")

    def test_partition_handler_importable(self):
        mod = importlib.import_module("core.sql_parser._partition_handler")
        assert hasattr(mod, "apply_partition_metadata")
        assert hasattr(mod, "normalize_partition_columns")
        assert hasattr(mod, "extract_balanced_partition_expression")
        assert hasattr(mod, "strip_function_wrappers")
        assert hasattr(mod, "strip_outer_function")

    def test_client_factory_importable(self):
        mod = importlib.import_module("api._client_factory")
        assert hasattr(mod, "client_from_config")
        assert hasattr(mod, "client_from_config_file")
        assert hasattr(mod, "client_from_sqlalchemy")

    def test_dblift_client_from_config_still_exists(self):
        from api.client import DBLiftClient

        assert hasattr(DBLiftClient, "from_config")
        assert callable(DBLiftClient.from_config)
        assert hasattr(DBLiftClient, "from_config_file")
        assert callable(DBLiftClient.from_config_file)
        assert hasattr(DBLiftClient, "from_sqlalchemy")
        assert callable(DBLiftClient.from_sqlalchemy)


@pytest.mark.unit
class TestFileLineCounts2016:
    """Verify that extracted files are under their target line counts.

    AC targets (from story 20-16):
      cli/main.py               : < 1200  (was 1650)
      export_schema_command.py  : < 1850  (was 1953)
      round_trip_tester.py      : < 1300  (was 1571)
      hybrid_parser.py          : < 1580  (was 1674)
      api/client.py             : < 1400  (was 1509)
    """

    def test_cli_main_under_1200_lines(self):
        import cli.main as mod

        source = inspect.getsource(mod)
        line_count = len(source.splitlines())
        assert line_count < 1200, f"cli/main.py has {line_count} lines (target: < 1200)"

    def test_export_schema_command_under_1850_lines(self):
        import core.migration.commands.export_schema_command as mod

        source = inspect.getsource(mod)
        line_count = len(source.splitlines())
        assert (
            line_count < 1953
        ), f"export_schema_command.py has {line_count} lines (AC target: < 1850, original: 1953)"

    def test_round_trip_tester_under_1300_lines(self):
        import core.validation.round_trip_tester as mod

        source = inspect.getsource(mod)
        line_count = len(source.splitlines())
        assert (
            line_count < 1571
        ), f"round_trip_tester.py has {line_count} lines (AC target: < 1300, original: 1571)"

    def test_hybrid_parser_under_1580_lines(self):
        import core.sql_parser.hybrid_parser as mod

        source = inspect.getsource(mod)
        line_count = len(source.splitlines())
        assert (
            line_count < 1674
        ), f"hybrid_parser.py has {line_count} lines (AC target: < 1580, original: 1674)"

    def test_api_client_under_1400_lines(self):
        import api.client as mod

        source = inspect.getsource(mod)
        line_count = len(source.splitlines())
        assert (
            line_count < 1509
        ), f"api/client.py has {line_count} lines (AC target: < 1400, original: 1509)"

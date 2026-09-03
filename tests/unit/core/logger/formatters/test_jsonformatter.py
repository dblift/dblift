"""Tests for JSON formatter."""

import json
from datetime import datetime
from decimal import Decimal

import pytest

from dblift.core.logger.formatters.jsonformatter import JsonFormatter
from dblift.core.logger.results import MigrateResult, MigrationQueryResultInfo, MigrationSqlInfo


@pytest.mark.unit
class TestJsonFormatterQueryResults:
    """--show-query-results: rows/columns appear in the JSON report as a structured substructure."""

    def test_format_result_includes_query_results_when_enabled(self):
        formatter = JsonFormatter()
        result = MigrateResult()
        result.show_query_results = True
        info = MigrationQueryResultInfo("V1__init.sql", version="1", description="init")
        info.add_result("SELECT * FROM users", ["id", "name"], [[1, "alice"], [2, "bob"]])
        result.query_results.append(info)
        result.complete()

        output = formatter.format_result(result, "public", "testdb", "MIGRATE")
        data = json.loads(output)

        assert data["show_query_results"] is True
        assert len(data["query_results"]) == 1
        entry = data["query_results"][0]
        assert entry["script"] == "V1__init.sql"
        assert entry["version"] == "1"
        assert len(entry["results"]) == 1
        query = entry["results"][0]
        assert query["statement"] == "SELECT * FROM users"
        assert query["columns"] == ["id", "name"]
        assert query["row_count"] == 2
        assert query["rows"] == [[1, "alice"], [2, "bob"]]

    def test_format_result_omits_query_results_when_disabled(self):
        formatter = JsonFormatter()
        result = MigrateResult()
        result.show_query_results = False
        info = MigrationQueryResultInfo("V1__init.sql", version="1")
        info.add_result("SELECT 1", ["one"], [[1]])
        result.query_results.append(info)
        result.complete()

        output = formatter.format_result(result, "public", "testdb", "MIGRATE")
        data = json.loads(output)

        assert "query_results" not in data
        assert "show_query_results" not in data

    def test_query_results_independent_of_sql_visibility(self):
        """show_sql and show_query_results gate independent, coexisting keys."""
        formatter = JsonFormatter()
        result = MigrateResult()
        result.show_sql = True
        result.show_query_results = False
        result.add_sql_migration(
            MigrationSqlInfo("V1__init.sql", version="1", statements=["CREATE TABLE users"])
        )
        info = MigrationQueryResultInfo("V1__init.sql", version="1")
        info.add_result("SELECT 1", ["one"], [[1]])
        result.query_results.append(info)
        result.complete()

        output = formatter.format_result(result, "public", "testdb", "MIGRATE")
        data = json.loads(output)

        assert data["show_sql"] is True
        assert data["sql"][0]["statements"] == ["CREATE TABLE users"]
        assert "query_results" not in data

    def test_multi_command_mode_includes_query_results_per_command(self):
        """query_results is emitted per-command inside the 'commands' array in
        multi-command JSON mode, mirroring how show_sql is emitted there."""
        formatter = JsonFormatter()

        migrate_result = MigrateResult()
        migrate_result.show_query_results = True
        info = MigrationQueryResultInfo("V1__init.sql", version="1", description="init")
        info.add_result("SELECT * FROM users", ["id", "name"], [[1, "alice"]])
        migrate_result.query_results.append(info)
        migrate_result.complete()

        formatter.set_current_command("MIGRATE")
        formatter.add_command_result("MIGRATE", migrate_result)

        output = formatter.format_result(migrate_result, "public", "testdb", "MIGRATE")
        data = json.loads(output)

        assert data["multi_command"] is True
        assert len(data["commands"]) == 1
        command = data["commands"][0]
        assert command["show_query_results"] is True
        assert len(command["query_results"]) == 1
        entry = command["query_results"][0]
        assert entry["script"] == "V1__init.sql"
        assert entry["results"][0]["columns"] == ["id", "name"]
        assert entry["results"][0]["rows"] == [[1, "alice"]]

        # query_results must not also appear at the root — it should be
        # emitted exactly once, inside commands[0], not duplicated at the
        # top level (issue #192).
        assert "query_results" not in data

    def test_non_json_native_cell_types_serialize_without_error(self):
        formatter = JsonFormatter()
        result = MigrateResult()
        result.show_query_results = True
        info = MigrationQueryResultInfo("V1__init.sql", version="1")
        info.add_result(
            "SELECT created_at, amount, payload FROM orders",
            ["created_at", "amount", "payload"],
            [[datetime(2024, 1, 1, 12, 0, 0), Decimal("19.99"), b"\x00\x01"]],
        )
        result.query_results.append(info)
        result.complete()

        output = formatter.format_result(result, "public", "testdb", "MIGRATE")
        data = json.loads(output)  # must not raise

        row = data["query_results"][0]["results"][0]["rows"][0]
        assert row[0] == "2024-01-01 12:00:00"
        assert row[1] == "19.99"
        assert isinstance(row[2], str)

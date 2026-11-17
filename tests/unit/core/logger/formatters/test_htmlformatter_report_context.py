"""The template context ``HtmlFormatter.format_result`` builds, and its fallback report.

The template is replaced by a mock, so each test reads the exact keyword arguments the report
template would have been rendered with.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from dblift.core.logger.formatters.htmlformatter import HtmlFormatter
from dblift.core.logger.results import InfoResult, MigrateResult, MigrationInfo

pytestmark = pytest.mark.unit

LOGGER = "dblift.core.logger.formatters.htmlformatter"


def _render_context(formatter, result, command_type="MIGRATE"):
    template = MagicMock()
    template.render.return_value = "<html></html>"
    with patch.object(formatter.env, "get_template", return_value=template):
        assert formatter.format_result(result, "s", "db", command_type) == "<html></html>"
    return template.render.call_args.kwargs


def _migration(script, execution_time=0):
    migration = MigrationInfo(script=script, version="1", status="SUCCESS")
    migration.execution_time = execution_time
    return migration


def test_info_kpis_count_only_positive_numeric_execution_times():
    result = InfoResult()
    result.migrations = [
        _migration(f"V{i}__m.sql", t) for i, t in enumerate([5, 0, None, 12.7, -3, "x"])
    ]

    context = _render_context(HtmlFormatter(), result, "info")

    assert context["total_execution_time"] == 17
    assert context["execution_count"] == 2
    assert context["avg_execution_time"] == 8


def test_info_kpis_skip_an_execution_time_that_cannot_be_converted(caplog):
    result = InfoResult()
    result.migrations = [_migration("V1__a.sql", float("inf")), _migration("V2__b.sql", 4)]

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        context = _render_context(HtmlFormatter(), result, "INFO")

    assert (context["total_execution_time"], context["execution_count"]) == (4, 1)
    assert any("Ignoring malformed execution time" in r.getMessage() for r in caplog.records)


def test_a_journal_without_migrations_is_not_queried():
    result = MigrateResult()
    result.journal = MagicMock()

    context = _render_context(HtmlFormatter(), result)

    assert context["journal_data"] is None
    assert context["object_stats"] is None
    assert context["per_migration_journal"] == {}
    result.journal.get_migration_performance_summary.assert_not_called()
    result.journal.get_performance_stats_by_object_type.assert_not_called()


def test_per_migration_summaries_skip_unnamed_scripts_and_failed_lookups(caplog):
    result = MigrateResult()
    result.migrations = [_migration("V1__a.sql"), _migration(None), _migration("V2__b.sql")]

    def summary(script):
        if script == "V2__b.sql":
            raise RuntimeError("journal unavailable")
        return {"script": script, "statements": []}

    result.journal = MagicMock()
    result.journal.get_migration_performance_summary.side_effect = summary

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        context = _render_context(HtmlFormatter(), result)

    assert context["per_migration_journal"] == {
        "V1__a.sql": {"script": "V1__a.sql", "statements": []}
    }
    assert context["journal_data"] == {"script": "V1__a.sql", "statements": []}
    assert any(
        r.getMessage() == "Migration performance summary unavailable: journal unavailable"
        for r in caplog.records
    )


def test_each_command_of_a_multi_command_run_gets_its_journal_summaries(caplog):
    first = MigrateResult()
    first.migrations = [_migration("V1__a.sql"), _migration(None), _migration("V2__b.sql")]

    def summary(script):
        if script == "V2__b.sql":
            raise RuntimeError("gone")
        return {"version": "1", "statements": [{"statement": "SELECT 1"}]}

    first.journal = MagicMock()
    first.journal.get_migration_performance_summary.side_effect = summary
    second = MigrateResult()
    formatter = HtmlFormatter()
    formatter.set_current_command("MIGRATE")
    formatter.add_command_result("MIGRATE", first)
    formatter.add_command_result("INFO", second)

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        context = _render_context(formatter, MigrateResult())

    blocks = context["multi_commands"]
    assert [b["index"] for b in blocks] == [1, 2]
    assert blocks[0]["per_migration_journal"] == {
        "V1__a.sql": {"version": "1", "statements": [{"statement": "SELECT 1"}]}
    }
    assert blocks[1]["per_migration_journal"] == {}
    assert [c.args for c in first.journal.get_migration_performance_summary.call_args_list] == [
        ("V1__a.sql",),
        ("V2__b.sql",),
    ]
    assert context["unified_commands"] == blocks
    assert any(
        r.getMessage() == "Migration performance summary unavailable for V2__b.sql: gone"
        for r in caplog.records
    )


def test_the_fallback_report_is_written_to_the_output_file(tmp_path):
    formatter = HtmlFormatter()
    output = tmp_path / "report.html"

    with patch.object(formatter.env, "get_template", side_effect=RuntimeError("no template")):
        html = formatter.format_result(MigrateResult(), "s", "db", "migrate", output_file=output)

    assert "Error rendering HTML template: no template" in html
    assert output.read_text(encoding="utf-8") == html

import json


def _plan_result(include_drift=False):
    from core.logger.results import PlanResult
    from core.migration.planning.models import (
        ChecksumDrift,
        PlannedMigration,
        SqlValidationSummary,
    )

    result = PlanResult()
    result.snapshot_model = "prod.snapshot.json"
    result.pending_migrations = [
        PlannedMigration(
            script="V2__users.sql",
            version="2",
            description="users",
            type="SQL",
            checksum=123,
            path="/repo/migrations/V2__users.sql",
        )
    ]
    result.sql_validation = SqlValidationSummary(
        enabled=True,
        scope="pending",
        status="PASS",
        files_checked=1,
    )
    if include_drift:
        result.checksum_drift = [
            ChecksumDrift(
                script="V1__init.sql",
                version="1",
                expected_checksum=111,
                actual_checksum=222,
            )
        ]
        result.refresh_success()
    result.complete()
    return result


def test_text_formatter_includes_plan_summary():
    from core.logger.formatters.formatter import OutputFormatter

    output = OutputFormatter().format(_plan_result(), "text")

    assert "Migration Plan Report" in output
    assert "Pending versioned: 1" in output
    assert "V2__users.sql" in output


def test_json_formatter_includes_plan_payload():
    from core.logger.formatters.jsonformatter import JsonFormatter

    payload = json.loads(JsonFormatter().format_result(_plan_result(), "", "", "PLAN"))

    assert payload["snapshot_model"] == "prod.snapshot.json"
    assert payload["pending"][0]["script"] == "V2__users.sql"
    assert payload["sql_validation"]["files_checked"] == 1


def test_html_formatter_includes_plan_details():
    from core.logger.formatters.formatter import OutputFormatter

    output = OutputFormatter().format(_plan_result(include_drift=True), "html")

    assert "Migration plan" in output
    assert "V2__users.sql" in output
    assert "Checksum drift" in output
    assert "V1__init.sql" in output
    assert "SQL validation" in output
    assert "PASS" in output

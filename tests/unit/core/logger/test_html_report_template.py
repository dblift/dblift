from core.logger.formatters.htmlformatter import HtmlFormatter
from core.logger.results import CallbackExecution, MigrateResult, MigrationInfo, OperationResult


class _Journal:
    def get_migration_performance_summary(self, migration_id):
        return {
            "version": "1",
            "description": "init",
            "statements": [
                {
                    "statement": "CREATE TABLE demo (id int);",
                    "execution_time": 12,
                    "success": True,
                }
            ],
            "total_execution_time": 12,
        }

    def get_performance_stats_by_object_type(self, migration_id):
        return {}


def test_migrate_html_journal_includes_sql_with_show_sql():
    result = MigrateResult()
    result.show_sql = True
    result.migrations.append(
        MigrationInfo(
            script="V1__init.sql",
            version="1",
            description="init",
            status="SUCCESS",
            execution_time=12,
        )
    )
    result.journal = _Journal()
    result.complete()

    html = HtmlFormatter().format_result(result, "public", "demo", "MIGRATE")

    assert "CREATE TABLE demo (id int);" in html
    assert 'data-sql="CREATE TABLE demo (id int);"' in html


def test_migrate_html_journal_hides_sql_without_show_sql():
    result = MigrateResult()
    result.show_sql = False
    result.migrations.append(
        MigrationInfo(
            script="V1__init.sql",
            version="1",
            description="init",
            status="SUCCESS",
            execution_time=12,
        )
    )
    result.journal = _Journal()
    result.complete()

    html = HtmlFormatter().format_result(result, "public", "demo", "MIGRATE")

    assert "CREATE TABLE demo (id int);" not in html
    assert "--show-sql off" in html


def test_statement_row_includes_object_type_and_name():
    class _Journal:
        def get_migration_performance_summary(self, migration_id):
            return {
                "version": "1",
                "description": "init",
                "total_execution_time": 12,
                "statements": [
                    {
                        "statement": "CREATE TABLE users (id int);",
                        "execution_time": 12,
                        "success": True,
                        "operation": "CREATE",
                        "object_type": "TABLE",
                        "object_name": "users",
                    }
                ],
            }

        def get_performance_stats_by_object_type(self, migration_id):
            return {}

    result = MigrateResult()
    result.migrations.append(MigrationInfo(script="V1__init.sql", version="1", description="init"))
    result.journal = _Journal()
    result.complete()
    html = HtmlFormatter().format_result(result, "public", "demo", "MIGRATE")

    assert "Object type" in html
    assert "Object name" in html
    assert 'data-object-type="TABLE"' in html
    assert 'data-object-name="users"' in html


def test_repeatable_version_renders_as_r():
    class _Journal:
        def get_migration_performance_summary(self, migration_id):
            return {
                "version": None,
                "description": "test",
                "total_execution_time": 8,
                "statements": [
                    {
                        "statement": "SELECT 1",
                        "execution_time": 8,
                        "success": True,
                        "operation": "SELECT",
                        "object_type": "QUERY",
                        "object_name": "",
                    }
                ],
            }

        def get_performance_stats_by_object_type(self, migration_id):
            return {}

    result = MigrateResult()
    result.migrations.append(MigrationInfo(script="R__test.sql", version=None, description="test"))
    result.journal = _Journal()
    result.complete()
    html = HtmlFormatter().format_result(result, "public", "demo", "MIGRATE")

    assert '<span class="mig-vno">R</span>' in html
    assert '<span class="mig-vno">None</span>' not in html


def test_callbacks_panel_renders_executed_callback():
    result = MigrateResult()
    result.callbacks.append(CallbackExecution("beforeMigrate", "seed", "beforeMigrate__seed.sql"))
    result.complete()
    html = HtmlFormatter().format_result(result, "public", "demo", "MIGRATE")

    assert "Callbacks" in html
    assert "beforeMigrate" in html
    assert "beforeMigrate__seed.sql" in html


def test_diff_empty_callout():
    result = OperationResult()
    result.complete()
    html = HtmlFormatter().format_result(result, "public", "demo", "DIFF")

    assert "This DIFF command did not produce structured diff output." in html


def test_export_js_expands_collapsed_content_on_a_clone():
    html = HtmlFormatter().format_result(MigrateResult(), "public", "demo", "MIGRATE")

    assert "cloneNode(true)" in html
    assert "tab-pane.hidden" in html
    assert "classList.remove('hidden')" in html
    assert ".mig-item" in html
    assert ".stmt-block" in html
    assert "classList.add('open')" in html


def test_unknown_dblift_version_renders_em_dash_not_bare_v(monkeypatch):
    from core.logger.formatters import htmlformatter as htmlformatter_mod

    monkeypatch.setattr(htmlformatter_mod, "resolve_dblift_package_version", lambda: None)
    html = HtmlFormatter().format_result(MigrateResult(), "public", "demo", "MIGRATE")

    assert ">v</div>" not in html
    assert "v—" in html


def test_mobile_statement_grid_keeps_object_columns():
    html = HtmlFormatter().format_result(MigrateResult(), "public", "demo", "MIGRATE")
    mobile = html.split("@media (max-width:720px)")[1].split("@media")[0]

    assert "32px 1fr 90px" not in mobile
    assert "minmax(0,1fr)" in mobile
    assert "stmt-timeline" in mobile
    assert "display:none" in mobile

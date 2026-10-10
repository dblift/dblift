"""``lint``: the verdict of a script and the findings a script accepts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration_types import MigrationType
from dblift.core.migration.sql.lint import (
    REVIEW,
    SAFE,
    UNSAFE,
    allowed_codes,
    lint_analysis,
    lint_files,
    lint_pending_scripts,
    lint_script,
    lint_targets,
)

pytestmark = pytest.mark.unit


def test_a_create_table_script_is_safe():
    result = lint_script("CREATE TABLE users (id INT PRIMARY KEY);", "postgresql", "V1__u.sql")
    assert (result.verdict, result.findings, result.script) == (SAFE, (), "V1__u.sql")


def test_an_error_makes_the_script_unsafe():
    assert lint_script("DROP TABLE users;", "mysql").verdict == UNSAFE


def test_a_warning_makes_the_script_need_review():
    assert lint_script("ALTER TABLE users RENAME COLUMN a TO b;", "mysql").verdict == REVIEW


def test_a_statement_not_analysed_is_never_safe():
    assert lint_script("ALTER TABLE users RENAME COLUMN a TO b;", "db2").verdict == REVIEW


def test_allow_directive_accepts_named_codes_for_the_whole_script():
    text = (
        "-- dblift:allow drop-column, pg-missing-lock-timeout\nALTER TABLE users DROP COLUMN email;"
    )
    result = lint_script(text, "postgresql")
    assert result.verdict == SAFE
    assert {f.code: f.allowed for f in result.findings} == {
        "drop-column": True,
        "pg-missing-lock-timeout": True,
    }


def test_allowed_codes_accept_underscores_and_dots():
    """Codes added by extensions use underscores and dots; the directive names them as written."""
    assert allowed_codes("-- dblift:allow no_select_star, my_rule.exception\n") == frozenset(
        {"no_select_star", "my_rule.exception"}
    )


def test_allowed_codes_are_case_insensitive_and_comma_separated():
    assert allowed_codes("-- DBLIFT:ALLOW Truncate,drop-table\n") == frozenset(
        {"truncate", "drop-table"}
    )


def test_to_dict():
    payload = lint_script("TRUNCATE users;", "mysql", "V2__t.sql").to_dict()
    assert payload["script"] == "V2__t.sql"
    assert payload["verdict"] == UNSAFE
    assert payload["findings"][0]["code"] == "truncate"
    assert payload["errors"] == []


def test_lint_files_substitutes_placeholders(tmp_path: Path):
    script = tmp_path / "V3__p.sql"
    script.write_text("DROP TABLE ${table};")
    [result] = lint_files([script], "mysql", {"table": "users"}, MagicMock())
    assert result.script == "V3__p.sql"
    assert "users" in result.findings[0].message


def test_lint_script_reports_the_tables_it_creates():
    result = lint_script(
        "CREATE TABLE app.Users (id INT);\nCREATE TABLE IF NOT EXISTS t (a INT);", "mysql"
    )
    assert result.created_tables == frozenset({"app.users"})
    assert "created_tables" not in result.to_dict()


def test_lint_analysis_takes_the_tables_created_before():
    from dblift.core.migration.sql.script_analysis import analyse_script

    text = "CREATE INDEX i ON orders (id);"
    result = lint_analysis(
        analyse_script(text, "postgresql"), text, "postgresql", created_before={"orders"}
    )
    assert (result.verdict, result.findings) == (SAFE, ())


def test_lint_script_never_reports_an_existing_table_as_created():
    result = lint_script(
        "CREATE TABLE orders (id INT);\nCREATE INDEX i ON orders (id);",
        "postgresql",
        existing_tables={"orders"},
    )
    assert result.created_tables == frozenset()
    assert [f.code for f in result.findings] == [
        "pg-index-not-concurrent",
        "pg-missing-lock-timeout",
    ]


def test_lint_analysis_takes_the_existing_tables():
    from dblift.core.migration.sql.script_analysis import analyse_script

    text = "CREATE TABLE orders (id INT);\nDROP TABLE orders;"
    result = lint_analysis(analyse_script(text, "mysql"), text, "mysql", existing_tables={"orders"})
    assert (result.verdict, [f.code for f in result.findings]) == (UNSAFE, ["drop-table"])


_CREATE_ORDERS = "CREATE TABLE orders (id INT);"
_INDEX_ORDERS = "CREATE INDEX idx_orders_id ON orders (id);"


@pytest.fixture
def delta(tmp_path: Path) -> list:
    v1 = tmp_path / "V1__orders.sql"
    v1.write_text(_CREATE_ORDERS)
    v2 = tmp_path / "V2__index.sql"
    v2.write_text(_INDEX_ORDERS)
    return [v2, v1]


def test_lint_files_as_a_delta_knows_the_tables_earlier_files_created(delta):
    results = lint_files(delta, "postgresql", {}, MagicMock(), as_delta=True)

    assert [(r.script, r.verdict, r.findings) for r in results] == [
        ("V1__orders.sql", SAFE, ()),
        ("V2__index.sql", SAFE, ()),
    ]


def test_lint_files_as_a_delta_does_not_carry_existing_tables(delta):
    results = lint_files(
        delta, "postgresql", {}, MagicMock(), as_delta=True, existing_tables={"orders"}
    )

    assert [(r.script, r.verdict) for r in results] == [
        ("V1__orders.sql", SAFE),
        ("V2__index.sql", REVIEW),
    ]


def test_lint_files_alone_lints_each_file_by_itself_in_the_order_given(delta):
    results = lint_files(delta, "postgresql", {}, MagicMock())

    assert [r.script for r in results] == ["V2__index.sql", "V1__orders.sql"]
    assert [f.code for f in results[0].findings] == [
        "pg-index-not-concurrent",
        "pg-missing-lock-timeout",
    ]


def test_lint_files_as_a_delta_runs_in_apply_order(tmp_path: Path):
    names = ["U3__undo.sql", "R__b.sql", "V10__ten.sql", "notes.sql", "R__A.sql", "V2__two.sql"]
    for name in names:
        (tmp_path / name).write_text("SELECT 1;")

    results = lint_files([tmp_path / n for n in names], "mysql", {}, MagicMock(), as_delta=True)

    assert [r.script for r in results] == [
        "V2__two.sql",
        "V10__ten.sql",
        "R__A.sql",
        "R__b.sql",
        "U3__undo.sql",
        "notes.sql",
    ]


def _pending(name: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(type=MigrationType.SQL, script_name=name, content=content)


def test_pending_scripts_are_one_delta():
    pending = [_pending("V2__orders.sql", _CREATE_ORDERS), _pending("V3__i.sql", _INDEX_ORDERS)]

    analysed = lint_pending_scripts(pending, "postgresql", MagicMock())

    assert analysed["V3__i.sql"]["verdict"] == SAFE
    assert analysed["V3__i.sql"]["findings"] == []


def test_pending_scripts_do_not_carry_existing_tables():
    pending = [_pending("V2__orders.sql", _CREATE_ORDERS), _pending("V3__i.sql", _INDEX_ORDERS)]

    analysed = lint_pending_scripts(pending, "postgresql", MagicMock(), existing_tables={"orders"})

    assert analysed["V3__i.sql"]["verdict"] == REVIEW


def test_pending_scripts_can_be_linted_alone():
    pending = [_pending("V2__orders.sql", _CREATE_ORDERS), _pending("V3__i.sql", _INDEX_ORDERS)]

    analysed = lint_pending_scripts(pending, "postgresql", MagicMock(), as_delta=False)

    assert analysed["V3__i.sql"]["verdict"] == REVIEW


@pytest.fixture
def migration_tree(tmp_path: Path) -> Path:
    root = tmp_path / "migrations"
    nested = root / "later"
    nested.mkdir(parents=True)
    for name in (
        "V2__b.sql",
        "V1__a.sql",
        "R__view.sql",
        "v3__lower.sql",
        "U1__undo_a.sql",
        "B1__baseline.sql",
        "afterMigrate__notify.sql",
        "notes.sql",
        "V4__script.py",
    ):
        (root / name).write_text("SELECT 1;")
    (nested / "V5__nested.sql").write_text("SELECT 1;")
    return root


def test_lint_targets_are_the_v_and_r_sql_scripts_sorted(migration_tree):
    names = [p.name for p in lint_targets([migration_tree], recursive=False)]

    assert names == ["R__view.sql", "V1__a.sql", "V2__b.sql", "v3__lower.sql"]


def test_lint_targets_recurse_when_asked(migration_tree):
    paths = lint_targets([migration_tree], recursive=True)

    assert migration_tree / "later" / "V5__nested.sql" in paths
    assert paths == sorted(paths)


def test_lint_targets_per_directory_recursion_overrides_the_default(migration_tree, tmp_path):
    other = tmp_path / "other"
    (other / "deep").mkdir(parents=True)
    (other / "V9__top.sql").write_text("SELECT 1;")
    (other / "deep" / "V8__deep.sql").write_text("SELECT 1;")

    paths = lint_targets([migration_tree, other], recursive=False, recursive_by_dir={other: True})

    names = [p.name for p in paths]
    assert names == [
        "R__view.sql",
        "V1__a.sql",
        "V2__b.sql",
        "v3__lower.sql",
        "V9__top.sql",
        "V8__deep.sql",
    ]


def test_lint_targets_of_no_directory_is_empty():
    assert lint_targets([], recursive=True) == []

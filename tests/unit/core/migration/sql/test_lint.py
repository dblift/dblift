"""``lint``: the verdict of a script and the findings a script accepts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.sql.lint import (
    REVIEW,
    SAFE,
    UNSAFE,
    allowed_codes,
    lint_files,
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

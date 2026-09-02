from pathlib import Path
from types import SimpleNamespace

from dblift.core.sql_model.base import ConstraintType


def test_metadata_helpers_are_available_from_new_module_and_legacy_extractors():
    from dblift.core.introspection.extractors import (
        constraint_extractor,
        index_extractor,
        procedure_extractor,
    )
    from dblift.core.utils import metadata_helpers

    assert (
        index_extractor.normalize_postgresql_index_predicate
        is metadata_helpers.normalize_postgresql_index_predicate
    )
    assert (
        constraint_extractor._build_unique_constraints_from_dict
        is metadata_helpers._build_unique_constraints_from_dict
    )
    assert (
        procedure_extractor._fetch_mysql_show_create_routine
        is metadata_helpers._fetch_mysql_show_create_routine
    )


def test_plugin_quirks_import_metadata_helpers_instead_of_rich_extractors():
    repo_root = Path(__file__).resolve().parents[5]
    for quirks_path in repo_root.glob("dblift/db/plugins/*/quirks.py"):
        assert "dblift.core.introspection.extractors" not in quirks_path.read_text()


def test_build_unique_constraints_from_dict_from_new_module_preserves_behavior():
    from dblift.core.utils.metadata_helpers import _build_unique_constraints_from_dict

    extractor = SimpleNamespace(
        dialect="postgresql",
        _sanitize_constraint_name=lambda name: f"clean_{name}",
    )
    constraints = _build_unique_constraints_from_dict(
        extractor,
        {
            "idx": {
                "name": "users_email_key",
                "columns": [
                    {"column": "email", "position": 2},
                    {"column": "tenant_id", "position": 1},
                ],
            }
        },
    )

    assert len(constraints) == 1
    assert constraints[0].constraint_type == ConstraintType.UNIQUE
    assert constraints[0].name == "clean_users_email_key"
    assert constraints[0].column_names == ["tenant_id", "email"]
    assert constraints[0].dialect == "postgresql"


def test_fetch_mysql_show_create_routine_from_new_module_preserves_behavior():
    from dblift.core.utils.metadata_helpers import _fetch_mysql_show_create_routine

    class QueryExecutor:
        def execute_query(self, connection, sql, params):
            assert connection == "connection"
            assert sql == "SHOW CREATE PROCEDURE `app``schema`.`do``work`"
            assert params == []
            return [{"Create Procedure": "CREATE PROCEDURE app.do_work() BEGIN SELECT 1; END"}]

    extractor = SimpleNamespace(
        connection="connection",
        log=SimpleNamespace(debug=lambda message: None),
        provider=SimpleNamespace(query_executor=QueryExecutor()),
        result_tracker=None,
    )

    assert (
        _fetch_mysql_show_create_routine(
            extractor,
            "app`schema",
            "do`work",
            "procedure",
        )
        == "CREATE PROCEDURE app.do_work() BEGIN SELECT 1; END"
    )

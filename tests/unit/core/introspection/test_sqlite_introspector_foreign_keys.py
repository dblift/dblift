from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.logger import NullLog
from core.sql_model.base import ConstraintType
from db.plugins.sqlite.introspection.sqlite_introspector import SQLiteIntrospector


@pytest.mark.unit
class TestSQLiteIntrospectorForeignKeys:
    def test_deduplicates_duplicate_logical_foreign_keys_from_pragma(self):
        provider = SimpleNamespace(
            config=SimpleNamespace(database=SimpleNamespace(type="sqlite")),
            execute_query=MagicMock(
                return_value=[
                    {
                        "id": 0,
                        "seq": 0,
                        "table": "departments",
                        "from": "dept_id",
                        "to": "id",
                        "on_update": "NO ACTION",
                        "on_delete": "NO ACTION",
                    },
                    {
                        "id": 1,
                        "seq": 0,
                        "table": "departments",
                        "from": "dept_id",
                        "to": "id",
                        "on_update": "NO ACTION",
                        "on_delete": "NO ACTION",
                    },
                ]
            ),
        )
        introspector = SQLiteIntrospector(provider, log=NullLog(), use_vendor_queries=False)

        constraints = introspector._get_foreign_keys("employees")

        assert len(constraints) == 1
        fk = constraints[0]
        assert fk.constraint_type == ConstraintType.FOREIGN_KEY
        assert fk.name == "fk_employees_0"
        assert fk.column_names == ["dept_id"]
        assert fk.reference_table == "departments"
        assert fk.reference_columns == ["id"]

    def test_orders_composite_foreign_key_columns_by_pragma_sequence(self):
        provider = SimpleNamespace(
            config=SimpleNamespace(database=SimpleNamespace(type="sqlite")),
            execute_query=MagicMock(
                return_value=[
                    {
                        "id": 0,
                        "seq": 1,
                        "table": "regions",
                        "from": "region_code",
                        "to": "region_code",
                        "on_update": "NO ACTION",
                        "on_delete": "NO ACTION",
                    },
                    {
                        "id": 0,
                        "seq": 0,
                        "table": "regions",
                        "from": "country_code",
                        "to": "country_code",
                        "on_update": "NO ACTION",
                        "on_delete": "NO ACTION",
                    },
                ]
            ),
        )
        introspector = SQLiteIntrospector(provider, log=NullLog(), use_vendor_queries=False)

        constraints = introspector._get_foreign_keys("locations")

        assert len(constraints) == 1
        assert constraints[0].column_names == ["country_code", "region_code"]
        assert constraints[0].reference_columns == ["country_code", "region_code"]

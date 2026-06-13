"""BUG-01 regression: MySQL FUNCTION must not be silently dropped from export.

MySQL's ``information_schema.ROUTINES.ROUTINE_DEFINITION`` is the function
*body* (``BEGIN…END``), not the full ``CREATE FUNCTION`` DDL. The base
``vendor_queries.get_function_definition_query`` returns ``(None, [])``,
so the ``if not def_sql: continue`` branch in ``get_functions`` dropped
the function entirely instead of appending it with the body it already
had. Procedures worked because they had a dialect-specific
``SHOW CREATE PROCEDURE`` fallback — functions had none.

The fix (1) adds a ``SHOW CREATE FUNCTION`` fallback for MySQL and
(2) stops skipping the append when the vendor has no definition query.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.introspection.extractors.procedure_extractor import ProcedureExtractor


def _make_extractor(dialect: str = "mysql") -> ProcedureExtractor:
    ext = ProcedureExtractor.__new__(ProcedureExtractor)
    ext.dialect = dialect
    ext.log = MagicMock()
    ext.provider = MagicMock()
    ext.connection = MagicMock()
    ext.result_tracker = None
    ext.vendor_queries = MagicMock()
    ext.vendor_queries.supports_functions.return_value = True
    ext.vendor_queries.get_functions_query.return_value = ("SELECT ...", [])
    # No arguments metadata path — skip the optional branch.
    del ext.vendor_queries.get_function_arguments_query
    # Base vendor returns (None, []) for function definition — the bug trigger.
    ext.vendor_queries.get_function_definition_query.return_value = (None, [])
    ext.ensure_metadata = MagicMock()
    return ext


@pytest.mark.unit
class TestMysqlFunctionShowCreateFallback:
    def test_function_is_kept_when_vendor_has_no_definition_query(self):
        """Before the fix, base (None, []) → `continue` → function dropped."""
        ext = _make_extractor("mysql")

        ext.provider.query_executor.execute_query.side_effect = [
            # First call: get_functions_query
            [
                {
                    "function_name": "get_dept_budget",
                    "definition": "BEGIN RETURN 1; END",
                    "language": "SQL",
                    "is_deterministic": "YES",
                }
            ],
            # Second call: SHOW CREATE FUNCTION
            [
                {
                    "Create Function": (
                        "CREATE DEFINER=`root`@`%` FUNCTION `get_dept_budget`() "
                        "RETURNS decimal(10,2) BEGIN RETURN 1; END"
                    )
                }
            ],
        ]

        functions = ext.get_functions("dblift_test")

        assert len(functions) == 1, "function must not be silently dropped"
        assert functions[0].name == "get_dept_budget"

    def test_show_create_function_populates_definition(self):
        ext = _make_extractor("mysql")
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": "BEGIN RETURN 1; END"}],
            [{"Create Function": "CREATE FUNCTION `fn`() RETURNS INT BEGIN RETURN 1; END"}],
        ]

        fns = ext.get_functions("s")

        assert fns[0].definition.startswith("CREATE FUNCTION")

    def test_show_create_function_failure_still_keeps_function(self):
        """Even if SHOW CREATE raises, the function must be exported."""
        ext = _make_extractor("mysql")
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": "BEGIN RETURN 1; END"}],
            RuntimeError("permission denied for SHOW CREATE FUNCTION"),
        ]

        fns = ext.get_functions("s")

        assert len(fns) == 1

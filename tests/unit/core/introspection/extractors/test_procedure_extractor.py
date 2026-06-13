"""Tests for ProcedureExtractor."""

import unittest
from unittest.mock import MagicMock


def _make_extractor(dialect="postgresql", vendor_queries=None):
    from core.introspection.extractors.procedure_extractor import ProcedureExtractor

    provider = MagicMock()
    provider.query_executor = MagicMock()
    ext = ProcedureExtractor(provider=provider, dialect=dialect, vendor_queries=vendor_queries)
    ext.ensure_metadata = MagicMock()
    ext.metadata = MagicMock()
    ext.connection = MagicMock()
    ext.log = MagicMock()
    return ext


class TestExtractDefinitionParts(unittest.TestCase):
    def test_none_returns_none_none(self):
        from core.introspection.extractors.procedure_extractor import _extract_definition_parts

        self.assertEqual(_extract_definition_parts(None), (None, None))

    def test_empty_string(self):
        from core.introspection.extractors.procedure_extractor import _extract_definition_parts

        self.assertEqual(_extract_definition_parts(""), (None, None))

    def test_with_as_keyword(self):
        from core.introspection.extractors.procedure_extractor import _extract_definition_parts

        defn = "CREATE PROCEDURE foo AS BEGIN SELECT 1 END"
        full, body = _extract_definition_parts(defn)
        self.assertIsNotNone(full)
        self.assertIn("BEGIN", body)

    def test_without_as_keyword(self):
        from core.introspection.extractors.procedure_extractor import _extract_definition_parts

        defn = "CREATE PROCEDURE foo()"
        full, body = _extract_definition_parts(defn)
        self.assertIsNotNone(full)
        self.assertIsNone(body)


class TestIsFullDefinition(unittest.TestCase):
    def test_create_is_full(self):
        from core.introspection.extractors.procedure_extractor import _is_full_definition

        self.assertTrue(_is_full_definition("CREATE PROCEDURE foo"))

    def test_alter_is_full(self):
        from core.introspection.extractors.procedure_extractor import _is_full_definition

        self.assertTrue(_is_full_definition("ALTER PROCEDURE foo"))

    def test_replace_is_full(self):
        from core.introspection.extractors.procedure_extractor import _is_full_definition

        self.assertTrue(_is_full_definition("REPLACE PROCEDURE foo"))

    def test_partial_not_full(self):
        from core.introspection.extractors.procedure_extractor import _is_full_definition

        self.assertFalse(_is_full_definition("BEGIN SELECT 1 END"))

    def test_none_false(self):
        from core.introspection.extractors.procedure_extractor import _is_full_definition

        self.assertFalse(_is_full_definition(None))

    def test_empty_false(self):
        from core.introspection.extractors.procedure_extractor import _is_full_definition

        self.assertFalse(_is_full_definition(""))


class TestCleanOracleSourceText(unittest.TestCase):
    """Oracle source-text cleaning lives on :class:`OracleQuirks` now.
    Tests target the canonical hook directly."""

    @staticmethod
    def _quirks():
        from db.plugins.oracle.quirks import OracleQuirks

        return OracleQuirks()

    def test_none_returns_none(self):
        self.assertIsNone(self._quirks().clean_source_text(None))

    def test_removes_e_tags(self):
        result = self._quirks().clean_source_text("<E>line1</E><E>line2</E>")
        self.assertNotIn("<E>", result)
        self.assertIn("line1", result)
        self.assertIn("line2", result)

    def test_replaces_e_e_with_newline(self):
        result = self._quirks().clean_source_text("<E>line1</E><E>line2</E>")
        self.assertIn("\n", result)

    def test_unescapes_html_entities(self):
        result = self._quirks().clean_source_text("a &amp; b &lt; c")
        self.assertIn("&", result)
        self.assertIn("<", result)


class TestBuildParametersFromJson(unittest.TestCase):
    def test_empty_returns_empty(self):
        ext = _make_extractor()
        result = ext._build_parameters_from_json(None)
        self.assertEqual(result, [])

    def test_valid_json_array(self):
        import json

        ext = _make_extractor()
        params = [{"name": "p1", "data_type": "INT", "mode": "IN"}]
        result = ext._build_parameters_from_json(json.dumps(params))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "p1")
        self.assertEqual(result[0].data_type, "INT")

    def test_generates_param_name_when_missing(self):
        import json

        ext = _make_extractor()
        params = [{"data_type": "VARCHAR"}]
        result = ext._build_parameters_from_json(json.dumps(params))
        self.assertEqual(len(result), 1)
        self.assertIn("param_", result[0].name)


class TestGetProceduresNoVendorQueries(unittest.TestCase):
    def test_returns_empty_without_vendor_queries(self):
        ext = _make_extractor()
        result = ext.get_procedures("public")
        self.assertEqual(result, [])


class TestGetProceduresWithVendorQueries(unittest.TestCase):
    def _make_vq(self):
        vq = MagicMock()
        vq.get_procedures_query.return_value = ("SELECT 1", ["public"])
        return vq

    def test_returns_empty_when_no_rows(self):
        vq = self._make_vq()
        ext = _make_extractor(vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = []
        result = ext.get_procedures("public")
        self.assertEqual(result, [])

    def test_processes_rows(self):
        vq = self._make_vq()
        ext = _make_extractor(vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {
                "procedure_name": "sp_test",
                "procedure_type": "PROCEDURE",
                "definition": "CREATE PROCEDURE sp_test AS BEGIN SELECT 1 END",
                "schema_name": "public",
                "parameters": None,
                "comment": None,
                "return_type": None,
                "is_deterministic": False,
                "security_type": None,
                "data_access": None,
            }
        ]
        result = ext.get_procedures("public")
        self.assertIsInstance(result, list)

    def test_skips_system_procs(self):
        vq = self._make_vq()
        ext = _make_extractor(vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {
                "procedure_name": "sys_proc",
                "procedure_type": "PROCEDURE",
                "definition": None,
                "schema_name": "sys",
                "parameters": None,
                "comment": None,
                "return_type": None,
                "is_deterministic": False,
                "security_type": None,
                "data_access": None,
            }
        ]
        # Should not crash
        result = ext.get_procedures("public")
        self.assertIsInstance(result, list)

    def test_handles_exception(self):
        vq = self._make_vq()
        ext = _make_extractor(vendor_queries=vq)
        ext.provider.query_executor.execute_query.side_effect = Exception("DB error")
        result = ext.get_procedures("public")
        self.assertEqual(result, [])


class TestGetFunctions(unittest.TestCase):
    def test_returns_empty_without_vendor_queries(self):
        ext = _make_extractor()
        result = ext.get_functions("public")
        self.assertEqual(result, [])

    def test_with_vendor_queries_no_rows(self):
        vq = MagicMock()
        vq.get_functions_query.return_value = ("SELECT 1", ["public"])
        ext = _make_extractor(vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = []
        result = ext.get_functions("public")
        self.assertEqual(result, [])


class TestGetTriggers(unittest.TestCase):
    def test_returns_empty_without_vendor_queries(self):
        # ProcedureExtractor does not have get_triggers — verify no AttributeError is expected
        # This test is kept as a placeholder indicating get_triggers is not part of this extractor.
        from core.introspection.extractors.procedure_extractor import ProcedureExtractor

        self.assertFalse(hasattr(ProcedureExtractor, "get_triggers"))


# ---------------------------------------------------------------------------
# Additional tests to cover missing lines
# ---------------------------------------------------------------------------


class TestExtractDefinitionPartsEdgeCases(unittest.TestCase):
    """Cover lines 35 (whitespace-only after strip_leading_comments) and 43 (EXECUTE AS skip)."""

    def test_whitespace_only_returns_none_none(self):
        from core.introspection.extractors.procedure_extractor import _extract_definition_parts

        # After strip_leading_comments, the remaining text is blank → (None, None)
        result = _extract_definition_parts("   ")
        self.assertEqual(result, (None, None))

    def test_execute_as_preceding_is_skipped(self):
        """EXECUTE AS should not be treated as the body delimiter."""
        from core.introspection.extractors.procedure_extractor import _extract_definition_parts

        defn = "CREATE PROCEDURE foo EXECUTE AS CALLER AS BEGIN SELECT 1 END"
        full, body = _extract_definition_parts(defn)
        # The second AS (after EXECUTE AS CALLER) must produce a body
        self.assertIsNotNone(body)
        self.assertIn("BEGIN", body)

    def test_definition_with_only_execute_as_no_body_as(self):
        """Definition containing only EXECUTE AS and no body AS keyword."""
        from core.introspection.extractors.procedure_extractor import _extract_definition_parts

        defn = "EXECUTE AS CALLER"
        full, body = _extract_definition_parts(defn)
        # No trailing AS → body should be None
        self.assertIsNotNone(full)
        self.assertIsNone(body)


class TestBuildParametersFromJsonNonDict(unittest.TestCase):
    """Cover line 92: entry is not a dict → continue."""

    def test_non_dict_entries_are_skipped(self):
        import json

        ext = _make_extractor()
        # Mix of non-dict and valid dict entries
        raw = json.dumps(["not_a_dict", {"name": "p1", "data_type": "INT", "mode": "IN"}])
        result = ext._build_parameters_from_json(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "p1")

    def test_default_values_from_json(self):
        import json

        ext = _make_extractor()
        raw = json.dumps(
            [{"name": "p1", "data_type": "VARCHAR", "mode": "IN", "default_value": "'hello'"}]
        )
        result = ext._build_parameters_from_json(raw)
        self.assertEqual(result[0].default_value, "'hello'")

    def test_default_falls_back_to_default_key(self):
        import json

        ext = _make_extractor()
        raw = json.dumps([{"name": "p1", "data_type": "INT", "mode": "IN", "default": "42"}])
        result = ext._build_parameters_from_json(raw)
        self.assertEqual(result[0].default_value, "42")


class TestFetchMysqlRoutineParameters(unittest.TestCase):
    """Cover lines 111, 117-142."""

    def test_no_vendor_queries_returns_empty(self):
        ext = _make_extractor(dialect="mysql")
        ext.vendor_queries = None
        result = ext._fetch_mysql_routine_parameters("mydb", "my_proc")
        self.assertEqual(result, [])

    def test_no_query_from_vendor_returns_empty(self):
        ext = _make_extractor(dialect="mysql")
        vq = MagicMock()
        vq.get_parameters_query.return_value = (None, [])
        ext.vendor_queries = vq
        result = ext._fetch_mysql_routine_parameters("mydb", "my_proc")
        self.assertEqual(result, [])

    def test_returns_sorted_parameters(self):
        ext = _make_extractor(dialect="mysql")
        vq = MagicMock()
        vq.get_parameters_query.return_value = ("SELECT ...", [])
        ext.vendor_queries = vq
        ext.provider.query_executor.execute_query.return_value = [
            {
                "ordinal_position": "2",
                "param_name": "p2",
                "parameter_type": "INT",
                "param_mode": "IN",
            },
            {
                "ordinal_position": "1",
                "param_name": "p1",
                "parameter_type": "VARCHAR",
                "param_mode": "IN",
            },
        ]
        result = ext._fetch_mysql_routine_parameters("mydb", "my_proc")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].name, "p1")
        self.assertEqual(result[1].name, "p2")

    def test_uses_data_type_fallback(self):
        ext = _make_extractor(dialect="mysql")
        vq = MagicMock()
        vq.get_parameters_query.return_value = ("SELECT ...", [])
        ext.vendor_queries = vq
        ext.provider.query_executor.execute_query.return_value = [
            {"ordinal_position": "1", "param_name": "p1", "data_type": "TEXT", "param_mode": "OUT"},
        ]
        result = ext._fetch_mysql_routine_parameters("mydb", "my_proc")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].data_type, "TEXT")
        self.assertEqual(result[0].direction, "OUT")

    def test_generates_name_when_missing(self):
        ext = _make_extractor(dialect="mysql")
        vq = MagicMock()
        vq.get_parameters_query.return_value = ("SELECT ...", [])
        ext.vendor_queries = vq
        ext.provider.query_executor.execute_query.return_value = [
            {
                "ordinal_position": "3",
                "param_name": None,
                "parameter_type": "INT",
                "param_mode": "IN",
            },
        ]
        result = ext._fetch_mysql_routine_parameters("mydb", "my_proc")
        self.assertEqual(len(result), 1)
        self.assertIn("param_", result[0].name)

    def test_exception_returns_empty(self):
        ext = _make_extractor(dialect="mysql")
        vq = MagicMock()
        vq.get_parameters_query.return_value = ("SELECT ...", [])
        ext.vendor_queries = vq
        ext.provider.query_executor.execute_query.side_effect = Exception("DB error")
        result = ext._fetch_mysql_routine_parameters("mydb", "my_proc")
        self.assertEqual(result, [])


class TestFetchOracleProcedureParameters(unittest.TestCase):
    """Cover lines 148-209."""

    def test_no_vendor_queries_returns_empty(self):
        ext = _make_extractor(dialect="oracle")
        ext.vendor_queries = None
        result = ext._fetch_oracle_procedure_parameters("myschema", "MY_PROC")
        self.assertEqual(result, [])

    def test_none_query_returns_empty(self):
        ext = _make_extractor(dialect="oracle")
        vq = MagicMock()
        vq.get_procedure_arguments_query.return_value = (None, [])
        ext.vendor_queries = vq
        result = ext._fetch_oracle_procedure_parameters("myschema", "MY_PROC")
        self.assertEqual(result, [])

    def test_returns_sorted_parameters_with_in_out_mapping(self):
        ext = _make_extractor(dialect="oracle")
        vq = MagicMock()
        vq.get_procedure_arguments_query.return_value = ("SELECT ...", [])
        ext.vendor_queries = vq
        ext.provider.query_executor.execute_query.return_value = [
            {"position": "2", "argument_name": "p2", "data_type": "NUMBER", "in_out": "OUT"},
            {"position": "1", "argument_name": "p1", "data_type": "VARCHAR2", "in_out": "IN"},
            {"position": "3", "argument_name": "p3", "data_type": "DATE", "in_out": "IN/OUT"},
        ]
        result = ext._fetch_oracle_procedure_parameters("MYSCHEMA", "MY_PROC")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].name, "p1")
        self.assertEqual(result[0].direction, "IN")
        self.assertEqual(result[1].name, "p2")
        self.assertEqual(result[1].direction, "OUT")
        self.assertEqual(result[2].name, "p3")
        self.assertEqual(result[2].direction, "INOUT")

    def test_unknown_in_out_defaults_to_in(self):
        ext = _make_extractor(dialect="oracle")
        vq = MagicMock()
        vq.get_procedure_arguments_query.return_value = ("SELECT ...", [])
        ext.vendor_queries = vq
        ext.provider.query_executor.execute_query.return_value = [
            {"position": "1", "argument_name": "p1", "data_type": "VARCHAR2", "in_out": "UNKNOWN"},
        ]
        result = ext._fetch_oracle_procedure_parameters("MYSCHEMA", "MY_PROC")
        self.assertEqual(result[0].direction, "IN")

    def test_uppercase_column_names_work(self):
        ext = _make_extractor(dialect="oracle")
        vq = MagicMock()
        vq.get_procedure_arguments_query.return_value = ("SELECT ...", [])
        ext.vendor_queries = vq
        ext.provider.query_executor.execute_query.return_value = [
            {"POSITION": "1", "ARGUMENT_NAME": "P_NAME", "DATA_TYPE": "CLOB", "IN_OUT": "IN"},
        ]
        result = ext._fetch_oracle_procedure_parameters("MYSCHEMA", "MY_PROC")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "P_NAME")

    def test_exception_returns_empty(self):
        ext = _make_extractor(dialect="oracle")
        vq = MagicMock()
        vq.get_procedure_arguments_query.return_value = ("SELECT ...", [])
        ext.vendor_queries = vq
        ext.provider.query_executor.execute_query.side_effect = Exception("ORA-0000")
        result = ext._fetch_oracle_procedure_parameters("MYSCHEMA", "MY_PROC")
        self.assertEqual(result, [])


class TestFetchOracleDdl(unittest.TestCase):
    """Cover lines 213-233."""

    def test_returns_ddl_from_query(self):
        ext = _make_extractor(dialect="oracle")
        ext.provider.query_executor.execute_query.return_value = [
            {"definition": "CREATE OR REPLACE PROCEDURE MY_PROC AS BEGIN NULL; END;"}
        ]
        result = ext._fetch_oracle_ddl("PROCEDURE", "MY_PROC", "MYSCHEMA")
        self.assertIsNotNone(result)
        self.assertIn("CREATE", result)

    def test_empty_rows_returns_none(self):
        ext = _make_extractor(dialect="oracle")
        ext.provider.query_executor.execute_query.return_value = []
        result = ext._fetch_oracle_ddl("PROCEDURE", "MY_PROC", "MYSCHEMA")
        self.assertIsNone(result)

    def test_none_definition_returns_none(self):
        ext = _make_extractor(dialect="oracle")
        ext.provider.query_executor.execute_query.return_value = [{"definition": None}]
        result = ext._fetch_oracle_ddl("PROCEDURE", "MY_PROC", "MYSCHEMA")
        self.assertIsNone(result)

    def test_exception_returns_none(self):
        ext = _make_extractor(dialect="oracle")
        ext.provider.query_executor.execute_query.side_effect = Exception("ORA-01031")
        result = ext._fetch_oracle_ddl("PROCEDURE", "MY_PROC", "MYSCHEMA")
        self.assertIsNone(result)

    def test_normalizes_identifiers_to_uppercase(self):
        ext = _make_extractor(dialect="oracle")
        captured = {}

        def fake_query(conn, sql, params):
            captured["params"] = params
            return [{"definition": "CREATE PROCEDURE MYSCHEMA.MY_PROC AS BEGIN NULL; END;"}]

        ext.provider.query_executor.execute_query.side_effect = fake_query
        ext._fetch_oracle_ddl("procedure", "my_proc", "myschema")
        self.assertEqual(captured["params"], ["PROCEDURE", "MY_PROC", "MYSCHEMA"])


class TestFetchOracleSourceText(unittest.TestCase):
    """Cover lines 239-263."""

    def test_no_query_executor_returns_none(self):
        ext = _make_extractor(dialect="oracle")
        ext.provider.query_executor = None
        result = ext._fetch_oracle_source_text("MYSCHEMA", "MY_PROC", "PROCEDURE")
        self.assertIsNone(result)

    def test_returns_concatenated_lines(self):
        ext = _make_extractor(dialect="oracle")
        ext.provider.query_executor.execute_query.return_value = [
            {"text": "CREATE OR REPLACE PROCEDURE MY_PROC AS\n"},
            {"text": "BEGIN NULL; END;\n"},
        ]
        result = ext._fetch_oracle_source_text("MYSCHEMA", "MY_PROC", "PROCEDURE")
        self.assertIn("CREATE", result)
        self.assertIn("BEGIN", result)

    def test_empty_rows_returns_none(self):
        ext = _make_extractor(dialect="oracle")
        ext.provider.query_executor.execute_query.return_value = []
        result = ext._fetch_oracle_source_text("MYSCHEMA", "MY_PROC", "PROCEDURE")
        self.assertIsNone(result)

    def test_exception_returns_none(self):
        ext = _make_extractor(dialect="oracle")
        ext.provider.query_executor.execute_query.side_effect = Exception("access denied")
        result = ext._fetch_oracle_source_text("MYSCHEMA", "MY_PROC", "PROCEDURE")
        self.assertIsNone(result)

    def test_all_whitespace_rows_returns_none(self):
        ext = _make_extractor(dialect="oracle")
        ext.provider.query_executor.execute_query.return_value = [{"text": "   "}, {"text": "\n"}]
        result = ext._fetch_oracle_source_text("MYSCHEMA", "MY_PROC", "PROCEDURE")
        self.assertIsNone(result)


class TestStripEmbeddedOraclePackageSpec(unittest.TestCase):
    """Cover lines 269-292."""

    def test_no_package_returns_definition_unchanged(self):
        ext = _make_extractor(dialect="oracle")
        defn = "CREATE OR REPLACE PROCEDURE MY_PROC AS BEGIN NULL; END;"
        result = ext._strip_embedded_oracle_package_spec("MYSCHEMA", defn)
        self.assertEqual(result, defn)

    def test_package_spec_is_stripped_and_cached(self):
        ext = _make_extractor(dialect="oracle")
        defn = (
            "CREATE OR REPLACE PROCEDURE MY_PROC AS BEGIN NULL; END;\n"
            "CREATE OR REPLACE PACKAGE MY_PKG AS PROCEDURE helper; END MY_PKG;"
        )
        result = ext._strip_embedded_oracle_package_spec("MYSCHEMA", defn)
        # The package spec should be cached
        self.assertIn(("MYSCHEMA", "MY_PKG"), ext._oracle_package_specs)
        # The returned text should not contain the package
        self.assertNotIn("CREATE OR REPLACE PACKAGE", result)

    def test_package_only_definition_returns_none(self):
        ext = _make_extractor(dialect="oracle")
        defn = "CREATE OR REPLACE PACKAGE MY_PKG AS PROCEDURE helper; END MY_PKG;"
        result = ext._strip_embedded_oracle_package_spec("MYSCHEMA", defn)
        # Nothing before the package → cleaned becomes empty → returns None
        self.assertIsNone(result)

    def test_no_match_for_package_name_returns_definition(self):
        """CREATE OR REPLACE PACKAGE present but regex can't find name → return as-is."""
        ext = _make_extractor(dialect="oracle")
        # Malformed so the regex won't match the name
        defn = "SOME BODY\nCREATE OR REPLACE PACKAGE"
        result = ext._strip_embedded_oracle_package_spec("MYSCHEMA", defn)
        self.assertEqual(result, defn)


class TestGetProceduresMysqlDialect(unittest.TestCase):
    """Cover MySQL-specific branches in get_procedures (lines 312-439)."""

    def _make_mysql_vq(self):
        vq = MagicMock()
        vq.supports_procedures.return_value = True
        vq.get_procedures_query.return_value = ("SELECT ...", [])
        return vq

    def _base_row(self, **kwargs):
        row = {
            "procedure_name": "sp_test",
            "definition": None,
            "parameter_json": None,
            "is_deterministic": "YES",
            "security_type": "DEFINER",
            "data_access": "READS SQL DATA",
            "definer": "root@localhost",
            "volatility": None,
            "execute_as_principal": None,
        }
        row.update(kwargs)
        return row

    def test_mysql_volatility_immutable(self):
        vq = self._make_mysql_vq()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.side_effect = [
            [self._base_row()],  # main query
            [],  # SHOW CREATE PROCEDURE → no rows
        ]
        result = ext.get_procedures("mydb")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].volatility, "IMMUTABLE")

    def test_mysql_volatility_volatile(self):
        vq = self._make_mysql_vq()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.side_effect = [
            [self._base_row(is_deterministic="NO")],
            [],
        ]
        result = ext.get_procedures("mydb")
        self.assertEqual(result[0].volatility, "VOLATILE")

    def test_mysql_security_definer_yes(self):
        vq = self._make_mysql_vq()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.side_effect = [
            [self._base_row(security_type="DEFINER")],
            [],
        ]
        result = ext.get_procedures("mydb")
        self.assertTrue(result[0].security_definer)

    def test_mysql_definer_set(self):
        vq = self._make_mysql_vq()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.side_effect = [
            [self._base_row(definer="admin@%")],
            [],
        ]
        result = ext.get_procedures("mydb")
        self.assertEqual(result[0].definer, "admin@%")

    def test_mysql_data_access_set(self):
        vq = self._make_mysql_vq()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.side_effect = [
            [self._base_row(data_access="MODIFIES SQL DATA")],
            [],
        ]
        result = ext.get_procedures("mydb")
        self.assertEqual(result[0].data_access, "MODIFIES SQL DATA")

    def test_mysql_show_create_procedure_populates_definition(self):
        vq = self._make_mysql_vq()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        create_stmt = "CREATE DEFINER=`root`@`%` PROCEDURE `sp_test`() BEGIN SELECT 1; END"
        ext.provider.query_executor.execute_query.side_effect = [
            [self._base_row()],
            [{"Create Procedure": create_stmt}],
        ]
        result = ext.get_procedures("mydb")
        self.assertEqual(result[0].definition, create_stmt)
        self.assertIsNotNone(result[0].body)
        self.assertIn("BEGIN", result[0].body)

    def test_mysql_show_create_procedure_lowercase_key(self):
        vq = self._make_mysql_vq()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        create_stmt = "CREATE PROCEDURE `sp_test`() BEGIN SELECT 1; END"
        ext.provider.query_executor.execute_query.side_effect = [
            [self._base_row()],
            [{"create procedure": create_stmt}],
        ]
        result = ext.get_procedures("mydb")
        self.assertEqual(result[0].definition, create_stmt)

    def test_mysql_show_create_procedure_exception_logs_debug(self):
        vq = self._make_mysql_vq()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.side_effect = [
            [self._base_row()],
            RuntimeError("permission denied"),
        ]
        result = ext.get_procedures("mydb")
        # Should still return the procedure
        self.assertEqual(len(result), 1)
        ext.log.debug.assert_called()

    def test_mysql_execute_as_owner_in_definition(self):
        """EXECUTE AS OWNER in definition sets definer=OWNER (when no MySQL-specific definer row)."""
        vq = self._make_mysql_vq()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        # No "definer" key in row so MySQL definer-override branch is skipped
        row = {
            "procedure_name": "sp_test",
            "definition": "CREATE PROCEDURE foo EXECUTE AS OWNER AS BEGIN SELECT 1 END",
            "parameter_json": None,
            "is_deterministic": "YES",
            "security_type": "DEFINER",
            "data_access": None,
            # Intentionally no "definer" key
            "volatility": None,
            "execute_as_principal": None,
        }
        ext.provider.query_executor.execute_query.side_effect = [
            [row],
            [],
        ]
        result = ext.get_procedures("mydb")
        self.assertEqual(len(result), 1)
        # definition contains EXECUTE AS OWNER → definer = OWNER
        self.assertEqual(result[0].definer, "OWNER")
        self.assertTrue(result[0].security_definer)

    def test_mysql_execute_as_principal_set(self):
        """execute_as_principal from row sets definer (when no MySQL-specific definer row)."""
        vq = self._make_mysql_vq()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        row = {
            "procedure_name": "sp_test",
            "definition": None,
            "parameter_json": None,
            "is_deterministic": "YES",
            "security_type": "DEFINER",
            "data_access": None,
            # No "definer" key so MySQL override is skipped
            "volatility": None,
            "execute_as_principal": "dbo",
        }
        ext.provider.query_executor.execute_query.side_effect = [
            [row],
            [],
        ]
        result = ext.get_procedures("mydb")
        # MySQL override (no definer key) → execute_as_principal wins
        self.assertEqual(result[0].definer, "dbo")
        self.assertTrue(result[0].security_definer)

    def test_mysql_skips_row_without_procedure_name(self):
        vq = self._make_mysql_vq()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {"procedure_name": None, "definition": None},
        ]
        result = ext.get_procedures("mydb")
        self.assertEqual(result, [])

    def test_mysql_result_tracker_tracks_status(self):
        vq = self._make_mysql_vq()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        tracker = MagicMock()
        proc_status = MagicMock()
        tracker._track_object_status.return_value = proc_status
        ext.result_tracker = tracker
        ext.provider.query_executor.execute_query.side_effect = [
            [self._base_row()],
            [],
        ]
        result = ext.get_procedures("mydb")
        tracker._track_object_status.assert_called_once_with("procedure", "sp_test", "mydb")
        proc_status.add_property_status.assert_called()

    def test_get_procedures_returns_empty_when_sql_is_none(self):
        vq = MagicMock()
        vq.supports_procedures.return_value = True
        vq.get_procedures_query.return_value = (None, [])
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        result = ext.get_procedures("mydb")
        self.assertEqual(result, [])

    def test_get_procedures_exception_with_result_tracker(self):
        vq = MagicMock()
        vq.supports_procedures.return_value = True
        vq.get_procedures_query.return_value = ("SELECT ...", [])
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        tracker = MagicMock()
        ext.result_tracker = tracker
        ext.provider.query_executor.execute_query.side_effect = Exception("fatal")
        result = ext.get_procedures("mydb")
        self.assertEqual(result, [])
        tracker._track_error.assert_called_once()


class TestGetProceduresOracleDialect(unittest.TestCase):
    """Cover Oracle-specific branches in get_procedures (lines 450-474)."""

    def _make_oracle_vq(self):
        vq = MagicMock()
        vq.supports_procedures.return_value = True
        vq.get_procedures_query.return_value = ("SELECT ...", [])
        return vq

    def _base_row(self, **kwargs):
        row = {
            "procedure_name": "MY_PROC",
            "definition": None,
            "parameter_json": None,
            "volatility": None,
            "execute_as_principal": None,
        }
        row.update(kwargs)
        return row

    def test_oracle_fetches_ddl_and_sets_definition(self):
        vq = self._make_oracle_vq()
        ext = _make_extractor(dialect="oracle", vendor_queries=vq)
        ddl = "CREATE OR REPLACE PROCEDURE MY_PROC AS BEGIN NULL; END;"
        ext.provider.query_executor.execute_query.side_effect = [
            [self._base_row()],  # main query
            [],  # _fetch_oracle_procedure_parameters (no vendor_queries.get_procedure_arguments_query)
            [{"definition": ddl}],  # _fetch_oracle_ddl
        ]
        vq.get_procedure_arguments_query = MagicMock(return_value=("SELECT ...", []))
        # Override the parameter query to return empty
        call_count = [0]
        orig_side = ext.provider.query_executor.execute_query.side_effect

        def multi_call(conn, sql, params):
            call_count[0] += 1
            if call_count[0] == 1:
                return [
                    (
                        ext._base_row()
                        if False
                        else {
                            "procedure_name": "MY_PROC",
                            "definition": None,
                            "parameter_json": None,
                            "volatility": None,
                            "execute_as_principal": None,
                        }
                    )
                ]
            elif call_count[0] == 2:
                return []  # parameters
            else:
                return [{"definition": ddl}]  # DDL

        ext.provider.query_executor.execute_query.side_effect = multi_call
        result = ext.get_procedures("MYSCHEMA")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].definition, ddl)

    def test_oracle_strip_package_spec_with_none_result(self):
        """When _strip_embedded_oracle_package_spec returns None, procedure.definition = None."""
        vq = self._make_oracle_vq()
        ext = _make_extractor(dialect="oracle", vendor_queries=vq)
        # Procedure definition that is only a package spec
        pkg_only = "CREATE OR REPLACE PACKAGE MY_PKG AS PROCEDURE helper; END MY_PKG;"
        call_count = [0]

        def multi_call(conn, sql, params):
            call_count[0] += 1
            if call_count[0] == 1:
                return [
                    {
                        "procedure_name": "MY_PROC",
                        "definition": None,
                        "parameter_json": None,
                        "volatility": None,
                        "execute_as_principal": None,
                    }
                ]
            elif call_count[0] == 2:
                return []  # parameters
            else:
                return [{"definition": pkg_only}]  # DDL

        vq.get_procedure_arguments_query = MagicMock(return_value=("SELECT ...", []))
        ext.provider.query_executor.execute_query.side_effect = multi_call
        result = ext.get_procedures("MYSCHEMA")
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0].definition)


class TestGetFunctionsDialects(unittest.TestCase):
    """Cover get_functions branches (lines 545-904)."""

    def _make_vq_for_functions(self, has_arg_query=False, has_def_query=False):
        vq = MagicMock()
        vq.supports_functions.return_value = True
        vq.get_functions_query.return_value = ("SELECT ...", [])
        if not has_arg_query:
            # Delete the attribute so hasattr() returns False
            del vq.get_function_arguments_query
        else:
            vq.get_function_arguments_query.return_value = ("SELECT ...", [])
        if not has_def_query:
            vq.get_function_definition_query.return_value = (None, [])
        else:
            vq.get_function_definition_query.return_value = ("SELECT ...", [])
        return vq

    def test_get_functions_returns_empty_no_vendor_queries(self):
        ext = _make_extractor(dialect="postgresql")
        result = ext.get_functions("public")
        self.assertEqual(result, [])

    def test_get_functions_sql_is_none(self):
        vq = MagicMock()
        vq.supports_functions.return_value = True
        vq.get_functions_query.return_value = (None, [])
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)
        result = ext.get_functions("public")
        self.assertEqual(result, [])

    def test_get_functions_skips_system_functions(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="db2", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {"function_name": "<", "definition": None},
            {
                "function_name": "my_func",
                "definition": "CREATE FUNCTION my_func() RETURNS INT RETURN 1",
            },
        ]
        result = ext.get_functions("myschema")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "my_func")

    def test_get_functions_skips_udt_names(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="db2", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {
                "function_name": "MY_UDT",
                "definition": "CREATE FUNCTION MY_UDT() RETURNS INT RETURN 1",
            },
        ]
        udt = MagicMock()
        udt.name = "MY_UDT"
        get_udts = MagicMock(return_value=[udt])
        result = ext.get_functions("myschema", get_user_defined_types_fn=get_udts)
        self.assertEqual(result, [])

    def test_get_functions_udt_fetch_exception_is_swallowed(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="db2", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {"function_name": "fn", "definition": "CREATE FUNCTION fn() RETURNS INT RETURN 1"},
        ]

        def bad_udts(schema):
            raise RuntimeError("udt error")

        result = ext.get_functions("myschema", get_user_defined_types_fn=bad_udts)
        # Function should still be included
        self.assertEqual(len(result), 1)

    def test_get_functions_skips_no_function_name(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {"function_name": None, "definition": None},
        ]
        result = ext.get_functions("public")
        self.assertEqual(result, [])

    def test_get_functions_funcname_db2_key(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="db2", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {"FUNCNAME": "fn_db2", "definition": "CREATE FUNCTION fn_db2() RETURNS INT RETURN 1"},
        ]
        result = ext.get_functions("myschema")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "fn_db2")

    def test_get_functions_mysql_immutable_volatility(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": None, "is_deterministic": "YES"}],
            [{"Create Function": "CREATE FUNCTION `fn`() RETURNS INT BEGIN RETURN 1; END"}],
        ]
        result = ext.get_functions("mydb")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].volatility, "IMMUTABLE")

    def test_get_functions_mysql_volatile(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": None, "is_deterministic": "NO"}],
            [{"Create Function": "CREATE FUNCTION `fn`() RETURNS INT BEGIN RETURN 1; END"}],
        ]
        result = ext.get_functions("mydb")
        self.assertEqual(result[0].volatility, "VOLATILE")

    def test_get_functions_sqlserver_deterministic_true(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="sqlserver", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {
                "function_name": "fn",
                "definition": "CREATE FUNCTION fn() RETURNS INT AS BEGIN RETURN 1 END",
                "is_deterministic": "1",
            },
        ]
        result = ext.get_functions("dbo")
        self.assertEqual(result[0].volatility, "IMMUTABLE")

    def test_get_functions_sqlserver_deterministic_false(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="sqlserver", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {
                "function_name": "fn",
                "definition": "CREATE FUNCTION fn() RETURNS INT AS BEGIN RETURN 1 END",
                "is_deterministic": "0",
            },
        ]
        result = ext.get_functions("dbo")
        self.assertEqual(result[0].volatility, "VOLATILE")

    def test_get_functions_sqlserver_deterministic_none(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="sqlserver", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {
                "function_name": "fn",
                "definition": "CREATE FUNCTION fn() RETURNS INT AS BEGIN RETURN 1 END",
                "is_deterministic": None,
            },
        ]
        result = ext.get_functions("dbo")
        # volatility not set via is_deterministic branch → check no error
        self.assertEqual(len(result), 1)

    def test_get_functions_explicit_volatility_overrides(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {
                "function_name": "fn",
                "definition": "CREATE FUNCTION fn() RETURNS INT AS $$ BEGIN RETURN 1; END $$ LANGUAGE plpgsql",
                "volatility": "STABLE",
            },
        ]
        result = ext.get_functions("public")
        self.assertEqual(result[0].volatility, "STABLE")

    def test_get_functions_security_definer_val(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {
                "function_name": "fn",
                "definition": "CREATE FUNCTION fn() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$",
                "security_definer": "YES",
            },
        ]
        result = ext.get_functions("public")
        self.assertTrue(result[0].security_definer)

    def test_get_functions_security_type_val(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": None, "security_type": "INVOKER"}],
            [],  # SHOW CREATE FUNCTION
        ]
        result = ext.get_functions("mydb")
        self.assertFalse(result[0].security_definer)

    def test_get_functions_execute_as_principal_sets_definer(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="sqlserver", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {
                "function_name": "fn",
                "definition": "CREATE FUNCTION fn() RETURNS INT AS BEGIN RETURN 1 END",
                "execute_as_principal": "dbo",
            },
        ]
        result = ext.get_functions("dbo_schema")
        self.assertEqual(result[0].definer, "dbo")
        self.assertTrue(result[0].security_definer)

    def test_get_functions_execute_as_owner_in_definition(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="sqlserver", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {
                "function_name": "fn",
                "definition": "CREATE FUNCTION fn() RETURNS INT EXECUTE AS OWNER AS BEGIN RETURN 1 END",
                "execute_as_principal": None,
            },
        ]
        result = ext.get_functions("dbo_schema")
        self.assertEqual(result[0].definer, "OWNER")
        self.assertTrue(result[0].security_definer)

    def test_get_functions_mysql_definer_set(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        create_stmt = "CREATE DEFINER=`root`@`%` FUNCTION `fn`() RETURNS INT BEGIN RETURN 1; END"
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": None, "definer": "root@%"}],
            [{"Create Function": create_stmt}],
        ]
        result = ext.get_functions("mydb")
        self.assertEqual(result[0].definer, "root@%")

    def test_get_functions_data_access_set(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": None, "data_access": "READS SQL DATA"}],
            [],  # SHOW CREATE FUNCTION returns empty
        ]
        result = ext.get_functions("mydb")
        self.assertEqual(result[0].data_access, "READS SQL DATA")

    def test_get_functions_show_create_function_exception_kept(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": None}],
            RuntimeError("permission denied"),
        ]
        result = ext.get_functions("mydb")
        self.assertEqual(len(result), 1)

    def test_get_functions_with_function_arguments_query(self):
        vq = self._make_vq_for_functions(has_arg_query=True)
        ext = _make_extractor(dialect="oracle", vendor_queries=vq)
        vq.get_function_arguments_query.return_value = ("SELECT ...", [])
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "MY_FN", "definition": None}],
            # _fetch_oracle_ddl → None
            [],
            # get_function_arguments_query rows
            [
                {"position": "0", "data_type": "NUMBER", "in_out": "OUT"},  # return type
                {"position": "1", "argument_name": "p1", "data_type": "VARCHAR2", "in_out": "IN"},
            ],
            # get_function_definition_query (def_sql from vendor_queries)
        ]
        vq.get_function_definition_query.return_value = (None, [])
        result = ext.get_functions("MYSCHEMA")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].return_type, "NUMBER")
        self.assertEqual(len(result[0].parameters), 1)

    def test_get_functions_arg_query_skip_invalid_position(self):
        vq = self._make_vq_for_functions(has_arg_query=True)
        ext = _make_extractor(dialect="oracle", vendor_queries=vq)
        vq.get_function_arguments_query.return_value = ("SELECT ...", [])
        vq.get_function_definition_query.return_value = (None, [])
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "MY_FN", "definition": None}],
            [],  # DDL
            [
                {"position": None, "data_type": "NUMBER", "in_out": "IN"},  # None position → skip
                {"position": "bad", "data_type": "INT", "in_out": "IN"},  # ValueError → skip
                {
                    "position": "1",
                    "argument_name": "valid_param",
                    "data_type": "VARCHAR2",
                    "in_out": "IN",
                },
            ],
        ]
        result = ext.get_functions("MYSCHEMA")
        self.assertEqual(result[0].parameters[0].name, "valid_param")

    def test_get_functions_arg_query_exception_swallowed(self):
        vq = self._make_vq_for_functions(has_arg_query=True)
        ext = _make_extractor(dialect="oracle", vendor_queries=vq)
        vq.get_function_arguments_query.return_value = ("SELECT ...", [])
        vq.get_function_definition_query.return_value = (None, [])
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "MY_FN", "definition": None}],
            [],  # DDL
            RuntimeError("arg query failed"),  # arg query exception
        ]
        result = ext.get_functions("MYSCHEMA")
        self.assertEqual(len(result), 1)

    def test_get_functions_definition_query_populates(self):
        vq = self._make_vq_for_functions(has_def_query=True)
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)
        vq.get_function_definition_query.return_value = ("SELECT ...", [])
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": None}],
            [{"definition": "CREATE FUNCTION fn() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$"}],
        ]
        result = ext.get_functions("public")
        self.assertEqual(len(result), 1)
        self.assertIsNotNone(result[0].definition)

    def test_get_functions_definition_query_exception_swallowed(self):
        vq = self._make_vq_for_functions(has_def_query=True)
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)
        vq.get_function_definition_query.return_value = ("SELECT ...", [])
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": None}],
            RuntimeError("def query failed"),
        ]
        result = ext.get_functions("public")
        self.assertEqual(len(result), 1)

    def test_get_functions_parameter_parsing_from_definition(self):
        """Cover the regex-based fallback parameter parser."""
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="oracle", vendor_queries=vq)
        func_def = "CREATE FUNCTION MY_FN(p_id IN NUMBER, p_name IN VARCHAR2) RETURN VARCHAR2 AS BEGIN RETURN 'x'; END;"
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "MY_FN", "definition": func_def}],
            [],  # DDL
        ]
        vq.get_function_definition_query.return_value = (None, [])
        result = ext.get_functions("MYSCHEMA")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].return_type, "VARCHAR2")
        self.assertGreater(len(result[0].parameters), 0)

    def test_get_functions_parameter_parsing_direction_first(self):
        """Cover the branch where direction token comes first."""
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="oracle", vendor_queries=vq)
        # "IN p_id NUMBER" format — direction before name
        func_def = "CREATE FUNCTION MY_FN(IN p_id NUMBER) RETURN INT AS BEGIN RETURN 1; END;"
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "MY_FN", "definition": func_def}],
            [],  # DDL
        ]
        vq.get_function_definition_query.return_value = (None, [])
        result = ext.get_functions("MYSCHEMA")
        self.assertEqual(len(result), 1)

    def test_get_functions_mysql_fetch_parameters_fallback(self):
        """Cover line 860-861: MySQL fallback to _fetch_mysql_routine_parameters."""
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        vq.get_parameters_query = MagicMock(return_value=("SELECT ...", []))
        create_stmt = "CREATE FUNCTION `fn`() RETURNS INT BEGIN RETURN 1; END"
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": None}],
            [{"Create Function": create_stmt}],
            # MySQL fetch params call
            [
                {
                    "ordinal_position": "1",
                    "param_name": "p1",
                    "parameter_type": "INT",
                    "param_mode": "IN",
                }
            ],
        ]
        result = ext.get_functions("mydb")
        self.assertEqual(len(result), 1)

    def test_get_functions_extension_name_set(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {
                "function_name": "fn",
                "definition": "CREATE FUNCTION fn() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$",
                "extension_name": "pg_catalog",
            },
        ]
        result = ext.get_functions("public")
        self.assertTrue(hasattr(result[0], "extension"))
        self.assertEqual(result[0].extension, "pg_catalog")

    def test_get_functions_result_tracker_tracks_status(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)
        tracker = MagicMock()
        fn_status = MagicMock()
        tracker._track_object_status.return_value = fn_status
        ext.result_tracker = tracker
        ext.provider.query_executor.execute_query.return_value = [
            {
                "function_name": "fn",
                "definition": "CREATE FUNCTION fn() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$",
            },
        ]
        result = ext.get_functions("public")
        tracker._track_object_status.assert_called_once_with("function", "fn", "public")
        fn_status.add_property_status.assert_called()

    def test_get_functions_result_tracker_parameter_exception(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)
        tracker = MagicMock()
        fn_status = MagicMock()
        tracker._track_object_status.return_value = fn_status
        ext.result_tracker = tracker
        # Make _build_parameters_from_json throw
        ext._build_parameters_from_json = MagicMock(side_effect=ValueError("bad json"))
        ext.provider.query_executor.execute_query.return_value = [
            {
                "function_name": "fn",
                "definition": "CREATE FUNCTION fn() RETURNS INT LANGUAGE sql AS $$ SELECT 1 $$",
                "parameter_json": "bad",
            },
        ]
        result = ext.get_functions("public")
        fn_status.add_property_status.assert_any_call("parameters", False)
        tracker._track_warning.assert_called_once()

    def test_get_functions_exception_with_result_tracker(self):
        vq = MagicMock()
        vq.supports_functions.return_value = True
        vq.get_functions_query.return_value = ("SELECT ...", [])
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)
        tracker = MagicMock()
        ext.result_tracker = tracker
        ext.provider.query_executor.execute_query.side_effect = Exception("fatal error")
        result = ext.get_functions("public")
        self.assertEqual(result, [])
        tracker._track_error.assert_called_once()

    def test_get_functions_oracle_ddl_sets_definition(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="oracle", vendor_queries=vq)
        ddl = "CREATE OR REPLACE FUNCTION MY_FN RETURN VARCHAR2 AS BEGIN RETURN 'x'; END;"
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "MY_FN", "definition": None}],
            [{"definition": ddl}],  # _fetch_oracle_ddl
        ]
        vq.get_function_definition_query.return_value = (None, [])
        result = ext.get_functions("MYSCHEMA")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].definition, ddl)
        self.assertIsNone(result[0].body)

    def test_get_functions_show_create_function_begin_idx(self):
        """Cover begin_idx branch in SHOW CREATE FUNCTION fallback."""
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        create_stmt = "CREATE FUNCTION `fn`() RETURNS INT BEGIN RETURN 1; END"
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": None}],
            [{"Create Function": create_stmt}],
        ]
        result = ext.get_functions("mydb")
        # body should start at BEGIN
        self.assertIn("BEGIN", result[0].body)

    def test_get_functions_show_create_function_no_begin(self):
        """Create stmt without BEGIN → body not set from SHOW CREATE."""
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        create_stmt = "CREATE FUNCTION `fn`() RETURNS INT RETURN 1"
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": None}],
            [{"Create Function": create_stmt}],
        ]
        result = ext.get_functions("mydb")
        self.assertEqual(result[0].definition, create_stmt)

    def test_get_functions_show_create_function_exception_with_result_tracker(self):
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)
        tracker = MagicMock()
        fn_status = MagicMock()
        tracker._track_object_status.return_value = fn_status
        ext.result_tracker = tracker
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "fn", "definition": None}],
            RuntimeError("permission denied"),
        ]
        result = ext.get_functions("mydb")
        fn_status.add_property_status.assert_any_call("definition", False)
        tracker._track_warning.assert_called()

    def test_get_functions_parameter_parsing_two_tokens(self):
        """Cover the len(tokens)>=2 branch (name + data_type)."""
        vq = self._make_vq_for_functions()
        ext = _make_extractor(dialect="oracle", vendor_queries=vq)
        # Simple format: "p_name VARCHAR2"
        func_def = "CREATE FUNCTION MY_FN(p_name VARCHAR2) RETURN NUMBER AS BEGIN RETURN 1; END;"
        ext.provider.query_executor.execute_query.side_effect = [
            [{"function_name": "MY_FN", "definition": func_def}],
            [],  # DDL
        ]
        vq.get_function_definition_query.return_value = (None, [])
        result = ext.get_functions("MYSCHEMA")
        self.assertEqual(len(result), 1)
        self.assertGreater(len(result[0].parameters), 0)
        self.assertEqual(result[0].parameters[0].data_type, "VARCHAR2")

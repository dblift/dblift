"""Provider contract imports should not require analysis or report dependencies."""

import pytest

from tests.unit.lightweight_core._support import run_python

BLOCKED = ("rich", "jinja2", "sqlglot", "psycopg", "oracledb", "pymssql", "pymongo")


def test_provider_exports_do_not_import_analysis_or_renderers():
    result = run_python(
        """
        import sys
        from dblift.extensions.providers import PluginInfo, ProviderRegistry, ProviderTransport
        from dblift.db.dml_analysis import DmlMutation
        assert PluginInfo.__name__ == 'PluginInfo'
        assert ProviderTransport.__args__ == ('native',)
        assert DmlMutation('t', {'UPDATE'}, ['x']).table == 't'
        assert not ProviderRegistry._discovered
        assert not any(n.startswith('dblift.db.plugins.') for n in sys.modules)
        """,
        blocked=BLOCKED,
    )
    assert result.returncode == 0, result.stderr


def test_provider_package_access_does_not_import_analysis_or_renderers():
    result = run_python(
        """
        import sys
        from dblift.extensions import providers
        assert providers.PluginInfo.__name__ == 'PluginInfo'
        assert not providers.ProviderRegistry._discovered
        assert not any(n.startswith('dblift.db.plugins.') for n in sys.modules)
        """,
        blocked=BLOCKED,
    )
    assert result.returncode == 0, result.stderr


def test_logger_html_exports_are_lazy_and_keep_class_identity():
    result = run_python("""
        import sys
        import dblift.core.logger as logger
        import dblift.core.logger.formatters as formatters
        assert 'HtmlFormatter' in logger.__all__ and 'HtmlFormatter' in formatters.__all__
        assert 'HtmlFormatter' in dir(logger) and 'HtmlFormatter' in dir(formatters)
        assert 'dblift.core.logger.formatters.htmlformatter' not in sys.modules
        from dblift.core.logger.formatters.htmlformatter import HtmlFormatter
        assert logger.HtmlFormatter is HtmlFormatter
        assert formatters.HtmlFormatter is HtmlFormatter
        assert logger.HtmlFormatter is logger.HtmlFormatter
        assert formatters.HtmlFormatter is formatters.HtmlFormatter
        try:
            logger.no_such_attribute
        except AttributeError as error:
            assert 'no_such_attribute' in str(error)
        else:
            raise AssertionError('unknown logger attribute was accepted')
        try:
            formatters.no_such_attribute
        except AttributeError as error:
            assert 'no_such_attribute' in str(error)
        else:
            raise AssertionError('unknown formatter attribute was accepted')
        """)
    assert result.returncode == 0, result.stderr


def test_logger_facade_resolves_html_class_and_rejects_unknown_names():
    import dblift.core.logger as logger
    import dblift.core.logger.formatters as formatters
    from dblift.core.logger.formatters.htmlformatter import HtmlFormatter

    for facade in (logger, formatters):
        assert "HtmlFormatter" in dir(facade)
        facade.__dict__.pop("HtmlFormatter", None)
        assert facade.HtmlFormatter is HtmlFormatter
        assert facade.HtmlFormatter is HtmlFormatter
        with pytest.raises(AttributeError, match="no_such_attribute"):
            facade.no_such_attribute


def test_json_result_serialization_does_not_load_rich():
    result = run_python(
        """
        import json
        import sys
        from dblift.core.logger.formatters.jsonformatter import JsonFormatter
        from dblift.core.logger.results import MigrateResult
        report = JsonFormatter().format_result(MigrateResult(), 'main', 'demo', 'migrate')
        assert isinstance(json.loads(report), dict)
        assert 'dblift.core.logger.console' not in sys.modules
        """,
        blocked=("rich",),
    )
    assert result.returncode == 0, result.stderr


def test_sqlglot_absence_is_not_swallowed_as_parse_failure():
    result = run_python(
        """
        from dblift.db.dml_analysis import (
            analyze_dml, cte_outer_statement_type, dml_where_predicate,
            insert_value_rows, is_full_table_dml, statement_dml_table,
        )
        cases = (
            lambda: analyze_dml('UPDATE t SET x = 1'),
            lambda: cte_outer_statement_type('WITH c AS (SELECT 1) SELECT * FROM c'),
            lambda: dml_where_predicate('UPDATE t SET x = 1 WHERE id = 2'),
            lambda: insert_value_rows('INSERT INTO t (id) VALUES (1)'),
            lambda: is_full_table_dml('DELETE FROM t'),
            lambda: statement_dml_table('UPDATE t SET x = 1', dialect='postgres'),
        )
        for call in cases:
            try:
                call()
            except ModuleNotFoundError as error:
                assert error.name == 'sqlglot', error
            else:
                raise AssertionError('missing sqlglot was treated as a parse failure')
        """,
        blocked=("sqlglot",),
    )
    assert result.returncode == 0, result.stderr

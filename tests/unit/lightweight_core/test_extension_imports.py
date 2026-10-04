import pytest

from tests.unit.lightweight_core._support import run_python


def test_package_does_not_load_implementations():
    result = run_python(
        """
        import sys
        import dblift.extensions as ext
        assert ext.__all__ == ['logging', 'providers', 'sql_generation', 'sql_model']
        assert not any(n.startswith('dblift.db.plugins.') for n in sys.modules)
        assert not any(n.startswith('dblift.core.sql_parser.') for n in sys.modules)
        assert set(ext.__all__) <= set(dir(ext))
        try:
            ext.not_a_category
        except AttributeError:
            pass
        else:
            raise AssertionError('unknown attribute accepted')
    """,
        blocked=("rich", "jinja2", "sqlglot"),
    )
    assert result.returncode == 0, result.stderr


def test_category_access_keeps_module_identity():
    result = run_python("""
        import dblift.extensions as ext
        from dblift.extensions import logging, providers, sql_generation, sql_model
        assert ext.logging is logging
        assert ext.providers is providers
        assert ext.sql_generation is sql_generation
        assert ext.sql_model is sql_model
        assert ext.providers is providers
        assert set(ext.__all__) <= set(dir(ext))
    """)
    assert result.returncode == 0, result.stderr


def test_probe_really_blocks_imports():
    result = run_python("import jinja2", blocked=("jinja2",))
    assert result.returncode != 0
    assert "contract blocked: jinja2" in result.stderr


def test_package_introspection_and_unknown_attribute():
    import dblift.extensions as ext

    assert set(ext.__all__) <= set(dir(ext))
    with pytest.raises(
        AttributeError, match="module 'dblift.extensions' has no attribute 'not_a_category'"
    ):
        ext.not_a_category

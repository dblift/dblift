"""Contract tests for :mod:`dblift.db.generator_protocol`.

The provider layer describes what a DDL/ALTER generator is through these
Protocols instead of importing the concrete generator package. The tests
pin that the generator base classes still satisfy them, that an object
missing a method does not, and that the Protocol signatures stay in step
with the base classes they were copied from.
"""

import ast
import inspect
from pathlib import Path
from typing import List, Optional

import pytest

import dblift.db
from dblift.core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
from dblift.core.sql_generator.base_generator import BaseSqlGenerator
from dblift.core.sql_generator.sql_generator import SqlGenerator
from dblift.db.generator_protocol import AlterGeneratorProtocol, SqlGeneratorProtocol

pytestmark = [pytest.mark.unit]

SQL_GENERATOR_METHODS = (
    "generate_ddl",
    "generate_create_statement",
    "generate_drop_statement",
    "generate_drop_statements",
    "generate_schema_script",
)
ALTER_GENERATOR_METHODS = (
    "generate_alter_table_statements",
    "generate_alter_view_statement",
)


class _AlterGenerator(BaseAlterGenerator):
    def generate_alter_table_statements(  # type: ignore[override]
        self,
        table,
        add_constraints=None,
        drop_constraints=None,
        add_columns=None,
        drop_columns=None,
        modify_columns=None,
    ) -> List[str]:
        return []

    def generate_alter_view_statement(self, view, new_query=None) -> Optional[str]:
        return None

    def _format_identifier(self, identifier: str) -> str:
        return identifier


def test_sql_generator_satisfies_sql_generator_protocol():
    assert isinstance(SqlGenerator(default_dialect="postgresql"), SqlGeneratorProtocol)


def test_alter_generator_subclass_satisfies_alter_generator_protocol():
    assert isinstance(_AlterGenerator("postgresql"), AlterGeneratorProtocol)


def test_class_missing_generate_drop_statement_is_not_a_sql_generator():
    class _NoPublicDrop:
        def generate_ddl(self, objects):
            return ""

        def generate_create_statement(self, obj):
            return ""

        def generate_drop_statements(self, objects):
            return ""

        def generate_schema_script(self, schema):
            return {}

    assert not isinstance(_NoPublicDrop(), SqlGeneratorProtocol)


def test_class_missing_alter_view_is_not_an_alter_generator():
    class _TableOnly:
        def generate_alter_table_statements(self, table):
            return []

    assert not isinstance(_TableOnly(), AlterGeneratorProtocol)


@pytest.mark.parametrize(
    ("protocol", "base", "method"),
    [(SqlGeneratorProtocol, BaseSqlGenerator, m) for m in SQL_GENERATOR_METHODS]
    + [(AlterGeneratorProtocol, BaseAlterGenerator, m) for m in ALTER_GENERATOR_METHODS],
)
def test_protocol_parameters_match_base_class(protocol, base, method):
    """Parameter names, kinds and defaults are copied from the base class."""

    def _params(fn):
        return [(p.name, p.kind, p.default) for p in inspect.signature(fn).parameters.values()]

    assert _params(getattr(protocol, method)) == _params(getattr(base, method))


def test_db_layer_does_not_import_the_generator_package():
    """``dblift/db`` types generators through the Protocols, never the package.

    ``TYPE_CHECKING`` imports count: they still couple the provider layer to
    the generator package for every type checker and reader.
    """
    db_root = Path(dblift.db.__file__).parent
    forbidden = "dblift.core.sql_generator"
    offenders = []
    for path in sorted(db_root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                if module == forbidden or module.startswith(forbidden + "."):
                    offenders.append(f"{path.relative_to(db_root)}:{node.lineno} {module}")
    assert offenders == []

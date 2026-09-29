"""Contract tests for :mod:`dblift.db.generator_protocol`.

The provider layer describes what a DDL/ALTER generator is through these
Protocols. An object missing a required method must not satisfy the
contract, and provider modules must remain independent of implementations.
"""

import ast
from pathlib import Path

import pytest

import dblift.db
from dblift.db.base_quirks import BaseQuirks
from dblift.db.generator_protocol import AlterGeneratorProtocol, SqlGeneratorProtocol
from dblift.db.provider_registry import ProviderRegistry

pytestmark = [pytest.mark.unit]


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


@pytest.mark.parametrize(
    "dialect", [None, *(plugin.name for plugin in ProviderRegistry.list_plugins())]
)
def test_bundled_generator_hooks_return_none(dialect):
    quirks = BaseQuirks() if dialect is None else ProviderRegistry.get_quirks(dialect)
    assert quirks.ddl_generator_class() is None
    assert quirks.alter_generator_class() is None

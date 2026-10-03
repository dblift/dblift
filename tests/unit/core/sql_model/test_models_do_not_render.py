"""SQL models carry data without loading or exposing DDL rendering."""

import importlib.util
import subprocess
import sys

import pytest

from dblift.core import sql_model


@pytest.mark.parametrize(
    "model",
    [
        sql_model.DatabaseLink,
        sql_model.Event,
        sql_model.Extension,
        sql_model.ForeignDataWrapper,
        sql_model.ForeignServer,
        sql_model.Index,
        sql_model.LinkedServer,
        sql_model.Module,
        sql_model.Package,
        sql_model.Partition,
        sql_model.Procedure,
        sql_model.Sequence,
        sql_model.Synonym,
        sql_model.Table,
        sql_model.Trigger,
        sql_model.UserDefinedType,
        sql_model.View,
    ],
)
@pytest.mark.parametrize("member", ["create_statement", "drop_statement"])
def test_models_do_not_render(model, member):
    assert not hasattr(model, member)


def test_table_has_no_alter_rendering():
    assert not any(name.startswith("generate_alter_table_") for name in dir(sql_model.Table))


def test_generator_package_is_removed():
    assert importlib.util.find_spec("dblift.core.sql_generator") is None


def test_model_import_does_not_load_generator():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import dblift.core.sql_model; "
            "assert not any(name.startswith('dblift.core.sql_generator') for name in sys.modules)",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_sequence_has_no_fallback_renderer():
    assert not hasattr(sql_model.Sequence, "_build_sequence_ddl")

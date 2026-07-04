from dataclasses import fields, is_dataclass

import pytest

from cli.main import CliCommandContext


@pytest.mark.unit
class TestCliCommandContextDataclass:
    def test_is_dataclass(self):
        assert is_dataclass(CliCommandContext)

    def test_fields_count(self):
        assert len(fields(CliCommandContext)) == 9

    def test_field_names(self):
        field_names = {f.name for f in fields(CliCommandContext)}
        assert field_names == {
            "client",
            "args",
            "log",
            "scripts_dir",
            "additional_scripts_dirs",
            "recursive",
            "placeholders",
            "dir_recursive_map",
            "license_tier",
        }

    def test_default_values(self):
        ctx = CliCommandContext()
        assert ctx.client is None
        assert ctx.args is None
        assert ctx.log is None
        assert ctx.scripts_dir is None
        assert ctx.additional_scripts_dirs == []
        assert ctx.recursive is False
        assert ctx.placeholders == {}
        assert ctx.dir_recursive_map == {}
        assert ctx.license_tier is None

    def test_default_factory_independence(self):
        ctx1 = CliCommandContext()
        ctx2 = CliCommandContext()
        assert ctx1.additional_scripts_dirs is not ctx2.additional_scripts_dirs
        assert ctx1.placeholders is not ctx2.placeholders
        assert ctx1.dir_recursive_map is not ctx2.dir_recursive_map

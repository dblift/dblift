"""``dblift.mcp_tools`` entry-point discovery (mirrors tests/unit/cli/test_cli_extensions.py)."""

from unittest.mock import Mock, patch

import pytest

from dblift.cli.mcp.registry import MCP_TOOLS_ENTRY_POINT_GROUP, load_mcp_tool_registrars


def test_group_name_is_stable():
    assert MCP_TOOLS_ENTRY_POINT_GROUP == "dblift.mcp_tools"


def test_load_registrars_returns_loaded_callables_in_name_order():
    b = Mock(name="b")
    a = Mock(name="a")
    eps = [Mock(load=Mock(return_value=b)), Mock(load=Mock(return_value=a))]
    eps[0].name, eps[1].name = "b", "a"

    with patch("dblift.cli.mcp.registry.entry_points", return_value=eps) as ep:
        registrars = load_mcp_tool_registrars()

    ep.assert_called_once_with(group="dblift.mcp_tools")
    assert registrars == [a, b]


def test_load_registrars_skips_entrypoints_when_disabled(monkeypatch):
    ep = Mock(load=Mock(return_value=Mock()))
    ep.name = "x"
    monkeypatch.setenv("DBLIFT_DISABLE_CLI_EXTENSIONS", "1")

    with patch("dblift.cli.mcp.registry.entry_points", return_value=[ep]):
        assert load_mcp_tool_registrars() == []

    ep.load.assert_not_called()


def test_load_registrars_rejects_duplicate_names():
    eps = [Mock(load=Mock(return_value=Mock())), Mock(load=Mock(return_value=Mock()))]
    eps[0].name = eps[1].name = "same"

    with patch("dblift.cli.mcp.registry.entry_points", return_value=eps):
        with pytest.raises(ValueError, match="Duplicate MCP tool registrar: same"):
            load_mcp_tool_registrars()

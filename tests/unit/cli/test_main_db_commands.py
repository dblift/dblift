"""Regression tests for db utility command dispatch."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cli.main import main

pytestmark = [pytest.mark.unit]


def test_db_list_drivers_does_not_require_global_config_load(capsys):
    with (
        patch.object(sys, "argv", ["dblift", "db", "list-drivers"]),
        patch("cli.main._load_and_merge_config") as load_config,
        patch(
            "core.licensing.license_manager.LicenseManager.get_info",
            return_value=SimpleNamespace(),
        ),
        patch(
            "cli.db_utils.ProviderRegistry.get_available_drivers",
            return_value={"cosmosdb": True},
        ),
    ):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 0
    load_config.assert_not_called()
    assert "cosmosdb" in capsys.readouterr().out

"""Paid raw-config passthrough (``_paid_config_data``).

OSS parsing drops unknown top-level YAML sections; the keys in
``_PAID_RAW_CONFIG_KEYS`` are preserved verbatim onto
``config._paid_config_data`` so the paid tiers can consume sections the
OSS core does not model (``data_sets``, ``validation``,
``zero_downtime``).
"""

from __future__ import annotations

import pytest

from config.dblift_config import _PAID_RAW_CONFIG_KEYS, DbliftConfig

pytestmark = [pytest.mark.unit]

_BASE = {
    "database": {
        "type": "sqlite",
        "url": "sqlite:///test.db",
    }
}


def _config_with(extra):
    return DbliftConfig.from_dict({**_BASE, **extra}, resolve_secrets=False)


class TestAllowlist:
    def test_allowlist_contents(self):
        """The allowlist is cross-tier API: paid tiers key on these names."""
        assert _PAID_RAW_CONFIG_KEYS == ("data_sets", "datasets", "validation", "zero_downtime")


class TestPassthrough:
    @pytest.mark.parametrize("key", _PAID_RAW_CONFIG_KEYS)
    def test_section_is_preserved(self, key):
        payload = {"some": {"nested": ["values"]}}
        config = _config_with({key: payload})
        assert getattr(config, "_paid_config_data", None) == {key: payload}

    def test_zero_downtime_section_preserved_verbatim(self):
        section = {"enabled": True, "batch_size": 5000, "strategy": "expand-contract"}
        config = _config_with({"zero_downtime": section})
        assert config._paid_config_data == {"zero_downtime": section}

    def test_unknown_section_is_not_preserved(self):
        config = _config_with({"not_a_paid_key": {"x": 1}})
        assert getattr(config, "_paid_config_data", None) is None

    def test_absent_sections_leave_attribute_unset(self):
        config = _config_with({})
        assert getattr(config, "_paid_config_data", None) is None

    def test_multiple_sections_coexist(self):
        config = _config_with({"validation": {"rules": []}, "zero_downtime": {"enabled": False}})
        assert config._paid_config_data == {
            "validation": {"rules": []},
            "zero_downtime": {"enabled": False},
        }

"""Tests for ValidationConfig class."""

from pathlib import Path

import pytest

from config.validation_config import ValidationConfig

pytestmark = [pytest.mark.unit]


class TestValidationConfig:
    """Test ValidationConfig functionality."""

    def test_default_values(self):
        """Test ValidationConfig default values."""
        config = ValidationConfig()

        assert config.enabled is True
        assert config.rules_file is None
        assert config.rule_profile is None
        assert config.rules == []
        assert config.fail_on == "error"
        assert config.severity_threshold == "warning"
        assert config.performance_enabled is True
        assert "cartesian_product" in config.performance_rules
        assert config.output_format == "console"

    def test_from_dict(self):
        """Test creating ValidationConfig from dictionary."""
        data = {
            "enabled": False,
            "rule_profile": "strict",
            "rules": ["no_grant_all_privileges", "require_primary_key"],
            "fail_on": "warning",
            "severity_threshold": "error",
            "performance_enabled": False,
            "performance_rules": ["cartesian_product"],
            "output_format": "json",
        }

        config = ValidationConfig.from_dict(data)

        assert config.enabled is False
        assert config.rules_file is None
        assert config.rule_profile == "strict"
        assert config.rules == ["no_grant_all_privileges", "require_primary_key"]
        assert config.fail_on == "warning"
        assert config.severity_threshold == "error"
        assert config.performance_enabled is False
        assert config.performance_rules == ["cartesian_product"]
        assert config.output_format == "json"

    def test_from_dict_partial(self):
        """Test creating ValidationConfig from partial dictionary."""
        data = {"enabled": False, "fail_on": "info"}

        config = ValidationConfig.from_dict(data)

        assert config.enabled is False
        assert config.fail_on == "info"
        # Other values should be defaults
        assert config.severity_threshold == "warning"
        assert config.performance_enabled is True

    def test_to_dict(self):
        """Test converting ValidationConfig to dictionary."""
        config = ValidationConfig(enabled=False, rules_file=".my_rules.yaml", fail_on="warning")

        data = config.to_dict()

        assert data["enabled"] is False
        assert data["rules_file"] == ".my_rules.yaml"
        assert data["rule_profile"] is None
        assert data["rules"] == []
        assert data["fail_on"] == "warning"
        assert "fail_on_violations" not in data
        assert "severity_threshold" in data
        assert "performance_enabled" in data

    def test_get_rules_path(self):
        """Test getting rules file Path object."""
        config = ValidationConfig(rules_file=".dblift_rules.yaml")

        rules_path = config.get_rules_path()

        assert isinstance(rules_path, Path)
        assert str(rules_path) == ".dblift_rules.yaml"

    def test_get_rules_path_none(self):
        """Test getting rules path when no file configured."""
        config = ValidationConfig(rules_file=None)

        rules_path = config.get_rules_path()

        assert rules_path is None

    def test_invalid_severity_threshold(self):
        """Test that invalid severity threshold raises error."""
        with pytest.raises(ValueError, match="Invalid severity_threshold"):
            ValidationConfig(severity_threshold="invalid")

    def test_invalid_output_format(self):
        """Test that invalid output format raises error."""
        with pytest.raises(ValueError, match="Invalid output_format"):
            ValidationConfig(output_format="invalid")

    def test_invalid_fail_on(self):
        """Test that invalid fail_on raises error."""
        with pytest.raises(ValueError, match="Invalid fail_on"):
            ValidationConfig(fail_on="invalid")

    def test_rules_file_cannot_be_combined_with_profile(self):
        """Test that custom rule files are exclusive with built-in profiles."""
        with pytest.raises(ValueError, match="--rules-file cannot be combined"):
            ValidationConfig(rules_file=".my_rules.yaml", rule_profile="strict")

    def test_rules_file_cannot_be_combined_with_rules(self):
        """Test that custom rule files are exclusive with selected rules."""
        with pytest.raises(ValueError, match="--rules-file cannot be combined"):
            ValidationConfig(rules_file=".my_rules.yaml", rules=["security"])

    def test_valid_severity_thresholds(self):
        """Test all valid severity thresholds."""
        valid_thresholds = ["error", "warning", "info"]

        for threshold in valid_thresholds:
            config = ValidationConfig(severity_threshold=threshold)
            assert config.severity_threshold == threshold

    def test_valid_output_formats(self):
        """Test all valid output formats."""
        valid_formats = ["console", "json", "sarif", "github-actions", "gitlab", "compact", "html"]

        for format_name in valid_formats:
            config = ValidationConfig(output_format=format_name)
            assert config.output_format == format_name

    def test_exclude_patterns(self):
        """Test exclude patterns configuration."""
        config = ValidationConfig(exclude_patterns=["*/temp/*", "*/test/*"])

        assert len(config.exclude_patterns) == 2
        assert "*/temp/*" in config.exclude_patterns

    def test_performance_rules_customization(self):
        """Test customizing performance rules."""
        custom_rules = ["cartesian_product", "select_star"]
        config = ValidationConfig(performance_rules=custom_rules)

        assert config.performance_rules == custom_rules
        assert len(config.performance_rules) == 2

    def test_from_dict_performance_rules_defaults_match_dataclass(self):
        """from_dict({}) must produce same performance_rules as direct constructor."""
        from_dict_config = ValidationConfig.from_dict({})
        direct_config = ValidationConfig()
        assert from_dict_config.performance_rules == direct_config.performance_rules

"""``logging.level: warn`` is accepted, like the CLI ``--log-level warn``."""

import pytest

from dblift.config.dblift_config import DbliftConfig


def _data(level):
    return {
        "database": {
            "url": "postgresql+psycopg://localhost:5432/db",
            "username": "pg",
            "password": "pw",
        },
        "logging": {"level": level},
    }


@pytest.mark.unit
@pytest.mark.parametrize("level", ["warn", "WARN", "Warning", "warning"])
def test_warn_resolves_to_warning(level):
    assert DbliftConfig.from_dict(_data(level)).logging.level == "WARNING"


@pytest.mark.unit
def test_yaml_warn_level(tmp_path):
    f = tmp_path / "dblift.yaml"
    f.write_text(
        "database:\n  url: postgresql+psycopg://localhost:5432/db\n"
        "  username: pg\n  password: pw\nlogging:\n  level: warn\n"
    )
    assert DbliftConfig.from_file(str(f)).logging.level == "WARNING"


@pytest.mark.unit
def test_invalid_level_still_rejected():
    with pytest.raises(ValueError, match="Invalid log level"):
        DbliftConfig.from_dict(_data("loud"))

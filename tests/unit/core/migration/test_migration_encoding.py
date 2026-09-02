from __future__ import annotations

import pytest

from dblift.config.dblift_config import DbliftConfig
from dblift.core.migration.encoding import (
    MigrationEncodingError,
    detect_file_encoding,
    read_migration_text,
)
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager


def test_default_utf8_decode_remains_strict(tmp_path):
    script = tmp_path / "V1__accent.sql"
    script.write_bytes("INSERT INTO t VALUES ('é');\n".encode("iso-8859-1"))

    with pytest.raises(MigrationEncodingError):
        read_migration_text(script, configured_encoding="utf-8", detect_encoding=False)


def test_detect_encoding_preserves_iso_8859_1_accents(tmp_path):
    script = tmp_path / "V1__accent.sql"
    expected = "INSERT INTO t VALUES ('éàç');\n"
    script.write_bytes(expected.encode("iso-8859-1"))

    migration = Migration(script_path=script, detect_encoding=True)

    assert migration.content == expected
    assert detect_file_encoding(script) == "iso-8859-1"


def test_detect_encoding_strips_utf8_bom(tmp_path):
    script = tmp_path / "V1__bom.sql"
    script.write_bytes(b"\xef\xbb\xbf" + "SELECT 'é';\n".encode("utf-8"))

    assert read_migration_text(script, detect_encoding=True) == "SELECT 'é';\n"


def test_detect_encoding_reads_utf16le_bom(tmp_path):
    script = tmp_path / "V1__utf16.sql"
    expected = "SELECT 'é';\n"
    script.write_bytes(b"\xff\xfe" + expected.encode("utf-16-le"))

    assert read_migration_text(script, detect_encoding=True) == expected


def test_detect_encoding_raises_when_detected_codec_cannot_decode(tmp_path, monkeypatch):
    script = tmp_path / "V1__accent.sql"
    script.write_bytes("SELECT 'é';\n".encode("iso-8859-1"))

    monkeypatch.setattr("dblift.core.migration.encoding.detect_file_encoding", lambda _: "ascii")

    with pytest.raises(MigrationEncodingError):
        read_migration_text(script, detect_encoding=True)


def test_script_manager_uses_detect_encoding_for_loaded_migrations(tmp_path):
    script = tmp_path / "V1__accent.sql"
    expected = "INSERT INTO t VALUES ('é');\n"
    script.write_bytes(expected.encode("iso-8859-1"))
    logger = type(
        "Logger", (), {"warning": lambda *args, **kwargs: None, "debug": lambda *a, **k: None}
    )()

    manager = MigrationScriptManager(logger, detect_encoding=True)
    migrations = manager.load_migration_scripts(tmp_path)

    assert migrations[MigrationType.SQL][0].content == expected


def test_config_loads_detect_encoding_flag():
    config = DbliftConfig.from_dict(
        {
            "database": {"type": "sqlite", "path": ":memory:"},
            "migrations": {
                "directory": "migrations",
                "script_encoding": "utf-8",
                "detect_encoding": True,
            },
        }
    )

    assert config.migrations.script_encoding == "utf-8"
    assert config.migrations.detect_encoding is True
    assert config.to_dict()["migrations"]["detect_encoding"] is True

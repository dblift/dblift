from dataclasses import fields

from config.dblift_config import DbliftConfig


def test_journal_dir_field_gone():
    assert "journal_dir" not in {f.name for f in fields(DbliftConfig)}


def test_journal_enabled_field_gone():
    """Journal is always on; it is not a config option."""
    names = {f.name for f in fields(DbliftConfig)}
    assert "journal_enabled" not in names
    assert "journal_enabled" not in DbliftConfig.from_args_dict({"journal_enabled": False})

from dataclasses import fields

from config.dblift_config import DbliftConfig


def test_journal_dir_field_gone():
    assert "journal_dir" not in {f.name for f in fields(DbliftConfig)}

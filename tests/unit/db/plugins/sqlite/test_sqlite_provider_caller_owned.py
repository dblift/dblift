"""``is_caller_owned`` answers from the flag ``attach_external_sqlalchemy`` sets."""

import pytest

from dblift.config import DbliftConfig
from dblift.db.plugins.sqlite.provider import SQLiteProvider


@pytest.mark.unit
@pytest.mark.sqlite
def test_is_caller_owned_follows_the_external_connection_flag() -> None:
    provider = SQLiteProvider(
        DbliftConfig.from_dict({"database": {"type": "sqlite", "path": ":memory:"}})
    )

    assert provider.is_caller_owned() is False
    provider._external_connection = True
    assert provider.is_caller_owned() is True

"""``NoSqlQueryLanguageUnsupportedError`` — DBLIFT-NOSQL-002.

Distinct from ``NoSqlWriteNotSupportedError``: that one means a *write*
reached a read-only query API. This one means the store has no string
query language at all, so reads are rejected too.
"""

import pytest

from core.exceptions import (
    ExecutionError,
    NoSqlQueryLanguageUnsupportedError,
    NoSqlWriteNotSupportedError,
)


def test_code_is_stable():
    assert NoSqlQueryLanguageUnsupportedError.code == "DBLIFT-NOSQL-002"


def test_is_an_execution_error():
    assert issubclass(NoSqlQueryLanguageUnsupportedError, ExecutionError)


def test_is_not_a_write_error():
    """The two are siblings, not parent/child — a caller catching one must not
    silently swallow the other."""
    assert not issubclass(NoSqlQueryLanguageUnsupportedError, NoSqlWriteNotSupportedError)
    assert not issubclass(NoSqlWriteNotSupportedError, NoSqlQueryLanguageUnsupportedError)


def test_message_is_preserved():
    with pytest.raises(NoSqlQueryLanguageUnsupportedError) as excinfo:
        raise NoSqlQueryLanguageUnsupportedError("use context.db instead")
    assert "use context.db instead" in str(excinfo.value)

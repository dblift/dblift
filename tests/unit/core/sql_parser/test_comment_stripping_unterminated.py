"""A block comment that never closes is dropped, or kept when the caller must read it as text."""

import pytest

from dblift.core.sql_parser.common.comment_stripping import strip_comments_preserving_quotes

pytestmark = pytest.mark.unit


def _strip(sql, **kwargs):
    return strip_comments_preserving_quotes(
        sql, line_prefixes=["--"], has_block_comments=True, nested_block_comments=True, **kwargs
    )


def test_an_unterminated_block_comment_is_dropped_by_default():
    assert _strip("SELECT 1 /* open") == "SELECT 1"


def test_an_unterminated_block_comment_is_kept_when_asked():
    assert _strip("SELECT 1 /* open", keep_unterminated_comment=True) == "SELECT 1 /* open"


def test_a_closed_block_comment_is_dropped_either_way():
    assert _strip("SELECT 1 /* c */", keep_unterminated_comment=True) == "SELECT 1"

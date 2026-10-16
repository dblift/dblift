"""Splitting a client script costs time linear in its length.

The budget is a bound on counted work, not on time: the characters the delimiter path slices,
searches and maps back are counted on counting copies of the text and of the offset map, each shape is
run at S and at 4S, and the count must grow about four times (clean runs give 4.0 to 4.2, a per-token
search of a line or a per-statement scan from the start of the script gives about 16). A count does
not depend on the machine, so S only has to be large enough for the quadratic terms to dominate.
"""

from typing import Callable, Dict, List, Tuple

import pytest

from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC

MAX_RATIO = 5.0
COUNT = [0]


class CountingText(str):
    """A script that counts the characters sliced from it and searched in it."""

    def __getitem__(self, key):  # type: ignore[no-untyped-def]
        result = str.__getitem__(self, key)
        COUNT[0] += len(result) if isinstance(key, slice) else 1
        return result

    def _span(self, start, stop):  # type: ignore[no-untyped-def]
        start = 0 if start is None else start
        stop = len(self) if stop is None else min(stop, len(self))
        return max(0, stop - start)

    def find(self, sub, start=None, stop=None):  # type: ignore[no-untyped-def]
        args = [x for x in (start, stop) if x is not None]
        found = str.find(self, sub, *args)
        base = 0 if start is None else start
        COUNT[0] += (found - base + len(sub)) if found >= 0 else self._span(start, stop)
        return found

    def rfind(self, sub, start=None, stop=None):  # type: ignore[no-untyped-def]
        COUNT[0] += self._span(start, stop)
        return str.rfind(self, sub, *[x for x in (start, stop) if x is not None])

    def startswith(self, prefix, start=None, stop=None):  # type: ignore[no-untyped-def]
        COUNT[0] += len(prefix) if isinstance(prefix, str) else 1
        return str.startswith(self, prefix, *[x for x in (start, stop) if x is not None])

    def count(self, sub, start=None, stop=None):  # type: ignore[no-untyped-def]
        COUNT[0] += self._span(start, stop)
        return str.count(self, sub, *[x for x in (start, stop) if x is not None])


class CountingOffsets(list):  # type: ignore[type-arg]
    """The offsets of dropped carriage returns, counting every element looked at."""

    def __getitem__(self, key):  # type: ignore[no-untyped-def]
        COUNT[0] += 1
        return list.__getitem__(self, key)

    def __iter__(self):  # type: ignore[no-untyped-def]
        for item in list.__iter__(self):
            COUNT[0] += 1
            yield item


def work(script: str, spec: LexicalSpec) -> int:
    tokenizer = LexicalTokenizer(script, spec=spec)
    assert tokenizer.delimiter_script is not None
    tokenizer.sql = CountingText(tokenizer.sql)
    tokenizer.delimiter_script.text = tokenizer.sql
    tokenizer.delimiter_script.removed = CountingOffsets(tokenizer.delimiter_script.removed)
    COUNT[0] = 0
    tokenizer.tokenize()
    assert tokenizer.delimiter_script.records is not None
    return COUNT[0]


#: shape -> (script of n repeats, S).
SHAPES: Dict[str, Tuple[Callable[[int], str], int]] = {
    "one-line-of-statements-and-comments": (
        lambda n: "SELECT 1; /* c */ /*!40000 SET @a = 1 */; " * n,
        700,
    ),
    "one-line-under-a-custom-delimiter": (
        lambda n: "DELIMITER //\n" + "SELECT 1; " * n + "//",
        3500,
    ),
    "crlf-statements": (lambda n: "SELECT 1;\r\n" * n, 2800),
    "one-statement-of-comment-lines": (lambda n: "SELECT 1\n" + "# c ; x\n" * n + ";", 11000),
    "one-line-of-block-comments": (lambda n: "/**/" * n, 2000),
}


@pytest.mark.parametrize("shape", list(SHAPES))
def test_mysql_splitting_cost_grows_linearly(shape: str) -> None:
    make, size = SHAPES[shape]
    small, large = work(make(size), MYSQL_SPEC), work(make(4 * size), MYSQL_SPEC)
    assert large / small <= MAX_RATIO, (shape, small, large)


def test_the_counting_text_counts_what_a_per_token_search_would_cost() -> None:
    text = CountingText("a" * 1000)
    COUNT[0] = 0
    for _ in range(10):
        text.find("\n", 0)
    assert COUNT[0] == 10_000
    offsets: List[int] = CountingOffsets(range(100))
    COUNT[0] = 0
    assert sum(1 for _ in offsets) == 100 and COUNT[0] == 100

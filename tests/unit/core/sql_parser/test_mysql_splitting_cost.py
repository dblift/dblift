"""Splitting a client script costs time linear in its length.

The budget is a bound on counted work, not on time: the characters the delimiter path slices,
searches and maps back are counted on counting copies of the text and of the offset map, each shape is
run at S and at 4S, and the count must grow about four times (clean runs give 4.0 to 4.2, a per-token
search of a line or a per-statement scan from the start of the script gives about 16). A count does
not depend on the machine, so S only has to be large enough for the quadratic terms to dominate.
The public-path probe uses a non-string counting source after tokenizer construction. It counts the
classifier's anchored word probe and conservatively charges the rest of recognized command lines;
the line and word regex shapes are certified, but native VM steps are not counted.
"""

import ast
import inspect
import re
import textwrap
from dataclasses import replace
from typing import Callable, Dict, List, Tuple
from unittest import mock

import pytest

from dblift.core.sql_parser import delimiter_commands
from dblift.core.sql_parser import delimiter_script as delimiter_module
from dblift.core.sql_parser import lexical_engine as engine_module
from dblift.core.sql_parser.delimiter_script import DelimiterScript
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_RULES, MYSQL_SPEC
from tests.support.splitting_cost import CountingParserTokens, CountingPattern, CountingPlainText
from tests.support.splitting_cost import CountingText as GuardedText
from tests.support.splitting_cost import CountingTokens, Meter, loop_findings

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
    assert spec.delimiter_script is not None
    CountingPattern(re.compile(spec.delimiter_script.line_word), Meter())
    CountingPattern(tokenizer._word_re, Meter())
    tokenizer.sql = CountingText(tokenizer.sql)
    tokenizer.delimiter_script.text = tokenizer.sql
    tokenizer.delimiter_script.removed = CountingOffsets(tokenizer.delimiter_script.removed)
    COUNT[0] = 0
    tokenizer.tokenize()
    assert tokenizer.delimiter_script.records is not None
    assert COUNT[0] > 0
    return COUNT[0]


def public_work(script: str, *, classifier=None) -> Tuple[int, list]:
    meter = Meter()
    original_tokenizer = LexicalTokenizer
    original_classify = classifier or delimiter_module.classify_line
    original_parser = engine_module.LexicalStatementParser.__init__
    line_word = CountingPattern(re.compile(MYSQL_RULES.line_word), meter)

    def tokenizer(source, *, spec):  # type: ignore[no-untyped-def]
        wrapped = original_tokenizer(source._value, spec=spec)
        wrapped.sql = GuardedText(wrapped.sql, meter)
        wrapped.delimiter_script.text = wrapped.sql
        wrapped._word_re = CountingPattern(wrapped._word_re, meter)
        return wrapped

    def parser(self, tokens, *args, **kwargs):  # type: ignore[no-untyped-def]
        original_parser(self, CountingParserTokens(tokens, meter), *args, **kwargs)

    def classify(rules, source, start, end, delimiter):  # type: ignore[no-untyped-def]
        pos = start
        while pos < end and source[pos] in rules.blanks:
            pos += 1
        found = line_word.match(source, pos, end)
        if found is not None and found.group().upper() in delimiter_commands._known_words(rules):
            meter.add(end - found.end())  # recognized commands may inspect the rest of the line
        return original_classify(
            rules, CountingPlainText(source._value, meter), start, end, delimiter
        )

    with (
        mock.patch.object(engine_module, "LexicalTokenizer", tokenizer),
        mock.patch.object(engine_module.LexicalStatementParser, "__init__", parser),
        mock.patch.object(delimiter_module, "classify_line", classify),
    ):
        records = LexicalEngine(MYSQL_SPEC).split(GuardedText(script, meter))
    return meter.count, records


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


@pytest.mark.parametrize("shape", list(SHAPES))
def test_mysql_public_split_cost_grows_linearly(shape: str) -> None:
    make, size = SHAPES[shape]
    small, _ = public_work(make(size))
    large, _ = public_work(make(4 * size))
    assert small > 0 and large <= MAX_RATIO * small, (shape, small, large)


@pytest.mark.parametrize("scan", ("count", "find", "splitlines"))
def test_mysql_public_split_counts_a_classifier_rescan(scan: str) -> None:
    def rescanning(rules, source, start, end, delimiter):  # type: ignore[no-untyped-def]
        if scan == "count":
            source.count("\n")
        elif scan == "find":
            source.find("never-present")
        else:
            source.splitlines()
        return delimiter_commands.classify_line(rules, source, start, end, delimiter)

    make, _ = SHAPES["crlf-statements"]
    small, _ = public_work(make(100), classifier=rescanning)
    large, _ = public_work(make(400), classifier=rescanning)
    assert large > MAX_RATIO * small, (small, large)


def test_mysql_public_split_counts_a_classifier_lowercase_copy() -> None:
    def rescanning(rules, source, start, end, delimiter):  # type: ignore[no-untyped-def]
        source.lower()
        return delimiter_commands.classify_line(rules, source, start, end, delimiter)

    make, _ = SHAPES["crlf-statements"]
    small, _ = public_work(make(100), classifier=rescanning)
    large, _ = public_work(make(400), classifier=rescanning)
    assert large > MAX_RATIO * small, (small, large)


def test_mysql_classifier_guard_rejects_a_native_regex_whole_source_scan() -> None:
    source = textwrap.dedent(inspect.getsource(delimiter_commands.classify_line))
    mutant = source.replace(
        "    blanks = rules.blanks",
        "    re.search('never-present', source)\n    blanks = rules.blanks",
        1,
    )

    assert mutant != source
    assert loop_findings(ast.parse(mutant), plain_source=True, source_parameter=1)


def test_mysql_classifier_plain_source_is_guarded() -> None:
    source = textwrap.dedent(inspect.getsource(delimiter_commands.classify_line))
    assert loop_findings(ast.parse(source), plain_source=True, source_parameter=1) == []


def test_mysql_public_split_counts_repeated_record_prefixes(monkeypatch) -> None:
    original = LexicalEngine.split

    def rescanning_split(self, source):  # type: ignore[no-untyped-def]
        records = original(self, source)
        for record in records:
            source[: record.source_start].count("\n")
        return records

    monkeypatch.setattr(LexicalEngine, "split", rescanning_split)
    shape, size = SHAPES["crlf-statements"]
    small, small_records = public_work(shape(size))
    large, large_records = public_work(shape(4 * size))
    assert (len(small_records), len(large_records)) == (size, 4 * size)
    assert large > MAX_RATIO * small, (small, large)


def test_mysql_public_split_counts_delimiter_assembly_prefix_rescans(monkeypatch) -> None:
    original = DelimiterScript.end

    def rescanning_end(self, pos):  # type: ignore[no-untyped-def]
        before = len(self.records)
        original(self, pos)
        for record in self.records[before:]:
            self.text[: record.source_start].count("\n")

    monkeypatch.setattr(DelimiterScript, "end", rescanning_end)
    shape, size = SHAPES["crlf-statements"]
    small, _ = public_work(shape(size))
    large, records = public_work(shape(4 * size))
    assert len(records) == 4 * size and large > MAX_RATIO * small


def test_mysql_public_split_has_bounded_cost_and_ordered_records() -> None:
    shape, size = SHAPES["crlf-statements"]
    small, first = public_work(shape(size))
    large, records = public_work(shape(4 * size))
    assert len(first) == size and len(records) == 4 * size
    assert [r.source_start for r in records] == list(range(0, 4 * size * 11, 11))
    assert all(r.text == "SELECT 1" for r in records)
    assert small > 0 and large <= MAX_RATIO * small


def test_mysql_public_split_counts_scanner_and_passes_no_tokens_to_parser(monkeypatch) -> None:
    original = engine_module.LexicalStatementParser.__init__
    original_next = LexicalTokenizer._next_token
    scanned = []

    def checked_parser(self, tokens, *args, **kwargs):  # type: ignore[no-untyped-def]
        assert isinstance(tokens, CountingTokens)
        assert len(tokens) == 0
        original(self, tokens, *args, **kwargs)

    def checked_next(self):  # type: ignore[no-untyped-def]
        token = original_next(self)
        if token is not None:
            scanned.append(token)
        return token

    monkeypatch.setattr(engine_module.LexicalStatementParser, "__init__", checked_parser)
    monkeypatch.setattr(LexicalTokenizer, "_next_token", checked_next)
    count, records = public_work("SELECT 1;")
    assert len(scanned) > 0 and count > len(scanned)
    assert len(records) == 1


def test_mysql_public_split_detects_a_prefix_rescan_per_comment(monkeypatch) -> None:
    original = LexicalEngine._parser

    def rescanning_parser(self, script):  # type: ignore[no-untyped-def]
        parser = original(self, script)
        for start, _ in parser._comments:
            script[:start].count("\n")
        return parser

    monkeypatch.setattr(LexicalEngine, "_parser", rescanning_parser)
    make, _ = SHAPES["one-line-of-block-comments"]
    small, _ = public_work(make(100))
    large, _ = public_work(make(400))
    assert large > MAX_RATIO * small, (small, large)


def test_mysql_public_split_detects_a_prefix_copy_per_scanned_token(monkeypatch) -> None:
    original = LexicalTokenizer._next_token

    def copying_next(self):  # type: ignore[no-untyped-def]
        token = original(self)
        if token is not None:
            self.sql[: self.pos]
        return token

    monkeypatch.setattr(LexicalTokenizer, "_next_token", copying_next)
    make, _ = SHAPES["crlf-statements"]
    small, _ = public_work(make(100))
    large, _ = public_work(make(400))
    assert large > MAX_RATIO * small, (small, large)


def test_the_counting_text_counts_what_a_per_token_search_would_cost() -> None:
    text = CountingText("a" * 1000)
    COUNT[0] = 0
    for _ in range(10):
        text.find("\n", 0)
    assert COUNT[0] == 10_000
    offsets: List[int] = CountingOffsets(range(100))
    COUNT[0] = 0
    assert sum(1 for _ in offsets) == 100 and COUNT[0] == 100


@pytest.mark.parametrize(
    "mutant",
    (r"[\s\S]*?(?=\$)", r"(?![\s\S]*\$\$)", r"(?:[\s\S]*?)?"),
)
def test_mysql_line_word_regex_rejects_unbounded_scanning(mutant: str) -> None:
    CountingPattern(re.compile(MYSQL_RULES.line_word), Meter())
    with pytest.raises(AssertionError, match="uncertified regex"):
        work(
            "SELECT 1;\n",
            replace(MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, line_word=mutant)),
        )

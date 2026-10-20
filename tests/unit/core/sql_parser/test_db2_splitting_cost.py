"""Splitting a Db2 script costs a bounded number of operations per character, counted not timed.

Each stage is handed a counting object through the parameter it already has: the script text (an
object that counts the characters every slice, search and scan touches), the tokens (every
visit is counted, any access but ``tokens[i]`` fails), the comment depth marks and the lines. A
shape grows the script fourfold; the count may grow at most fivefold.

The text is not a ``str``: the interpreter cannot read it behind the counters' back, so a regular
expression run over it, an unbound ``str.find(text, ...)``, ``bytes(text)`` and ``text.__class__.lower(text)``
all fail. The only pattern allowed on it is the word pattern, wrapped so that it may be matched at a
position and is charged for what it matched. What a counter cannot see is a token value copied into a
plain container once and rescanned later; token attributes are therefore counting ints whose comparisons
and sums count, and a source check refuses the copy forms in every module the terminator path imports
(subpackages included; imports from outside the package are listed with their reason).
Not an evasion: reading the wrapper's ``_value`` attribute from engine code is a copy, and the source check
refuses it by name. Known limits: arithmetic on a copied value that is first converted with ``int()`` is not counted; an accumulator
re-joined or re-sliced per cut (the masked-text accumulator) is not seen. Compiled word regexes are
certified by shape; their native VM steps are not counted.
"""

import ast
import inspect
import re
from collections import abc
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterator, Optional, Tuple

import pytest

from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.terminator_script import TerminatorScript
from dblift.core.sql_parser.terminator_lines import read_lines
from dblift.db.plugins.db2.parser.lexical_spec import DB2_RULES, DB2_SPEC
from tests.support.splitting_cost import (
    OUTSIDE_EXEMPT,
    PACKAGE,
    CountingPattern,
    CountingText,
    CountingTokens,
    Meter,
    forbidden,
    import_closure,
)

SMALL, LARGE, BOUND = 100, 400, 5


class CountingMarks(abc.Mapping):  # type: ignore[type-arg]
    """Allows ``marks[key]`` and ``marks.get(key)``."""

    def __init__(self, marks: Dict[int, Tuple[int, bool]], meter: Meter) -> None:
        self._marks, self._meter = marks, meter

    def __getitem__(self, key: int) -> Tuple[int, bool]:
        self._meter.add(1)
        return self._marks[key]

    def get(self, key: int, default: Any = None) -> Any:
        self._meter.add(1)
        return self._marks.get(key, default)

    def __iter__(self) -> Iterator[int]:
        raise AssertionError("iterating the marks")

    def __len__(self) -> int:
        raise AssertionError("the length of the marks")


class CountingLines(list):  # type: ignore[type-arg]
    """The line list: each line visited counts one; a slice fails."""

    meter: Optional[Meter] = None

    def __iter__(self) -> Iterator[Any]:
        for line in list.__iter__(self):
            assert self.meter is not None
            self.meter.add(1)
            yield line

    def __getitem__(self, index: Any) -> Any:
        if not isinstance(index, int):
            raise AssertionError("a slice of the lines")
        assert self.meter is not None
        self.meter.add(1)
        return list.__getitem__(self, index)


def counted(script: str) -> int:
    """Operations of the line pass, the lexeme pass and the assembly on ``script``."""
    meter = Meter()
    read_lines(DB2_RULES, CountingText(script, meter))
    tokenizer = LexicalTokenizer(script, spec=DB2_SPEC)
    assert tokenizer.terminator_script is not None
    ts = tokenizer.terminator_script
    lines = CountingLines(ts.lines)
    lines.meter = meter
    ts.lines = lines
    tokenizer.sql = CountingText(tokenizer.sql, meter)
    tokenizer._word_re = CountingPattern(tokenizer._word_re, meter)
    tokens = tokenizer.tokenize()
    ts.text = CountingText(ts.text, meter)
    ts.assemble(
        CountingTokens(tokens, meter), CountingMarks(tokenizer.marks, meter), tokenizer.open_lexeme
    )
    return meter.count


def public_counted(script: str) -> Tuple[int, list]:
    meter = Meter()
    records = LexicalEngine(DB2_SPEC).split(CountingText(script, meter))
    return meter.count, records


SHAPES = {
    "one statement per line": lambda n: "INSERT INTO t VALUES (1, 'a;b');\n" * n,
    "block comment of terminator lines": lambda n: "/*\n"
    + "DROP TABLE old;\n" * n
    + "*/\nVALUES 1;\n",
    "one long line of lexemes": lambda n: "VALUES 1 " + "/* c */ 'x' \"y\" + " * n + "1;\n",
    "directive switches": lambda n: "--#SET TERMINATOR @\nVALUES 1@\n--#SET TERMINATOR ;\nVALUES 2;\n"
    * n,
    "routine body under a custom terminator": lambda n: (
        "--#SET TERMINATOR @\nCREATE PROCEDURE p()\nBEGIN\n" + "  SET x = 1;\n" * n + "END@\n"
    ),
    "directive lines inside one statement": lambda n: (
        "CREATE TABLE t (\n" + "--#SET TERMINATOR ;\n" * n + "id INT);\n"
    ),
    "comment lines inside one statement": lambda n: "VALUES 1\n" + "-- c\n" * n + ";\n",
    "nested routine bodies": lambda n: "CREATE PROCEDURE p()\n"
    + "BEGIN\n" * n
    + "END;\n" * n
    + "VALUES 1;\n",
    "string over many lines": lambda n: "VALUES 'a\n" + "b''c\n" * n + "';\n",
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_db2_splitting_cost_grows_linearly(shape):
    small, large = counted(SHAPES[shape](SMALL)), counted(SHAPES[shape](LARGE))
    assert large <= BOUND * small, (shape, small, large)


def test_db2_public_split_counts_repeated_record_prefixes(monkeypatch):
    original = LexicalEngine.split

    def rescanning_split(self, source):
        records = original(self, source)
        for record in records:
            source[: record.source_start].count("\n")
        return records

    monkeypatch.setattr(LexicalEngine, "split", rescanning_split)
    shape = SHAPES["one statement per line"]
    small, small_records = public_counted(shape(SMALL))
    large, large_records = public_counted(shape(LARGE))
    assert (len(small_records), len(large_records)) == (SMALL, LARGE)
    assert large > BOUND * small, (small, large)


def test_db2_public_split_counts_assembly_prefix_rescans(monkeypatch):
    original = TerminatorScript.assemble

    def rescanning_assemble(self, tokens, marks, open_lexeme):
        records = original(self, tokens, marks, open_lexeme)
        for record in records:
            self.text[: record.source_start].count("\n")
        return records

    monkeypatch.setattr(TerminatorScript, "assemble", rescanning_assemble)
    shape = SHAPES["one statement per line"]
    small, _ = public_counted(shape(SMALL))
    large, records = public_counted(shape(LARGE))
    assert len(records) == LARGE and large > BOUND * small


def test_db2_public_split_has_bounded_cost_and_ordered_records():
    shape = SHAPES["one statement per line"]
    small, first = public_counted(shape(SMALL))
    large, records = public_counted(shape(LARGE))
    assert len(first) == SMALL and len(records) == LARGE
    assert [r.source_start for r in records] == list(range(0, LARGE * 33, 33))
    assert all(r.text == "INSERT INTO t VALUES (1, 'a;b')" for r in records)
    assert small > 0 and large <= BOUND * small


def test_the_counters_count_what_a_rescan_would_cost():
    meter = Meter()
    text = CountingText("abc def abc", meter)
    text[1:4], text.find("def"), text.rfind("abc"), text.startswith("ab"), text.count("a")
    assert meter.count == 3 + 7 + 3 + 2 + 11
    meter.count = 0
    text.strip(), text.split(), text.upper(), text.replace("a", "b"), text.splitlines()
    assert meter.count == 5 * 11
    with pytest.raises(AssertionError):
        text[:]
    with pytest.raises(AssertionError):
        str(text)
    tokens = CountingTokens([SimpleNamespace(pos=5), SimpleNamespace(pos=6)], meter)
    meter.count = 0
    assert tokens[0].pos == 5 and meter.count == 3  # a visit, an attribute read, a comparison
    copied = [tokens[1].pos]
    meter.count = 0
    assert copied[0] < 9 and copied[0] + 1 == 7 and 3 < copied[0] and meter.count == 3
    for access in (
        lambda: tokens[0:1],
        lambda: iter(tokens),
        lambda: tokens.index(1),
        lambda: 1 in tokens,
        lambda: reversed(tokens),
        lambda: tokens.count(1),
        lambda: tokens.copy(),
    ):
        with pytest.raises(AssertionError):
            access()
    marks = CountingMarks({3: (1, True)}, meter)
    assert marks[3] == (1, True) and marks.get(4) is None
    with pytest.raises(AssertionError):
        list(marks)
    lines = CountingLines([1, 2, 3])
    lines.meter = meter
    meter.count = 0
    assert list(lines) == [1, 2, 3] and lines[1] == 2 and meter.count == 4
    with pytest.raises(AssertionError):
        lines[0:2]


@pytest.mark.parametrize(
    "mutant",
    (r"[\s\S]*?(?=\$)", r"(?![\s\S]*\$\$)", r"(?:[\s\S]*?)?"),
)
def test_db2_word_regex_rejects_unbounded_scanning(mutant, monkeypatch):
    assert (
        CountingPattern(re.compile(DB2_RULES.word), Meter()).match(
            CountingText("VALUES", Meter()), 0
        )
        is not None
    )
    monkeypatch.setattr(
        "tests.unit.core.sql_parser.test_db2_splitting_cost.DB2_SPEC",
        replace(DB2_SPEC, terminator_script=replace(DB2_RULES, word=mutant)),
    )
    with pytest.raises(AssertionError, match="uncertified regex"):
        counted("VALUES 1;\n")


def test_the_counted_text_refuses_what_it_does_not_count():
    text = CountingText("abc", Meter())
    pattern = re.compile("a")
    search = pattern.search
    for call in (
        lambda: text.lower(),
        lambda: text.encode(),
        lambda: text.casefold(),
        lambda: text + "x",
        lambda: "x" + text,
        lambda: text * 2,
        lambda: text % (),
        lambda: f"{text}",
        lambda: repr(text),
        lambda: text < "b",
        lambda: text.isspace(),
        lambda: pattern.match(text, 0),
        lambda: pattern.search(string=text),
        lambda: search(text),
        lambda: re.sub("a", "b", text),
        lambda: str.find(text, "a"),
        lambda: str.lower(text),
        lambda: bytes(text, "utf8"),
        lambda: text.__class__.lower(text),
        lambda: text[:],
        lambda: str(text),
    ):
        with pytest.raises((AssertionError, TypeError, AttributeError)):
            call()
    assert text == "abc" and text.meter.count == 3 and "b" in text


ENGINE_MODULES = ("terminator_script", "terminator_lines", "routine_body")
TOKENIZER_PASS = (
    (
        "lexical_tokenizer",
        {"_tokenize_terminator_script", "_handle_standard_string", "_handle_quoted_identifier"},
    ),
    ("base_tokenizer", {"_read_block_comment"}),
)


def test_engine_modules_never_copy_or_scan_their_inputs():
    package = Path(inspect.getfile(read_lines)).parent
    closure, outside = import_closure(package, ENGINE_MODULES)
    assert {f"{PACKAGE}.{name}" for name in ENGINE_MODULES} <= set(closure)
    assert [
        name
        for name in outside
        if name.rsplit(".", 1)[0] not in OUTSIDE_EXEMPT and name not in OUTSIDE_EXEMPT
    ] == []
    for dotted, path in closure.items():
        assert forbidden(ast.parse(path.read_text(encoding="utf-8"))) == [], dotted
    for module, functions in TOKENIZER_PASS:
        tree = ast.parse((package / f"{module}.py").read_text(encoding="utf-8"))
        found = [
            n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in functions
        ]
        assert {n.name for n in found} == functions
        for node in found:
            assert forbidden(node) == [], node.name


def test_the_source_check_sees_the_forms_it_exists_for():
    for source in (
        "x = list(tokens)",
        "x = tuple(tokens)",
        "x = str(text)",
        "x = bytes(text)",
        "x = text[:]",
        "x = str.find(text, 'a')",
        "x = re.search('a', text)",
        "x = pattern.search(text, 3)",
        "s = self.text\nx = pattern.search(s, 3)",
        "x = pattern.finditer(s)",
        "from re import search",
        "import re as r",
        "x = [tokens[i].pos for i in range(3)]",
        "x = [t for t in text]",
        "x = text._value",
    ):
        assert forbidden(ast.parse(source)) != [], source
    allowed = "x = pattern.match(line, 3)\ny = text[1:3]\nz = re.compile('a')\nw = text.split(None, 3)\nv = p.search(text[1:5])"
    assert forbidden(ast.parse(allowed)) == []
    allowed_anchored = "m = word.match(sql, pos)\nk = leading.match(token)"
    assert forbidden(ast.parse(allowed_anchored)) == []

"""Splitting a Db2 script costs a bounded number of operations per character, counted not timed.

Each stage is handed a counting object through the parameter it already has: the script text (a
``str`` subclass that counts the characters every slice, search and scan touches), the tokens (every
visit is counted, any access but ``tokens[i]`` fails), the comment depth marks and the lines. A
shape grows the script fourfold; the count may grow at most fivefold.

What the counters cannot see, a source check covers (``test_engine_modules_never_copy_or_scan_their_
inputs``): ``str.method(text)`` called unbound and regular expressions run over the text go straight to the
interpreter, and a token value copied into a plain container once and rescanned later is invisible to a
proxy. The check refuses those forms in the engine modules.
"""

import ast
import inspect
from collections import abc
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.terminator_lines import read_lines
from dblift.db.plugins.db2.parser.lexical_spec import DB2_RULES, DB2_SPEC

SMALL, LARGE, BOUND = 100, 400, 5


class Meter:
    def __init__(self) -> None:
        self.count = 0

    def add(self, amount: int) -> None:
        self.count += amount


COUNTED_METHODS = frozenset(
    "find index rfind rindex count startswith endswith split splitlines partition rpartition strip "
    "lstrip rstrip upper replace join".split()
)


class CountingText(str):
    """Counts the characters touched by every slice, search and scan; refuses a whole copy.

    Allowed, and counted: ``len`` (free), indexing and slicing (the length of the result), the search
    methods (the span scanned), ``startswith``/``endswith`` (the prefix), ``split``, ``splitlines``,
    ``partition``, ``strip``, ``upper``, ``replace`` (the whole length), ``join`` (the result), iteration,
    ``in``, ``==``, ``!=`` and ``hash`` (the whole length). Refused: every other method (``lower``,
    ``encode``, ``format``, ...), ``+``, ``*``, ``%``, ordering, ``str()``, ``repr()`` and ``[:]``.
    """

    meter: Meter

    def __new__(cls, value: str, meter: Meter) -> "CountingText":
        text = super().__new__(cls, value)
        text.meter = meter
        return text

    def __getattribute__(self, name: str) -> Any:
        if name.startswith("__") or name == "meter" or name in COUNTED_METHODS or name[0] == "_":
            return str.__getattribute__(self, name)
        raise AssertionError(f"{name} is not a counted operation on the text")

    def _refuse(self, *args: Any) -> Any:
        raise AssertionError("an operation on the text that is not counted")

    __add__ = __radd__ = __mul__ = __rmul__ = __mod__ = __rmod__ = _refuse  # type: ignore[assignment]
    __lt__ = __le__ = __gt__ = __ge__ = __format__ = __repr__ = _refuse  # type: ignore[assignment]

    def __eq__(self, other: Any) -> bool:
        self.meter.add(len(self))
        return str.__eq__(self, other)

    def __ne__(self, other: Any) -> bool:
        self.meter.add(len(self))
        return str.__ne__(self, other)

    def __hash__(self) -> int:
        self.meter.add(len(self))
        return str.__hash__(self)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, slice):
            if key.start is None and key.stop is None:
                raise AssertionError("a whole copy of the text")
            self.meter.add(len(str.__getitem__(self, key)))
        else:
            self.meter.add(1)
        return str.__getitem__(self, key)

    def __str__(self) -> str:
        raise AssertionError("str() of the text")

    def __iter__(self) -> Iterator[str]:
        self.meter.add(len(self))
        return str.__iter__(self)

    def __contains__(self, item: Any) -> bool:
        self.meter.add(len(self))
        return str.__contains__(self, item)

    def _span(self, start: Any, end: Any) -> int:
        stop = len(self) if end is None else min(end, len(self))
        return max(stop - (start or 0), 0)

    def find(self, sub: str, start: Any = None, end: Any = None) -> int:
        found = str.find(self, sub, start or 0, len(self) if end is None else end)
        self.meter.add(found - (start or 0) + len(sub) if found >= 0 else self._span(start, end))
        return found

    def index(self, sub: str, start: Any = None, end: Any = None) -> int:
        found = str.index(self, sub, start or 0, len(self) if end is None else end)
        self.meter.add(found - (start or 0) + len(sub))
        return found

    def rfind(self, sub: str, start: Any = None, end: Any = None) -> int:
        stop = len(self) if end is None else end
        found = str.rfind(self, sub, start or 0, stop)
        self.meter.add(stop - found if found >= 0 else self._span(start, end))
        return found

    def rindex(self, sub: str, start: Any = None, end: Any = None) -> int:
        stop = len(self) if end is None else end
        found = str.rindex(self, sub, start or 0, stop)
        self.meter.add(stop - found)
        return found

    def count(self, sub: str, start: Any = None, end: Any = None) -> int:
        self.meter.add(self._span(start, end))
        return str.count(self, sub, start or 0, len(self) if end is None else end)

    def startswith(self, prefix: Any, start: Any = None, end: Any = None) -> bool:
        self.meter.add(sum(map(len, prefix)) if isinstance(prefix, tuple) else len(prefix))
        return str.startswith(self, prefix, start or 0, len(self) if end is None else end)

    def endswith(self, suffix: Any, start: Any = None, end: Any = None) -> bool:
        self.meter.add(sum(map(len, suffix)) if isinstance(suffix, tuple) else len(suffix))
        return str.endswith(self, suffix, start or 0, len(self) if end is None else end)

    def _whole(self, name: str, *args: Any) -> Any:
        self.meter.add(len(self))
        return getattr(str, name)(self, *args)

    def split(self, *args: Any) -> List[str]:
        return self._whole("split", *args)

    def splitlines(self, *args: Any) -> List[str]:
        return self._whole("splitlines", *args)

    def partition(self, sep: str) -> Tuple[str, str, str]:
        return self._whole("partition", sep)

    def rpartition(self, sep: str) -> Tuple[str, str, str]:
        return self._whole("rpartition", sep)

    def strip(self, *args: Any) -> str:
        return self._whole("strip", *args)

    def lstrip(self, *args: Any) -> str:
        return self._whole("lstrip", *args)

    def rstrip(self, *args: Any) -> str:
        return self._whole("rstrip", *args)

    def upper(self) -> str:
        return self._whole("upper")

    def replace(self, *args: Any) -> str:
        return self._whole("replace", *args)

    def join(self, items: Any) -> str:
        result = str.join(self, items)
        self.meter.add(len(result))
        return result


class TokenProxy:
    def __init__(self, token: Any, meter: Meter) -> None:
        self._token, self._meter = token, meter

    def __getattr__(self, name: str) -> Any:
        self._meter.add(1)
        return getattr(self._token, name)


class CountingTokens(abc.Sequence):  # type: ignore[type-arg]
    """Allows ``len`` and ``tokens[i]``; every visit counts one, every attribute read counts one."""

    def __init__(self, tokens: List[Any], meter: Meter) -> None:
        self._tokens, self._meter = tokens, meter

    def __len__(self) -> int:
        return len(self._tokens)

    def __getitem__(self, index: Any) -> Any:
        if not isinstance(index, int):
            raise AssertionError(f"tokens[{index!r}]")
        self._meter.add(1)
        return TokenProxy(self._tokens[index], self._meter)

    def _refuse(self, *args: Any) -> Any:
        raise AssertionError("an access other than tokens[i]")

    __iter__ = __contains__ = __reversed__ = index = count = copy = _refuse  # type: ignore[assignment]


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
    tokens = tokenizer.tokenize()
    ts.text = CountingText(ts.text, meter)
    ts.assemble(
        CountingTokens(tokens, meter), CountingMarks(tokenizer.marks, meter), tokenizer.open_lexeme
    )
    return meter.count


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
    assert tokens[0].pos == 5 and meter.count == 2
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


def test_the_counted_text_refuses_what_it_does_not_count():
    text = CountingText("abc", Meter())
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
    ):
        with pytest.raises(AssertionError):
            call()
    assert text == "abc" and text.meter.count == 3 and "b" in text


ENGINE_SOURCES = [
    "terminator_script.py",
    "terminator_lines.py",
    "routine_body.py",
]
SCANNED_NAMES = {"text", "sql", "tokens", "marks", "lines"}


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def forbidden(tree: ast.AST, exempt_regex: bool = False) -> List[str]:
    """Forms the counters cannot see: copies, unbound str methods, regular expressions over the text."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in {
                "list",
                "tuple",
                "str",
                "sorted",
                "set",
                "dict",
            }:
                found.append(f"{func.id}() at line {node.lineno}")
            if isinstance(func, ast.Attribute) and _name(func.value) == "str":
                found.append(f"str.{func.attr}() at line {node.lineno}")
            if (
                isinstance(func, ast.Attribute)
                and _name(func.value) == "re"
                and func.attr != "compile"
            ):
                found.append(f"re.{func.attr}() at line {node.lineno}")
            if (
                not exempt_regex
                and isinstance(func, ast.Attribute)
                and func.attr
                in {"match", "search", "fullmatch", "finditer", "findall", "sub", "subn"}
                and node.args
                and _name(node.args[0]) in {"text", "sql"}
            ):
                found.append(f"{func.attr}() over the text at line {node.lineno}")
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            if node.slice.lower is None and node.slice.upper is None:
                found.append(f"[:] at line {node.lineno}")
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Subscript) and _name(inner.value) in {"tokens", "marks"}:
                    found.append(f"comprehension over tokens at line {node.lineno}")
                    break
            for generator in node.generators:
                if _name(generator.iter) in SCANNED_NAMES - {"lines"}:
                    found.append(
                        f"comprehension over {_name(generator.iter)} at line {node.lineno}"
                    )
    return found


def test_engine_modules_never_copy_or_scan_their_inputs():
    package = Path(inspect.getfile(read_lines)).parent
    for name in ENGINE_SOURCES:
        tree = ast.parse((package / name).read_text(encoding="utf-8"))
        assert forbidden(tree) == [], name
    tokenizer = ast.parse((package / "lexical_tokenizer.py").read_text(encoding="utf-8"))
    pass_ = next(
        node
        for node in ast.walk(tokenizer)
        if isinstance(node, ast.FunctionDef) and node.name == "_tokenize_terminator_script"
    )
    assert (
        forbidden(pass_, exempt_regex=True) == []
    )  # the word pattern is matched at a position: bounded


def test_the_source_check_sees_the_forms_it_exists_for():
    for source in (
        "x = list(tokens)",
        "x = tuple(tokens)",
        "x = str(text)",
        "x = text[:]",
        "x = str.find(text, 'a')",
        "x = re.search('a', text)",
        "x = pattern.search(text, 3)",
        "x = [tokens[i].pos for i in range(3)]",
        "x = [t for t in text]",
    ):
        assert forbidden(ast.parse(source)) != [], source
    assert (
        forbidden(ast.parse("x = pattern.match(line, 3)\ny = text[1:3]\nz = re.compile('a')")) == []
    )

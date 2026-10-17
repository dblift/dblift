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
refuses it by name. Known limit: arithmetic on a copied value that is first converted with ``int()`` is not counted.
"""

import ast
import inspect
import re
from collections import abc
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

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


class CountingText:
    """The text, as an object that is not a ``str``: every operation on it is counted or refused.

    A ``str`` subclass can be read by the interpreter without calling any method of it (a regular
    expression, an unbound ``str.find(text, ...)``, ``bytes(text)``). This is not a ``str``, so all of
    those fail with a ``TypeError``; what remains is counted. Counted: ``len`` (free), indexing and
    slicing (the length of the result; slices and characters are plain strings), the search methods (the
    span scanned), ``startswith``/``endswith`` (the prefix), ``split``, ``splitlines``, ``partition``,
    ``strip``, ``upper``, ``replace`` (the whole length), ``join`` (the result), iteration, ``in``,
    ``==``, ``!=`` and ``hash`` (the whole length). Refused: every other method, ``str()``, ``repr()``,
    formatting and ``[:]``. Not a ``str`` also means ``+``, ``%``, ``*`` and ordering are undefined.
    """

    def __init__(self, value: str, meter: "Meter") -> None:
        self._value, self.meter = value, meter

    def __len__(self) -> int:
        return len(self._value)

    def __getitem__(self, key: Any) -> str:
        if isinstance(key, slice):
            if key.start is None and key.stop is None:
                raise AssertionError("a whole copy of the text")
            result = self._value[key]
            self.meter.add(len(result))
            return result
        self.meter.add(1)
        return self._value[key]

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"{name} is not a counted operation on the text")

    def __str__(self) -> str:
        raise AssertionError("str() of the text")

    __repr__ = __format__ = __str__  # type: ignore[assignment]

    def __iter__(self) -> Iterator[str]:
        self.meter.add(len(self._value))
        return iter(self._value)

    def __contains__(self, item: Any) -> bool:
        self.meter.add(len(self._value))
        return item in self._value

    def __eq__(self, other: Any) -> bool:
        self.meter.add(len(self._value))
        return self._value == (other._value if isinstance(other, CountingText) else other)

    def __ne__(self, other: Any) -> bool:
        return not self == other

    def __hash__(self) -> int:
        self.meter.add(len(self._value))
        return hash(self._value)

    def _span(self, start: Any, end: Any) -> int:
        stop = len(self._value) if end is None else min(end, len(self._value))
        return max(stop - (start or 0), 0)

    def find(self, sub: str, start: Any = None, end: Any = None) -> int:
        found = self._value.find(sub, start or 0, len(self._value) if end is None else end)
        self.meter.add(found - (start or 0) + len(sub) if found >= 0 else self._span(start, end))
        return found

    def index(self, sub: str, start: Any = None, end: Any = None) -> int:
        found = self._value.index(sub, start or 0, len(self._value) if end is None else end)
        self.meter.add(found - (start or 0) + len(sub))
        return found

    def rfind(self, sub: str, start: Any = None, end: Any = None) -> int:
        stop = len(self._value) if end is None else end
        found = self._value.rfind(sub, start or 0, stop)
        self.meter.add(stop - found if found >= 0 else self._span(start, end))
        return found

    def rindex(self, sub: str, start: Any = None, end: Any = None) -> int:
        stop = len(self._value) if end is None else end
        found = self._value.rindex(sub, start or 0, stop)
        self.meter.add(stop - found)
        return found

    def count(self, sub: str, start: Any = None, end: Any = None) -> int:
        self.meter.add(self._span(start, end))
        return self._value.count(sub, start or 0, len(self._value) if end is None else end)

    def startswith(self, prefix: Any, start: Any = None, end: Any = None) -> bool:
        self.meter.add(sum(map(len, prefix)) if isinstance(prefix, tuple) else len(prefix))
        return self._value.startswith(prefix, start or 0, len(self._value) if end is None else end)

    def endswith(self, suffix: Any, start: Any = None, end: Any = None) -> bool:
        self.meter.add(sum(map(len, suffix)) if isinstance(suffix, tuple) else len(suffix))
        return self._value.endswith(suffix, start or 0, len(self._value) if end is None else end)

    def _whole(self, name: str, *args: Any) -> Any:
        self.meter.add(len(self._value))
        return getattr(self._value, name)(*args)

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
        result = self._value.join(items)
        self.meter.add(len(result))
        return result


class CountingPattern:
    """A compiled pattern that may only be matched at a position of the counted text (the word pattern)."""

    def __init__(self, pattern: Any, meter: "Meter") -> None:
        self._pattern, self._meter = pattern, meter

    def match(self, text: CountingText, pos: int) -> Any:
        found = self._pattern.match(text._value, pos)
        self._meter.add(found.end() - pos if found else 1)
        return found


class CountingInt(int):
    """An int whose comparisons and sums count one operation each and return plain values.

    A token position copied into a container and rescanned later still counts every comparison.
    """

    meter: Meter

    def __new__(cls, value: int, meter: Meter) -> "CountingInt":
        number = super().__new__(cls, value)
        number.meter = meter
        return number

    def _op(self, other: Any, operation: Callable[[int, int], Any]) -> Any:
        self.meter.add(1)
        return operation(int(self), int(other))

    def __lt__(self, other: Any) -> bool:
        return self._op(other, lambda a, b: a < b)

    def __le__(self, other: Any) -> bool:
        return self._op(other, lambda a, b: a <= b)

    def __gt__(self, other: Any) -> bool:
        return self._op(other, lambda a, b: a > b)

    def __ge__(self, other: Any) -> bool:
        return self._op(other, lambda a, b: a >= b)

    def __eq__(self, other: Any) -> bool:  # type: ignore[override]
        return self._op(other, lambda a, b: a == b)

    def __ne__(self, other: Any) -> bool:  # type: ignore[override]
        return self._op(other, lambda a, b: a != b)

    def __add__(self, other: Any) -> int:  # type: ignore[override]
        return self._op(other, lambda a, b: a + b)

    def __radd__(self, other: Any) -> int:  # type: ignore[override]
        return self._op(other, lambda a, b: b + a)

    def __sub__(self, other: Any) -> int:  # type: ignore[override]
        return self._op(other, lambda a, b: a - b)

    def __rsub__(self, other: Any) -> int:  # type: ignore[override]
        return self._op(other, lambda a, b: b - a)

    __hash__ = int.__hash__


class TokenProxy:
    def __init__(self, token: Any, meter: Meter) -> None:
        self._token, self._meter = token, meter

    def __getattr__(self, name: str) -> Any:
        self._meter.add(1)
        value = getattr(self._token, name)
        return CountingInt(value, self._meter) if type(value) is int else value


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
    tokenizer._word_re = CountingPattern(tokenizer._word_re, meter)
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
SCANNED_NAMES = {"text", "sql", "tokens", "marks"}
REGEX_METHODS = {"search", "match", "finditer", "findall", "sub", "subn", "split", "fullmatch"}
BOUNDED_ARGUMENTS = {"line", "token", "statement"}  # a slice of the text, never the text
COPIES = {"list", "tuple", "str", "sorted", "set", "dict", "bytes", "bytearray", "memoryview"}


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _regex_call(node: ast.Call) -> bool:
    """A call shaped like a regular expression run, unless it reads a bounded piece or an anchored position."""
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr in REGEX_METHODS):
        return False
    first = node.args[0] if node.args else None
    if first is None or isinstance(first, (ast.Constant, ast.Subscript)):
        return False  # str.split() and friends, or a slice of the text
    if isinstance(first, ast.Name) and first.id in BOUNDED_ARGUMENTS:
        return False
    return not (
        func.attr == "match" and len(node.args) + len(node.keywords) >= 2
    )  # anchored at a position


def forbidden(tree: ast.AST) -> List[str]:
    """Forms the counters cannot see: copies, unbound str methods, regular expressions over the text."""
    found = []
    for node in ast.walk(tree):
        where = f"line {getattr(node, 'lineno', 0)}"
        if isinstance(node, ast.Import):
            found += [
                f"import re as {a.asname} at {where}"
                for a in node.names
                if a.name == "re" and a.asname
            ]
        if isinstance(node, ast.ImportFrom) and node.module == "re":
            found.append(f"from re import at {where}")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in COPIES:
                found.append(f"{func.id}() at {where}")
            if isinstance(func, ast.Attribute) and _name(func.value) == "str":
                found.append(f"str.{func.attr}() at {where}")
            if (
                isinstance(func, ast.Attribute)
                and _name(func.value) == "re"
                and func.attr != "compile"
            ):
                found.append(f"re.{func.attr}() at {where}")
            if _regex_call(node):
                found.append(f"regular expression over unbounded input at {where}")
        if isinstance(node, ast.Attribute) and node.attr == "_value":
            found.append(f"the wrapper's _value at {where}")
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            if node.slice.lower is None and node.slice.upper is None:
                found.append(f"[:] at {where}")
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Subscript) and _name(inner.value) in {"tokens", "marks"}:
                    found.append(f"comprehension over tokens at {where}")
                    break
            for generator in node.generators:
                if _name(generator.iter) in SCANNED_NAMES:
                    found.append(f"comprehension over {_name(generator.iter)} at {where}")
    return found


#: Imports from outside ``dblift.core.sql_parser`` that the scanned modules may have, each with the reason it
#: needs no scan: it never receives the text, the tokens or the marks. Anything else fails the test.
OUTSIDE_EXEMPT = {"dblift.core.exceptions": "exception classes only"}
PACKAGE = "dblift.core.sql_parser"


def _module_file(root: Path, dotted: str) -> Optional[Path]:
    parts = dotted.split(".")[len(PACKAGE.split(".")) :]
    for candidate in (
        root.joinpath(*parts).with_suffix(".py"),
        root.joinpath(*parts, "__init__.py"),
    ):
        if parts and candidate.exists():
            return candidate
    return None


def import_closure(root: Path, start: Tuple[str, ...]) -> Tuple[Dict[str, Path], List[str]]:
    """The modules of the package (subpackages included) the terminator path imports, and the outside imports."""
    found: Dict[str, Path] = {}
    outside: List[str] = []
    todo = [f"{PACKAGE}.{name}" for name in start]
    while todo:
        dotted = todo.pop()
        if dotted in found:
            continue
        path = _module_file(root, dotted)
        assert path is not None, dotted
        found[dotted] = path
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                base = node.module
                if node.level:  # a relative import resolves against the importing module's package
                    package = dotted if path.name == "__init__.py" else dotted.rsplit(".", 1)[0]
                    parts = package.split(".")[: len(package.split(".")) - node.level + 1]
                    base = ".".join(parts + ([node.module] if node.module else []))
                names = [base] + [f"{base}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                continue
            else:
                continue
            for name in names:
                if name.startswith(PACKAGE + ".") and _module_file(root, name) is not None:
                    todo.append(name)
                elif (
                    name.startswith("dblift.")
                    and not name.startswith(PACKAGE)
                    and name not in outside
                ):
                    outside.append(name)
    return found, sorted(outside)


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

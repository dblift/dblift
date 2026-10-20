"""Counting stand-ins and the source check shared by the splitting cost tests.

The text, the tokens and the compiled patterns of a stage are swapped for objects that count what is
done to them; ``forbidden`` finds the copy and rescan forms that no counter can see.
"""

import ast
import re
from collections import abc
from pathlib import Path
from re import _parser as regex_parser
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple


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
    """A compiled pattern with a certified local scan shape, not a regex VM-step counter."""

    def __init__(self, pattern: Any, meter: "Meter", *, allow_empty: bool = False) -> None:
        data = list(regex_parser.parse(pattern.pattern, pattern.flags))
        assert _certified_regex(pattern, data), f"uncertified regex: {pattern.pattern!r}"
        assert allow_empty or pattern.match("") is None, f"uncertified regex: {pattern.pattern!r}"
        self._pattern, self._meter = pattern, meter
        self._allow_empty = allow_empty
        self._tag_data = data if len(data) == 3 and _tag_or_parameter(data) else None

    def match(self, text: CountingText, pos: int, endpos: Optional[int] = None) -> Any:
        found = self._pattern.match(
            text._value, pos, len(text._value) if endpos is None else endpos
        )
        assert found is None or found.end() > pos or self._allow_empty, "an empty lexeme match"
        self._meter.add(
            found.end() - pos if found else _tag_failure_cost(self._tag_data, text, pos, endpos)
        )
        return found

    def search(self, text: CountingText, pos: int, endpos: Optional[int] = None) -> Any:
        """Charged for the span it scans: to the match, or to the end of the text when there is none."""
        stop = len(text._value) if endpos is None else endpos
        found = self._pattern.search(text._value, pos, stop)
        self._meter.add((found.end() if found else stop) - pos)
        return found


def _ranges(token: Any) -> Optional[List[Tuple[int, int]]]:
    """A positive one-character class; categories and arbitrary assertions are not certified."""
    op, value = token
    if op == regex_parser.LITERAL:
        return [(value, value)]
    if op != regex_parser.IN:
        return None
    ranges = []
    for kind, member in value:
        if kind == regex_parser.LITERAL:
            ranges.append((member, member))
        elif kind == regex_parser.RANGE:
            ranges.append(member)
        else:
            return None
    return ranges


def _member(token: Any, char: str) -> bool:
    ranges = _ranges(token)
    return ranges is not None and any(lo <= ord(char) <= hi for lo, hi in ranges)


def _tag_failure_cost(
    data: Optional[List[Any]], text: CountingText, pos: int, endpos: Optional[int]
) -> int:
    """Charge the failed dollar-tag probe through its local identifier run."""
    if data is None:
        return 1
    end = len(text._value) if endpos is None else min(endpos, len(text._value))
    if pos >= end or not _member(data[0], text._value[pos]):
        return 1
    body = _optional(data[1])
    assert body is not None
    run = _run(body[1])
    assert run is not None
    cursor = pos + 1
    if cursor < end and _member(body[0], text._value[cursor]):
        cursor += 1
        while cursor < end and any(_member(part, text._value[cursor]) for part in run):
            cursor += 1
    return cursor - pos + 1


def _atom(token: Any) -> bool:
    """Also allow a negated class for a trailing comment run."""
    if _ranges(token) is not None:
        return True
    op, value = token
    return (
        op == regex_parser.IN
        and bool(value)
        and value[0][0] == regex_parser.NEGATE
        and all(kind in (regex_parser.LITERAL, regex_parser.RANGE) for kind, _ in value[1:])
    )


def _disjoint(left: Any, right: Any) -> bool:
    a, b = _ranges(left), _ranges(right)
    return (
        a is not None
        and b is not None
        and all(hi_a < lo_b or hi_b < lo_a for lo_a, hi_a in a for lo_b, hi_b in b)
    )


def _optional(token: Any) -> Optional[List[Any]]:
    op, value = token
    if op == regex_parser.MAX_REPEAT and value[:2] == (0, 1):
        return list(value[2])
    return None


def _run(token: Any) -> Optional[List[Any]]:
    """A greedy character run, optionally with a distinct one-character separator."""
    op, value = token
    if (
        op != regex_parser.MAX_REPEAT
        or value[0] not in (0, 1)
        or value[1] != regex_parser.MAXREPEAT
    ):
        return None
    body = list(value[2])
    if len(body) == 1 and _atom(body[0]):
        return [body[0]]
    if len(body) == 2 and _atom(body[1]):
        prefix = _optional(body[0])
        if prefix is not None and len(prefix) == 1 and _disjoint(prefix[0], body[1]):
            return [prefix[0], body[1]]
    return None


def _simple(data: List[Any]) -> bool:
    """Fixed character tests followed by at most one final greedy run."""
    return bool(data) and (
        all(_atom(token) for token in data)
        or (all(_atom(token) for token in data[:-1]) and _run(data[-1]) is not None)
    )


def _number(data: List[Any]) -> bool:
    if len(data) != 4 or not _atom(data[0]) or _run(data[1]) is None:
        return False
    decimal, exponent = _optional(data[2]), _optional(data[3])
    if decimal is None or exponent is None or len(decimal) != 2 or len(exponent) != 4:
        return False
    digits = _run(data[1])
    assert digits is not None
    decimal_digits = _optional(decimal[1])
    sign = _optional(exponent[1])
    return (
        _atom(decimal[0])
        and all(_disjoint(decimal[0], digit) for digit in digits)
        and decimal_digits is not None
        and len(decimal_digits) == 2
        and _atom(decimal_digits[0])
        and _run(decimal_digits[1]) is not None
        and _atom(exponent[0])
        and all(_disjoint(exponent[0], digit) for digit in digits)
        and _disjoint(exponent[0], decimal[0])
        and sign is not None
        and len(sign) == 1
        and _atom(sign[0])
        and _disjoint(sign[0], exponent[2])
        and _atom(exponent[2])
        and _run(exponent[3]) is not None
    )


def _tag_or_parameter(data: List[Any]) -> bool:
    if len(data) not in (2, 3) or data[0][0] != regex_parser.LITERAL:
        return False
    body = _optional(data[1])
    if body is None or len(body) != 2 or not _atom(body[0]):
        return False
    run = _run(body[1])
    if (
        run is None
        or not _disjoint(data[0], body[0])
        or not all(_disjoint(data[0], part) for part in run)
    ):
        return False
    return len(data) == 2 or data[2] == data[0]


def _certified_regex(pattern: Any, data: List[Any]) -> bool:
    """Accept only the deterministic lexeme shapes used by this cost harness.

    This is deliberately a syntax certificate: Python's native regex VM does not expose a work
    counter. Unknown assertions, lazy scans, broad categories and ambiguous repetitions are refused.
    """
    if pattern.flags != re.UNICODE:
        return False
    if _simple(data) or _number(data) or _tag_or_parameter(data):
        return True
    if len(data) == 1 and data[0][0] == regex_parser.BRANCH:
        alternatives = data[0][1][1]
        if len(alternatives) < 2 or any(not alt for alt in alternatives):
            return False
        first = [(_run(alt[0]) or [alt[0]])[0] for alt in alternatives]
        return all(_simple(list(alt)) for alt in alternatives) and all(
            _disjoint(left, right)
            for index, left in enumerate(first)
            for right in first[index + 1 :]
        )
    return False


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


class CountingParserTokens(CountingTokens):
    """Count iteration and slices as token visits when a public parser consumes the stream."""

    def __getitem__(self, index: Any) -> Any:
        if isinstance(index, slice):
            return [CountingTokens.__getitem__(self, i) for i in range(*index.indices(len(self)))]
        return CountingTokens.__getitem__(self, index)

    def __iter__(self) -> Iterator[Any]:
        for index in range(len(self)):
            yield self[index]


SCANNED_NAMES = {"text", "sql", "tokens", "marks", "source"}
SLICED_TEXTS = {"text", "sql", "source"}  # names that hold a whole script or statement
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
    if isinstance(first, ast.Subscript) and isinstance(first.slice, ast.Slice):
        if first.slice.lower is not None and first.slice.upper is None:
            return True  # a copy of the rest of the text
    if first is None or isinstance(first, (ast.Constant, ast.Subscript)):
        return False  # str.split() and friends, or a bounded slice of the text
    if isinstance(first, ast.Name) and first.id in BOUNDED_ARGUMENTS:
        return False
    return not (
        func.attr == "match" and len(node.args) + len(node.keywords) >= 2
    )  # anchored at a position


def _is_text(node: ast.AST) -> bool:
    """A scanned text: a bare name, or one on ``self``; an attribute of another object is skipped."""
    if isinstance(node, ast.Name):
        return node.id in SLICED_TEXTS
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr in SLICED_TEXTS
    )


def _has_slice(node: ast.AST, of: Optional[str] = None) -> bool:
    """Whether the expression slices a name (any name when ``of`` is None)."""
    return any(
        isinstance(n, ast.Subscript)
        and isinstance(n.slice, ast.Slice)
        and (of is None or (isinstance(n.value, ast.Name) and n.value.id == of))
        for n in ast.walk(node)
    )


def loop_findings(tree: ast.AST) -> List[str]:
    """Copies of the rest of a text, and rebuilds of a string from itself, inside a loop body."""
    found = []
    loops = [n for n in ast.walk(tree) if isinstance(n, (ast.For, ast.While))]
    for loop in loops:
        for statement in loop.body:
            for node in ast.walk(statement):
                where = f"line {getattr(node, 'lineno', 0)}"
                if (
                    isinstance(node, ast.Subscript)
                    and isinstance(node.slice, ast.Slice)
                    and node.slice.lower is not None
                    and node.slice.upper is None
                    and _is_text(node.value)
                ):
                    found.append(f"open-ended slice of a text in a loop at {where}")
                if (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and _has_slice(node.value, node.targets[0].id)
                ):
                    found.append(f"string rebuilt from its own slices in a loop at {where}")
                if isinstance(node, ast.AugAssign) and _has_slice(node.value):
                    found.append(f"string grown by slices in a loop at {where}")
    return found


def forbidden(tree: ast.AST) -> List[str]:
    """Forms the counters cannot see: copies, unbound str methods, regular expressions over the text."""
    found = loop_findings(tree)
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

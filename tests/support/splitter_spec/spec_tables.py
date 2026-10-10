"""Compile the conformance tables of the splitter specs into rows.

Reads section ``## 10. Conformance examples`` of every ``<dialect>.md`` in
``docs/architecture/sql-splitter/`` (``README.md`` excepted) under the rules
the README states in "Conformance table format":

* ``#`` is the row id, unique within a spec;
* ``Script`` holds exactly one code span (one or two backticks); inside it
  ``\\n`` is a newline, ``\\t`` a tab, ``\\\\`` a backslash and ``\\|`` a pipe
  (GFM needs it for a pipe inside a table cell), nothing else is escaped;
* ``Statements returned`` holds one code span per expected statement,
  separated by `` · ``, with the same escapes; `` `(empty)` `` alone means
  no statement. When the **first** code span names an exception
  (``UnsupportedMetaCommandError``, ``UnsafeStatementSplitError`` or
  ``error`` for any), the row expects a refusal and the later code spans are
  explanatory (the directive or token that triggers it). Prose outside code
  spans is ignored. A cell whose prose (outside code spans) contains "to
  verify" or "depends on" compiles with status ``to_verify``.

Anything else is a ``SpecFormatError`` naming the file and the row: the
compiler is a lint for the specs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from tests.support.splitter_spec.splitting import normalize

ERROR_KEYWORDS = ("UnsupportedMetaCommandError", "UnsafeStatementSplitError", "error")
EMPTY_MARKER = "(empty)"

_SECTION_10 = re.compile(r"^## 10\.")
_ANY_SECTION = re.compile(r"^## ")
_SEPARATOR_CELL = re.compile(r"^:?-+:?$")
_TO_VERIFY = re.compile(r"to verify|depends on", re.IGNORECASE)
_ESCAPE = re.compile(r"\\(.)", re.DOTALL)
_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", "|": "|"}


class SpecFormatError(ValueError):
    """A conformance row (or spec) the compiler cannot read."""


@dataclass(frozen=True)
class Expectation:
    """Either the normalised statements a row expects, or the error it expects."""

    statements: Optional[tuple[str, ...]] = None
    error: Optional[str] = None

    def __post_init__(self) -> None:
        if (self.statements is None) == (self.error is None):
            raise ValueError("an Expectation has exactly one of statements or error")


@dataclass(frozen=True)
class ConformanceRow:
    dialect: str
    row_id: str
    script: str
    expectation: Expectation
    status: Literal["testable", "to_verify"]


def load_conformance_rows(spec_dir: Path) -> list[ConformanceRow]:
    """Compile every ``*.md`` spec in ``spec_dir`` except ``README.md``, in file order."""
    rows: list[ConformanceRow] = []
    for path in sorted(Path(spec_dir).glob("*.md")):
        if path.name == "README.md":
            continue
        rows.extend(_compile_spec(path))
    return rows


def _compile_spec(path: Path) -> list[ConformanceRow]:
    dialect = path.stem
    rows: list[ConformanceRow] = []
    for row_id, script_cell, statements_cell in _table_rows(path, _section_10_lines(path)):
        where = f"{path.name} row {row_id}"
        script = _single_code_span(script_cell, where)
        expectation, status = _expectation(statements_cell, where)
        rows.append(ConformanceRow(dialect, row_id, script, expectation, status))
    return rows


def _section_10_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if _SECTION_10.match(line)), None)
    if start is None:
        raise SpecFormatError(f"{path.name}: no '## 10.' section")
    end = next(
        (i for i in range(start + 1, len(lines)) if _ANY_SECTION.match(lines[i])), len(lines)
    )
    return lines[start + 1 : end]


def _table_rows(path: Path, lines: list[str]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = _split_cells(stripped, f"{path.name} line {stripped[:40]!r}")
        if not cells:
            continue
        first = cells[0].strip()
        if first == "#" or all(_SEPARATOR_CELL.match(c.strip() or "-") for c in cells):
            continue
        if len(cells) != 3:
            raise SpecFormatError(
                f"{path.name} row {first}: expected 3 cells (#, Script, Statements), got {len(cells)}"
            )
        rows.append((first, cells[1], cells[2]))
    return rows


def _split_cells(line: str, where: str) -> list[str]:
    """Split a table row on ``|`` that is outside code spans."""
    body = line[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells: list[str] = []
    current: list[str] = []
    open_fence = 0
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "`":
            run = _backtick_run(body, i)
            if open_fence == 0:
                open_fence = run
            elif run == open_fence:
                open_fence = 0
            current.append("`" * run)
            i += run
            continue
        if ch == "|" and open_fence == 0:
            cells.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    if open_fence:
        raise SpecFormatError(f"{where}: unbalanced backticks")
    cells.append("".join(current))
    return cells


def _backtick_run(text: str, start: int) -> int:
    end = start
    while end < len(text) and text[end] == "`":
        end += 1
    return end - start


def _code_spans(cell: str, where: str) -> list[str]:
    """CommonMark code spans of ``cell``, with one framing space pair removed."""
    spans: list[str] = []
    i = 0
    while i < len(cell):
        if cell[i] != "`":
            i += 1
            continue
        fence = _backtick_run(cell, i)
        j = i + fence
        while True:
            k = cell.find("`" * fence, j)
            if k < 0:
                raise SpecFormatError(f"{where}: unterminated code span {cell[i:i + fence + 20]!r}")
            if _backtick_run(cell, k) == fence:
                break
            j = k + _backtick_run(cell, k)
        content = cell[i + fence : k]
        if len(content) >= 2 and content[0] == " " and content[-1] == " " and content.strip():
            content = content[1:-1]
        spans.append(content)
        i = k + fence
    return spans


def _prose(cell: str, spans: list[str]) -> str:
    """The cell with its code spans removed (markers like 'to verify' count only in prose)."""
    prose = cell
    for span in spans:
        prose = prose.replace(span, "", 1)
    return prose


def _decode(text: str) -> str:
    return _ESCAPE.sub(lambda m: _ESCAPES.get(m.group(1), m.group(0)), text)


def _single_code_span(cell: str, where: str) -> str:
    spans = _code_spans(cell, where)
    if len(spans) != 1:
        raise SpecFormatError(
            f"{where}: the Script cell must hold exactly one code span, found {len(spans)}"
        )
    return _decode(spans[0])


def _expectation(cell: str, where: str) -> tuple[Expectation, Literal["testable", "to_verify"]]:
    spans = _code_spans(cell, where)
    status: Literal["testable", "to_verify"] = (
        "to_verify" if _TO_VERIFY.search(_prose(cell, spans)) else "testable"
    )
    if not spans:
        if status == "to_verify":
            return Expectation(statements=()), status
        raise SpecFormatError(
            f"{where}: the Statements cell has no code span, no error keyword, no (empty) "
            "marker and is not marked 'to verify'"
        )
    if spans[0] in ERROR_KEYWORDS:
        return Expectation(error=spans[0]), status
    if spans[0].startswith(ERROR_KEYWORDS):
        raise SpecFormatError(
            f"{where}: an error keyword must be the whole first code span, got {spans[0]!r}"
        )
    if spans == [EMPTY_MARKER]:
        return Expectation(statements=()), status
    for span in spans:
        if span in ERROR_KEYWORDS or span == EMPTY_MARKER:
            raise SpecFormatError(
                f"{where}: {span!r} must be the only code span of the Statements cell"
            )
    return Expectation(statements=normalize(_decode(s) for s in spans)), status

"""Compare two statement-edge recordings; only one kind of difference is allowed.

The allowed difference: a character of ``str.isspace()`` that is not one of the dialect's
``text_blanks`` sits at a statement's edge in the new recording where the old recording had trimmed it.
Both sides are cut into ``leading run + core + trailing run`` (a run is made of the characters that
class covers, the blanks included); the cores must be equal, each new run must extend the old one
(the leading run at its left, the trailing run at its right), and a run of the new text may not begin
or end at an edge with a blank of the dialect. A kept run must also be the characters the script holds
next to the core, each claimed once, in script order; a record's span must show the same runs as its text.
Three declared exceptions, each for one dialect only: Oracle refuses a script whose statement edge holds a
character the driver would strip and the dialect does not (the refusal must name a character the script
holds at the reported line and column); SQL Server now strips U+200B at a statement edge, where the old
recording kept it; Db2 executes a statement made only of kept characters, which the old recording dropped
(the script must hold it; the other statements are compared as usual).
Everything else is reported with the dialect, the script id, the view and the first differing offset.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC

VIEWS = ("execution", "analysis", "records")
RECORD_TEXT_FIELDS = ("text", "analysis_statements", "source_start", "source_end", "line")
RECORD_FIELDS = (
    "text",
    "line",
    "terminator",
    "kind",
    "multi",
    "repeat",
    "analysis_statements",
    "source_start",
    "source_end",
)
_WHITESPACE = frozenset(chr(i) for i in range(0x110000) if chr(i).isspace())
_REFUSAL = re.compile(
    r"U\+([0-9A-F]{4,6}) at line (\d+), column (\d+) is at the edge of a statement: .*", re.S
)
_SQLSERVER_NOW_STRIPPED = "\u200b"


@dataclass(frozen=True)
class EdgeDifference:
    """One difference outside the allowed class."""

    dialect: str
    script_id: str
    view: str
    statement: Optional[int]
    offset: Optional[int]
    detail: str


class _Mismatch(Exception):
    def __init__(self, offset: Optional[int], detail: str, statement: Optional[int] = None):
        super().__init__(detail)
        self.offset = offset
        self.detail = detail
        self.statement = statement


def _runs(text: str, edge: FrozenSet[str]) -> Tuple[str, str, str]:
    core = text.strip("".join(edge))
    lead = text[: len(text) - len(text.lstrip("".join(edge)))]
    if not core:
        return text, "", ""
    return lead, core, text[len(lead) + len(core) :]


def _check_text(old: str, new: str, blanks: str, lost: str = "") -> None:
    """Raise ``_Mismatch`` unless ``new`` differs from ``old`` only by kept edge characters.

    ``lost`` are characters the old text kept at its core's edge and the new text strips.
    """
    edge = frozenset(_WHITESPACE | set(blanks))
    if lost:
        old_lead, old_core, old_trail = _runs(old, edge)
        new_lead, new_core, new_trail = _runs(new, edge)
        if not (set(new_lead + new_trail + new_core[:1] + new_core[-1:]) & set(lost)):
            old = (
                old_lead.translate({ord(c): None for c in lost})
                + old_core.strip(lost)
                + old_trail.translate({ord(c): None for c in lost})
            )
    if old == new:
        return
    old_lead, old_core, old_trail = _runs(old, edge)
    new_lead, new_core, new_trail = _runs(new, edge)
    if old_core != new_core:
        shared = next(
            (i for i, (a, b) in enumerate(zip(old_core, new_core)) if a != b),
            min(len(old_core), len(new_core)),
        )
        raise _Mismatch(len(new_lead) + shared, "text differs inside the statement")
    if new_lead and new_lead[0] in blanks:
        raise _Mismatch(0, f"leading {new_lead[0]!r} is a blank of the dialect and is kept")
    if new_trail and new_trail[-1] in blanks:
        raise _Mismatch(
            len(new) - 1, f"trailing {new_trail[-1]!r} is a blank of the dialect and is kept"
        )
    if not new_lead.endswith(old_lead) or not new_trail.startswith(old_trail):
        raise _Mismatch(len(new), "an edge run of the old text is gone or was replaced")


class _Unlocated(Exception):
    def __init__(self, index: int):
        super().__init__(index)
        self.index = index


def _claims(script: str, texts: List[str], changed: List[bool], blanks: str) -> None:
    """Walk ``texts`` through ``script``; raise ``_Unlocated`` for a changed text it cannot find."""
    edge = frozenset(_WHITESPACE | set(blanks))
    cursor = 0
    for index, text in enumerate(texts):
        lead, core, trail = _runs(text, edge)
        if not core:
            continue
        at = script.find(core, cursor + len(lead))
        if at < 0:
            if script.find(core) >= 0:
                raise _Mismatch(
                    0, "the statement's characters were already kept by a previous one", index
                )
            if changed[index]:
                raise _Unlocated(index)
            continue
        if script[at - len(lead) : at] != lead:
            raise _Mismatch(0, "the kept leading run is not what the script holds there", index)
        after = at + len(core)
        if script[after : after + len(trail)] != trail:
            raise _Mismatch(
                len(text) - len(trail),
                "the kept trailing run is not what the script holds there",
                index,
            )
        cursor = after + len(trail)


def _readings(script: str) -> List[str]:
    """The script, then as a splitter may rewrite it: psql backslash-semicolon as `;`, CRLF as LF."""
    return [script, script.replace("\\;", ";"), script.replace("\r\n", "\n")]


def _check_claims(script: str, old: List[str], texts: List[str], blanks: str) -> None:
    """Each kept edge run is the script's own characters, next to its core, claimed once.

    A text that changed and is found in none of the script's readings is reported; an unchanged
    one is not looked for.
    """
    changed = [before != after for before, after in zip(old, texts)]
    readings = _readings(script)
    for reading in readings[:-1]:
        try:
            _claims(reading, texts, changed, blanks)
            return
        except _Unlocated:
            continue
    try:
        _claims(readings[-1], texts, changed, blanks)
    except _Unlocated as missing:
        raise _Mismatch(
            0, "the statement's core is not found in the script", missing.index
        ) from None


_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_TERMINATORS = ";@"


def _kept_only(text: str, blanks: str) -> bool:
    """Whether ``text`` holds, outside comments, only white space and some character kept at an edge."""
    code = _COMMENT.sub("", text)
    return bool(code) and code.isspace() and any(c not in blanks for c in code)


def _stands_alone(script: str, text: str, at: int, blanks: str) -> bool:
    """Whether ``text`` at ``at`` is a statement of its own: terminators (or the script's ends) around it."""
    gap = blanks + " \t\r\n"
    before = script[:at].rstrip(gap)
    after = script[at + len(text) :].lstrip(gap)
    return (not before or before[-1] in _TERMINATORS) and (not after or after[0] in _TERMINATORS)


def _in_place(new: List[Any], kept: List[Any], script: str, blanks: str, text_of: Any) -> bool:
    """Whether each statement of kept characters stands alone in the script where ``new`` has it."""
    position = 0
    for item in new:
        text = text_of(item)
        if any(item is other for other in kept):
            at = script.find(text, position)
            while at >= 0 and not _stands_alone(script, text, at, blanks):
                at = script.find(text, at + 1)
            if at < 0:
                return False
            position = at + len(text)
        else:
            core = text.strip()
            at = script.find(core, position) if core else -1
            if at < 0:
                if core and core in script:
                    return False  # the script holds it before a statement that precedes it
                continue
            position = at + len(core)
    return True


def _without_declared(
    new: List[Any], old_count: int, script: Optional[str], blanks: str, text_of: Any
) -> List[Any]:
    """``new`` without the statements of kept characters, when that explains the count."""
    if len(new) == old_count:
        return new
    kept = [item for item in new if _kept_only(text_of(item), blanks)]
    if script is None or len(new) - len(kept) != old_count:
        return new
    if not _in_place(new, kept, script, blanks, text_of):
        return new
    return [item for item in new if not any(item is other for other in kept)]


def _check_statements(
    old: Any,
    new: Any,
    blanks: str,
    script: Optional[str] = None,
    lost: str = "",
    count_change: bool = False,
) -> None:
    if not isinstance(old, list) or not isinstance(new, list):
        if old != new:
            raise _Mismatch(None, f"outcome differs: old {old!r}, new {new!r}")
        return
    if count_change:
        new = _without_declared(new, len(old), script, blanks, lambda text: text)
    if len(old) != len(new):
        raise _Mismatch(None, f"old has {len(old)} statements, new has {len(new)}")
    for index, (before, after) in enumerate(zip(old, new)):
        try:
            _check_text(before, after, blanks, lost)
        except _Mismatch as found:
            raise _Mismatch(found.offset, found.detail, index) from None
    if script is not None:
        _check_claims(script, list(old), list(new), blanks)


def _leading(text: str, blanks: str) -> str:
    return _runs(text, frozenset(_WHITESPACE | set(blanks)))[0]


def _span_runs(script: str, record: Dict[str, Any], blanks: str) -> Optional[Tuple[str, str]]:
    """The characters of a record's span before and after its text's core (terminator left out)."""
    span = script[record["source_start"] : record["source_end"]]
    terminator = record["terminator"]
    if terminator and span.rstrip("\r\n").endswith(
        terminator
    ):  # a separator line ends with its newline
        span = span.rstrip("\r\n")[: -len(terminator)]
    core = _runs(record["text"], frozenset(_WHITESPACE | set(blanks)))[1]
    for reading in _readings(span):
        at = reading.find(core) if core else -1
        if at >= 0:
            return reading[:at], reading[at + len(core) :]
    return None


def _check_span(script: str, new: Dict[str, Any], blanks: str) -> None:
    """The new span shows the runs the new text shows.

    A span that stops before the text's trailing run (a record ends at its last token) is not judged
    here: the slice check in ``_check_record`` rejects it unless the old span stopped there too.
    """
    after = _span_runs(script, new, blanks)
    if after is None:
        return
    edge = frozenset(_WHITESPACE | set(blanks))
    text_lead, _, text_trail = _runs(new["text"], edge)
    span_lead, span_trail = after
    # a span also holds the blanks of the dialect that the text lost around its kept run
    if span_lead.lstrip(blanks) != text_lead.lstrip(blanks):
        raise _Mismatch(None, "span: its leading characters differ from the text's kept run")
    if span_trail.rstrip(blanks) != text_trail.rstrip(blanks) and span_trail != "":
        raise _Mismatch(None, "span: its trailing characters differ from the text's kept run")


def _check_record(
    script: str, old: Dict[str, Any], new: Dict[str, Any], blanks: str, lost: str = ""
) -> None:
    for key in RECORD_FIELDS:
        for side, record in (("old", old), ("new", new)):
            if key not in record:
                raise _Mismatch(None, f"{key} is missing from the {side} record")
    for key in sorted(set(old) | set(new)):
        if key not in RECORD_TEXT_FIELDS and old.get(key) != new.get(key):
            raise _Mismatch(None, f"{key} differs: old {old.get(key)!r}, new {new.get(key)!r}")
    _check_text(old["text"], new["text"], blanks, lost)
    before, after = old["analysis_statements"], new["analysis_statements"]
    if before is None or after is None:
        if before != after:
            raise _Mismatch(None, f"analysis_statements differs: old {before!r}, new {after!r}")
    else:
        try:
            _check_statements(list(before), list(after), blanks, lost=lost)
        except _Mismatch as found:
            raise _Mismatch(
                found.offset, f"analysis_statements: {found.detail}", found.statement
            ) from None
    try:
        _check_text(
            script[old["source_start"] : old["source_end"]],
            script[new["source_start"] : new["source_end"]],
            blanks,
            lost,
        )
    except _Mismatch as found:
        raise _Mismatch(found.offset, f"span: {found.detail}") from None
    if old != new:
        _check_span(script, new, blanks)
    shift = _leading(new["text"], blanks).count("\n") - _leading(old["text"], blanks).count("\n")
    if old["line"] != new["line"] + shift:
        raise _Mismatch(
            None,
            f"line differs: old {old['line']}, new {new['line']}, kept leading text explains {shift}",
        )


def _check_records(
    script: str, old: Any, new: Any, blanks: str, lost: str = "", count_change: bool = False
) -> None:
    if not isinstance(old, list) or not isinstance(new, list):
        if old != new:
            raise _Mismatch(None, f"outcome differs: old {old!r}, new {new!r}")
        return
    if count_change:
        new = _without_declared(new, len(old), script, blanks, lambda record: record["text"])
    if len(old) != len(new):
        raise _Mismatch(None, f"old has {len(old)} records, new has {len(new)}")
    for index, (before, after) in enumerate(zip(old, new)):
        try:
            _check_record(script, before, after, blanks, lost)
        except _Mismatch as found:
            raise _Mismatch(found.offset, found.detail, index) from None
    try:
        _check_claims(script, [r["text"] for r in old], [r["text"] for r in new], blanks)
    except _Mismatch as found:
        raise _Mismatch(found.offset, found.detail, found.statement) from None


def _at_record_edge(script: str, records: Any, offset: int) -> bool:
    """The character at ``offset`` is the first or last of a record's span, or only blanks and
    terminators lie between it and that edge."""
    gap = _WHITESPACE | {";"}
    if not script[:offset].strip() or not script[offset + 1 :].strip():
        return True
    for record in records if isinstance(records, list) else []:
        start, end = record["source_start"], record["source_end"]
        if offset < start:
            near = script[offset:start]
        elif offset >= end:
            near = script[end : offset + 1]
        elif offset - start < end - 1 - offset:
            near = script[start:offset]
        else:
            near = script[offset + 1 : end]
        if set(near) <= gap:
            return True
    return False


def _is_declared_refusal(dialect: str, before: Dict[str, Any], view: str, new: Any) -> bool:
    """An Oracle refusal naming a character at a statement edge, outside Oracle's blanks."""
    script, old = before["script"], before[view]
    if dialect != "oracle" or not isinstance(new, dict) or "error" not in new:
        return False
    if isinstance(old, dict) and "error" in old:
        return False
    error = new["error"]
    if not isinstance(error, list) or len(error) != 2 or error[0] != "UnsafeStatementSplitError":
        return False
    match = _REFUSAL.fullmatch(str(error[1]))
    if match is None:
        return False
    char, line, column = chr(int(match.group(1), 16)), int(match.group(2)), int(match.group(3))
    lines = script.split("\n")
    if line > len(lines) or column > len(lines[line - 1]):
        return False
    if lines[line - 1][column - 1] != char or char in ORACLE_SPEC.text_blanks:
        return False
    offset = sum(len(text) + 1 for text in lines[: line - 1]) + column - 1
    return char in _WHITESPACE and _at_record_edge(script, before["records"], offset)


def compare_recordings(
    old: Mapping[str, Any], new: Mapping[str, Any], text_blanks: str
) -> List[EdgeDifference]:
    """Every difference between two recordings of one dialect outside the allowed class.

    ``text_blanks`` is the dialect's set of characters a statement edge loses.
    """
    dialect = str(new.get("dialect", old.get("dialect")))
    found: List[EdgeDifference] = []

    def add(script_id: str, view: str, mismatch: _Mismatch) -> None:
        found.append(
            EdgeDifference(
                dialect, script_id, view, mismatch.statement, mismatch.offset, mismatch.detail
            )
        )

    lost = _SQLSERVER_NOW_STRIPPED if dialect == "sqlserver" else ""
    count_change = dialect == "db2"
    old_scripts, new_scripts = old["scripts"], new["scripts"]
    for script_id in sorted(set(old_scripts) | set(new_scripts)):
        if script_id not in new_scripts or script_id not in old_scripts:
            side = "new" if script_id not in new_scripts else "old"
            add(script_id, "script", _Mismatch(None, f"missing from the {side} recording"))
            continue
        before, after = old_scripts[script_id], new_scripts[script_id]
        if before["script"] != after["script"]:
            add(script_id, "script", _Mismatch(None, "the script text differs between recordings"))
            continue
        for view in VIEWS:
            if _is_declared_refusal(dialect, before, view, after[view]):
                continue
            try:
                if view == "records":
                    _check_records(
                        before["script"], before[view], after[view], text_blanks, lost, count_change
                    )
                else:
                    _check_statements(
                        before[view], after[view], text_blanks, before["script"], lost, count_change
                    )
            except _Mismatch as mismatch:
                add(script_id, view, mismatch)
    return found

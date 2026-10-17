"""Compare two statement-edge recordings; only one kind of difference is allowed.

The allowed difference: a character of ``str.isspace()`` that is not one of the dialect's
``text_blanks`` sits at a statement's edge in the new recording where the old recording had trimmed it.
Both sides are cut into ``leading run + core + trailing run`` (a run is made of the characters that
class covers, the blanks included); the cores must be equal, the new runs may only be longer than the
old ones, and a run of the new text may not begin or end at an edge with a blank of the dialect.
Everything else is reported with the dialect, the script id, the view and the first differing offset.
"""

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

VIEWS = ("execution", "analysis", "records")
RECORD_TEXT_FIELDS = ("text", "analysis_statements", "source_start", "source_end", "line")
_WHITESPACE = frozenset(chr(i) for i in range(0x110000) if chr(i).isspace())


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


def _check_text(old: str, new: str, blanks: str) -> None:
    """Raise ``_Mismatch`` unless ``new`` differs from ``old`` only by kept edge characters."""
    if old == new:
        return
    edge = frozenset(_WHITESPACE | set(blanks))
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
    if len(new_lead) < len(old_lead) or len(new_trail) < len(old_trail):
        raise _Mismatch(len(new), "an edge character the old text held is gone")


def _check_statements(old: Any, new: Any, blanks: str) -> None:
    if not isinstance(old, list) or not isinstance(new, list):
        if old != new:
            raise _Mismatch(None, f"outcome differs: old {old!r}, new {new!r}")
        return
    if len(old) != len(new):
        raise _Mismatch(None, f"old has {len(old)} statements, new has {len(new)}")
    for index, (before, after) in enumerate(zip(old, new)):
        try:
            _check_text(before, after, blanks)
        except _Mismatch as found:
            raise _Mismatch(found.offset, found.detail, index) from None


def _leading(text: str, blanks: str) -> str:
    return _runs(text, frozenset(_WHITESPACE | set(blanks)))[0]


def _check_record(script: str, old: Dict[str, Any], new: Dict[str, Any], blanks: str) -> None:
    for key in sorted(set(old) | set(new)):
        if key not in RECORD_TEXT_FIELDS and old.get(key) != new.get(key):
            raise _Mismatch(None, f"{key} differs: old {old.get(key)!r}, new {new.get(key)!r}")
    _check_text(old["text"], new["text"], blanks)
    before, after = old["analysis_statements"], new["analysis_statements"]
    if before is None or after is None:
        if before != after:
            raise _Mismatch(None, f"analysis_statements differs: old {before!r}, new {after!r}")
    else:
        try:
            _check_statements(list(before), list(after), blanks)
        except _Mismatch as found:
            raise _Mismatch(
                found.offset, f"analysis_statements: {found.detail}", found.statement
            ) from None
    try:
        _check_text(
            script[old["source_start"] : old["source_end"]],
            script[new["source_start"] : new["source_end"]],
            blanks,
        )
    except _Mismatch as found:
        raise _Mismatch(found.offset, f"span: {found.detail}") from None
    shift = _leading(new["text"], blanks).count("\n") - _leading(old["text"], blanks).count("\n")
    if old["line"] != new["line"] + shift:
        raise _Mismatch(
            None,
            f"line differs: old {old['line']}, new {new['line']}, kept leading text explains {shift}",
        )


def _check_records(script: str, old: Any, new: Any, blanks: str) -> None:
    if not isinstance(old, list) or not isinstance(new, list):
        if old != new:
            raise _Mismatch(None, f"outcome differs: old {old!r}, new {new!r}")
        return
    if len(old) != len(new):
        raise _Mismatch(None, f"old has {len(old)} records, new has {len(new)}")
    for index, (before, after) in enumerate(zip(old, new)):
        try:
            _check_record(script, before, after, blanks)
        except _Mismatch as found:
            raise _Mismatch(found.offset, found.detail, index) from None


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
            try:
                if view == "records":
                    _check_records(before["script"], before[view], after[view], text_blanks)
                else:
                    _check_statements(before[view], after[view], text_blanks)
            except _Mismatch as mismatch:
                add(script_id, view, mismatch)
    return found

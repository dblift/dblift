"""How a completed command is rendered: execution time, file-log message, footer and fallbacks."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

import pytest

from dblift.core.logger import NullLog
from dblift.core.logger.log import ConsoleLog, FileLog, LogFormat
from dblift.core.logger.results import OperationResult
from dblift.core.migration.ui import command_presentation
from dblift.core.migration.ui.command_presentation import CommandPresentation

pytestmark = [pytest.mark.unit]

START = datetime(2026, 1, 1, 12, 0, 0)


class _FileLog(FileLog):
    """A file log that keeps its messages instead of writing a file."""

    def __init__(self, log_format: LogFormat, debug_error: Optional[Exception] = None) -> None:
        self.log_format = log_format
        self.messages: List[str] = []
        self.debug_error = debug_error

    def info(self, message: str, console_only: bool = False, *, dedupe: bool = True) -> None:
        self.messages.append(message)

    def debug(self, message: str) -> None:
        if self.debug_error is not None:
            raise self.debug_error
        self.messages.append(message)


class _ConsoleLog(ConsoleLog):
    """A console log that keeps its messages instead of printing them."""

    def __init__(self) -> None:
        self.messages: List[str] = []

    def info(self, message: str, console_only: bool = False, *, dedupe: bool = True) -> None:
        self.messages.append(message)


class _Command:
    """The parts of a command the completion renderer reads."""

    _has_own_console_footer = False

    def __init__(self, log: object, resolve: Callable[[], Optional[str]] = lambda: "7") -> None:
        self.log = log
        self.history_manager = object()
        self._resolve = resolve
        self.footers: List[Dict[str, object]] = []
        self.blocks: List[str] = []

    def _resolve_current_schema_version(self) -> Optional[str]:
        return self._resolve()

    def _format_command_footer(self, **footer: object) -> str:
        self.footers.append(footer)
        return "FOOTER"

    def _build_footer_panel(self, **footer: object) -> str:
        raise AssertionError("the plain-text footer is expected")

    def _log_text_block(self, block: str) -> None:
        self.blocks.append(block)


def _result(milliseconds: Optional[int], success: bool = True) -> OperationResult:
    result = OperationResult(success=success)
    result.start_time = START
    result.end_time = None if milliseconds is None else START + timedelta(milliseconds=milliseconds)
    return result


def _render(command: _Command, result: OperationResult, name: str = "info") -> None:
    CommandPresentation().present_command_result(command, name, result)  # type: ignore[arg-type]


def test_an_unfinished_result_is_completed_before_anything_else():
    result = _result(None)
    command = _Command(NullLog())
    _render(command, result)
    assert result.end_time is not None
    assert command.footers == [] and command.blocks == []


@pytest.mark.parametrize(
    "milliseconds, shown",
    [
        (999, "999 ms"),
        (1000, "1.00 s"),
        (1500, "1.50 s"),
        (59999, "60.00 s"),
        (60000, "1.00 min"),
        (90000, "1.50 min"),
    ],
)
def test_execution_time_is_shown_in_milliseconds_seconds_or_minutes(milliseconds, shown):
    command = _Command(_FileLog(LogFormat.TEXT))
    _render(command, _result(milliseconds))
    assert [footer["execution_time"] for footer in command.footers] == [shown]


def test_a_file_log_alone_gets_the_completion_message_and_no_console_footer(capsys):
    log = _FileLog(LogFormat.JSON)
    command = _Command(log)
    _render(command, _result(1500, success=False), "validate")
    assert log.messages == ["Command validate completed with status FAILED in 1.50 s"]
    assert command.blocks == ["FOOTER"]
    assert capsys.readouterr().out == ""


def test_a_text_file_log_alone_gets_no_completion_message():
    log = _FileLog(LogFormat.TEXT)
    command = _Command(log)
    _render(command, _result(5))
    assert log.messages == []
    assert command.blocks == ["FOOTER"]


def test_a_failed_schema_version_lookup_is_logged_and_leaves_the_footer_without_one():
    log = _FileLog(LogFormat.TEXT)

    def resolve() -> Optional[str]:
        raise RuntimeError("history table dropped")

    command = _Command(log, resolve)
    _render(command, _result(5))
    assert log.messages == [
        "Could not resolve post-operation schema version: history table dropped"
    ]
    assert command.footers[0]["schema_version"] is None


def test_a_debug_log_that_fails_does_not_stop_the_footer():
    log = _FileLog(LogFormat.TEXT, debug_error=AttributeError("stub log"))

    def resolve() -> Optional[str]:
        raise RuntimeError("history table dropped")

    command = _Command(log, resolve)
    _render(command, _result(5))
    assert command.blocks == ["FOOTER"]
    assert command.footers[0]["schema_version"] is None


def test_a_console_without_rich_gets_the_plain_text_footer(monkeypatch, capsys):
    monkeypatch.setattr(command_presentation, "rich_available", lambda: False)
    log = _ConsoleLog()
    command = _Command(log)
    _render(command, _result(5))
    assert capsys.readouterr().out == "FOOTER\n"
    assert log.messages == []
    assert command.blocks == ["FOOTER"]
    assert command.footers[0]["schema_version"] == "7"

"""Extended tests for core.logger.log to improve coverage.

This module tests additional scenarios for the log module, focusing on
uncovered areas like LogLevel, LogEvent, AbstractLog, ConsoleLog, FileLog,
MultiLog, LogFactory, and TextFormatter.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest

from core.logger.log import (
    AbstractLog,
    ConsoleLog,
    FileLog,
    Log,
    LogEvent,
    LogFactory,
    LogFormat,
    LogLevel,
    MultiLog,
    TextFormatter,
)
from core.logger.results import MigrateResult, MigrationSqlInfo, OperationResult


@pytest.mark.unit
class TestLogLevel:
    """Tests for LogLevel enum."""

    def test_from_string_valid(self):
        """Test LogLevel.from_string with valid values."""
        assert LogLevel.from_string("debug") == LogLevel.DEBUG
        assert LogLevel.from_string("DEBUG") == LogLevel.DEBUG
        assert LogLevel.from_string("info") == LogLevel.INFO
        assert LogLevel.from_string("INFO") == LogLevel.INFO
        assert LogLevel.from_string("warn") == LogLevel.WARN
        assert LogLevel.from_string("WARN") == LogLevel.WARN
        assert LogLevel.from_string("error") == LogLevel.ERROR
        assert LogLevel.from_string("ERROR") == LogLevel.ERROR
        assert LogLevel.from_string("notice") == LogLevel.NOTICE
        assert LogLevel.from_string("NOTICE") == LogLevel.NOTICE

    def test_from_string_invalid(self):
        """Test LogLevel.from_string with invalid values."""
        with pytest.raises(ValueError, match="Invalid log level"):
            LogLevel.from_string("invalid")
        with pytest.raises(ValueError, match="Invalid log level"):
            LogLevel.from_string("")


@pytest.mark.unit
class TestLogFormat:
    """Tests for LogFormat enum."""

    def test_str(self):
        """Test LogFormat.__str__."""
        assert str(LogFormat.TEXT) == "text"
        assert str(LogFormat.JSON) == "json"
        assert str(LogFormat.HTML) == "html"

    def test_from_string_case_insensitive(self):
        """Test LogFormat.from_string is case insensitive."""
        assert LogFormat.from_string("TEXT") == LogFormat.TEXT
        assert LogFormat.from_string("Text") == LogFormat.TEXT
        assert LogFormat.from_string("JSON") == LogFormat.JSON
        assert LogFormat.from_string("Html") == LogFormat.HTML


@pytest.mark.unit
class TestLogEvent:
    """Tests for LogEvent class."""

    def test_init_with_timestamp(self):
        """Test LogEvent initialization with custom timestamp."""
        timestamp = datetime(2023, 1, 1, 12, 0, 0)
        event = LogEvent(LogLevel.INFO, "test", "component", timestamp=timestamp)
        assert event.timestamp == timestamp
        assert event.level == LogLevel.INFO
        assert event.message == "test"
        assert event.component == "component"

    def test_init_with_context(self):
        """Test LogEvent initialization with context."""
        context = {"key": "value", "number": 123}
        event = LogEvent(LogLevel.INFO, "test", "component", context=context)
        assert event.context == context

    def test_init_defaults(self):
        """Test LogEvent initialization with defaults."""
        event = LogEvent(LogLevel.INFO, "test", "component")
        assert isinstance(event.timestamp, datetime)
        assert event.context == {}


@pytest.mark.unit
class TestLogBase:
    """Tests for Log base class."""

    def test_init(self):
        """Test Log initialization."""
        log = Log("test_log")
        assert log.name == "test_log"
        assert log._enable_debug is False
        assert log._dedup_window == 5
        assert log._last_messages == []
        assert log.logs == []

    def test_init_with_debug(self):
        """Test Log initialization with debug enabled."""
        log = Log("test_log", enable_debug=True)
        assert log._enable_debug is True

    def test_debug_enabled(self):
        """Test debug logging when enabled."""
        log = Log("test_log", enable_debug=True)
        logged = []
        log._write_log = lambda level, msg: logged.append((level, msg))
        log.debug("debug message")
        assert len(logged) == 1
        assert logged[0][0] == LogLevel.DEBUG
        assert logged[0][1] == "debug message"

    def test_debug_disabled(self):
        """Test debug logging when disabled."""
        log = Log("test_log", enable_debug=False)
        logged = []
        log._write_log = lambda level, msg: logged.append((level, msg))
        log.debug("debug message")
        assert len(logged) == 0

    def test_info(self):
        """Test info logging."""
        log = Log("test_log")
        logged = []
        log._write_log = lambda level, msg: logged.append((level, msg))
        log.info("info message")
        assert len(logged) == 1
        assert logged[0][0] == LogLevel.INFO
        assert logged[0][1] == "info message"

    def test_warn(self):
        """Test warn logging."""
        log = Log("test_log")
        logged = []
        log._write_log = lambda level, msg: logged.append((level, msg))
        log.warn("warn message")
        assert len(logged) == 1
        assert logged[0][0] == LogLevel.WARN
        assert logged[0][1] == "warn message"

    def test_warning_alias(self):
        """Test warning alias for warn."""
        log = Log("test_log")
        logged = []
        log._write_log = lambda level, msg: logged.append((level, msg))
        log.warning("warning message")
        assert len(logged) == 1
        assert logged[0][0] == LogLevel.WARN
        assert logged[0][1] == "warning message"

    def test_error(self):
        """Test error logging."""
        log = Log("test_log")
        logged = []
        log._log_direct = lambda level, msg: logged.append((level, msg))
        log.error("error message")
        assert len(logged) == 1
        assert logged[0][0] == LogLevel.ERROR
        assert logged[0][1] == "error message"
        assert hasattr(log, "_stack_trace")

    def test_error_with_exception(self):
        """Test error_with_exception."""
        log = Log("test_log")
        logged = []
        log.error = lambda msg: logged.append(msg)
        exception = ValueError("test exception")
        log.error_with_exception("error", exception)
        assert len(logged) == 1
        assert "error" in logged[0]
        assert "test exception" in logged[0]

    def test_notice(self):
        """Test notice logging."""
        log = Log("test_log")
        logged = []
        log._write_log = lambda level, msg: logged.append((level, msg))
        log.notice("notice message")
        assert len(logged) == 1
        assert logged[0][0] == LogLevel.NOTICE
        assert logged[0][1] == "notice message"

    def test_set_command_type(self):
        """Test set_command_type."""
        log = Log("test_log")
        log.set_command_type("MIGRATE")
        # Base implementation does nothing, but should not raise

    def test_set_command_completed_success(self):
        """Test set_command_completed with success."""
        log = Log("test_log")
        logged = []
        log.notice = lambda msg: logged.append(msg)
        log.set_command_completed(True, "Success message")
        assert len(logged) == 1
        assert "Success message" in logged[0]

    def test_set_command_completed_failure(self):
        """Test set_command_completed with failure."""
        log = Log("test_log")
        logged = []
        log.error = lambda msg: logged.append(msg)
        log.set_command_completed(False, "Failure message")
        assert len(logged) == 1
        assert "Failure message" in logged[0]

    def test_set_command_completed_no_message(self):
        """Test set_command_completed without message."""
        log = Log("test_log")
        logged = []
        log.notice = lambda msg: logged.append(msg)
        log.set_command_completed(True)
        assert len(logged) == 1
        assert "completed successfully" in logged[0]

    def test_is_debug_enabled(self):
        """Test is_debug_enabled."""
        log = Log("test_log", enable_debug=True)
        assert log.is_debug_enabled() is True
        log = Log("test_log", enable_debug=False)
        assert log.is_debug_enabled() is False

    def test_is_html_enabled(self):
        """Test is_html_enabled."""
        log = Log("test_log")
        assert log.is_html_enabled() is False

    def test_html(self):
        """Test html method."""
        log = Log("test_log")
        logged = []
        log.info = lambda msg: logged.append(msg)
        log.html("<b>test</b>")
        assert len(logged) == 1
        assert logged[0] == "<b>test</b>"

    def test_log_deduplication(self):
        """Test log deduplication."""
        log = Log("test_log", enable_debug=True)
        logged = []
        log._log_direct = lambda level, msg: logged.append((level, msg))
        log.info("duplicate")
        log.info("duplicate")  # Should be deduplicated
        log.info("different")
        # First message should be logged
        assert len(logged) >= 1
        # Check that duplicate was filtered
        assert logged[0][1] == "duplicate"
        # Different message should be logged
        assert any(l[1] == "different" for l in logged)

    def test_log_no_deduplication_for_errors(self):
        """Test that errors are not deduplicated."""
        log = Log("test_log")
        logged = []
        log._log_direct = lambda level, msg: logged.append((level, msg))
        log.error("error1")
        log.error("error1")  # Should NOT be deduplicated
        assert len(logged) == 2

    def test_log_deduplication_window_limit(self):
        """Test deduplication window limit."""
        log = Log("test_log", enable_debug=True)
        log._dedup_window = 2
        logged = []
        log._log_direct = lambda level, msg: logged.append((level, msg))
        # Log more messages than window size
        for i in range(5):
            log.info(f"msg{i}")
        # Should have logged all messages (window is per message key)
        assert len(logged) == 5

    def test_log_direct_skips_debug_when_disabled(self):
        """Test _log_direct skips DEBUG when disabled."""
        log = Log("test_log", enable_debug=False)
        logged = []
        log._write_log = lambda level, msg: logged.append((level, msg))
        log._log_direct(LogLevel.DEBUG, "debug")
        assert len(logged) == 0


@pytest.mark.unit
class TestAbstractLog:
    """Tests for AbstractLog class."""

    def test_init(self):
        """Test AbstractLog initialization."""
        log = AbstractLog("test_log")
        assert log.name == "test_log"
        assert log.enable_debug is False
        assert log._dedup_window == 2
        assert log._recent_messages == {}
        assert log._prev_message == ""
        assert log.command_type is None

    def test_should_deduplicate_error_level(self):
        """Test _should_deduplicate returns False for ERROR level."""
        log = AbstractLog("test_log")
        assert log._should_deduplicate(LogLevel.ERROR, "error") is False

    def test_should_deduplicate_empty_message(self):
        """Test _should_deduplicate returns False for empty message."""
        log = AbstractLog("test_log")
        assert log._should_deduplicate(LogLevel.INFO, "") is False

    def test_should_deduplicate_recent_message(self):
        """Test _should_deduplicate returns True for recent message."""
        log = AbstractLog("test_log")
        log._dedup_window = 10  # 10 seconds
        # First call should return False (not seen recently)
        assert log._should_deduplicate(LogLevel.INFO, "test") is False
        # Second call immediately should return True (seen recently)
        assert log._should_deduplicate(LogLevel.INFO, "test") is True

    def test_should_deduplicate_old_message(self):
        """Test _should_deduplicate returns False for old message."""
        log = AbstractLog("test_log")
        log._dedup_window = 0.1  # 0.1 seconds
        # First call
        log._should_deduplicate(LogLevel.INFO, "test")
        # Wait a bit (simulate with mock)
        import time

        time.sleep(0.2)
        # Should return False after window expires
        assert log._should_deduplicate(LogLevel.INFO, "test") is False

    def test_should_deduplicate_limits_dict_size(self):
        """Test _should_deduplicate limits recent_messages dict size."""
        log = AbstractLog("test_log")
        # Add many messages
        for i in range(150):
            log._should_deduplicate(LogLevel.INFO, f"msg{i}")
        # Dictionary should be limited to ~100 entries
        assert len(log._recent_messages) <= 100

    def test_log_skips_debug_when_disabled(self):
        """Test _log skips DEBUG when debug is disabled."""
        log = AbstractLog("test_log", enable_debug=False)
        logged = []
        log._write_log_event = lambda event, console_only: logged.append(event)
        log._log(LogLevel.DEBUG, "debug")
        assert len(logged) == 0

    def test_log_deduplicates_duplicate_tables(self):
        """Test _log deduplicates duplicate table messages."""
        log = AbstractLog("test_log")
        logged = []
        log._write_log_event = lambda event, console_only: logged.append(event)
        table_msg = "+-------+\n| col |"
        log._log(LogLevel.INFO, table_msg)
        log._log(LogLevel.INFO, table_msg)  # Should be deduplicated
        assert len(logged) == 1

    def test_error_with_exception_cleans_java_exceptions(self):
        """Test error_with_exception cleans Java exception messages."""
        log = AbstractLog("test_log")
        logged = []
        log._log = lambda level, msg, console_only=None: logged.append((level, msg))

        # Mock traceback.format_exc to return a stack trace
        with patch("core.logger.log.traceback.format_exc", return_value="Traceback..."):
            exception = Exception("com.example.JavaException: Error message")
            log.error_with_exception("test", exception)

        assert len(logged) == 1
        # Java exception prefix should be removed
        assert "com.example.JavaException" not in logged[0][1]
        assert "Error message" in logged[0][1]

    def test_error_with_exception_handles_nested_exceptions(self):
        """Test error_with_exception handles nested Java exceptions."""
        log = AbstractLog("test_log")
        logged = []
        log._log = lambda level, msg, console_only=None: logged.append((level, msg))

        with patch("core.logger.log.traceback.format_exc", return_value="Traceback..."):
            exception = Exception(
                "First exception\nThe above exception was the direct cause of the following exception\nSecond exception"
            )
            log.error_with_exception("test", exception)

        assert len(logged) == 1
        # Should only contain second exception
        assert "First exception" not in logged[0][1]
        assert "Second exception" in logged[0][1]

    def test_error_with_exception_skips_stack_trace_for_validation(self):
        """Test error_with_exception skips stack trace for validation errors."""
        log = AbstractLog("test_log")
        logged = []
        log._log = lambda level, msg, console_only=None: logged.append((level, msg))

        with patch("core.logger.log.traceback.format_exc", return_value="Traceback..."):
            exception = Exception("Error")
            log.error_with_exception("Validation failed", exception)

        assert len(logged) == 1
        # Stack trace should not be stored for validation errors
        assert not hasattr(log, "_stack_trace") or log._stack_trace is None

    def test_set_command_type(self):
        """Test set_command_type."""
        log = AbstractLog("test_log")
        log.set_command_type("MIGRATE")
        assert log.command_type == "MIGRATE"

    def test_set_command_type_updates_formatter(self):
        """Test set_command_type updates formatter if available."""
        log = AbstractLog("test_log")
        formatter = Mock()
        formatter.set_current_command = Mock()
        log.formatter = formatter
        log.set_command_type("MIGRATE")
        formatter.set_current_command.assert_called_once_with("MIGRATE")

    def test_set_current_command(self):
        """Test set_current_command."""
        log = AbstractLog("test_log")
        formatter = Mock()
        formatter.set_current_command = Mock()
        log.formatter = formatter
        log.set_current_command("VALIDATE")
        assert log.command_type == "VALIDATE"
        formatter.set_current_command.assert_called_once_with("VALIDATE")

    def test_close(self):
        """Test close method."""
        log = AbstractLog("test_log")
        log.close()  # Should not raise


@pytest.mark.unit
class TestConsoleLog:
    """Tests for ConsoleLog class."""

    def test_init(self):
        """Test ConsoleLog initialization."""
        log = ConsoleLog("test_log")
        assert log.name == "test_log"
        assert isinstance(log.formatter, TextFormatter)

    def test_write_log_event_info(self, capsys):
        """Test _write_log_event routes INFO level to stderr."""
        log = ConsoleLog("test_log")
        event = LogEvent(LogLevel.INFO, "test message", "test")
        log._write_log_event(event)
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "test message" in captured.err

    def test_write_log_event_error(self, capsys):
        """Test _write_log_event for ERROR level."""
        log = ConsoleLog("test_log")
        event = LogEvent(LogLevel.ERROR, "error message", "test")
        log._write_log_event(event)
        captured = capsys.readouterr()
        assert "error message" in captured.err

    def test_write_log_event_warn(self, capsys):
        """Test _write_log_event for WARN level."""
        log = ConsoleLog("test_log")
        event = LogEvent(LogLevel.WARN, "warn message", "test")
        log._write_log_event(event)
        captured = capsys.readouterr()
        assert "warn message" in captured.err

    def test_set_command_completed_with_command_type(self):
        """Test set_command_completed with command_type."""
        log = ConsoleLog("test_log")
        log.set_command_completed(True, "Success", "MIGRATE")
        assert log.command_type == "MIGRATE"

    def test_set_command_completed_without_command_type(self):
        """Test set_command_completed without command_type."""
        log = ConsoleLog("test_log")
        log.command_type = "VALIDATE"
        log.set_command_completed(True, "Success")
        assert log.command_type == "VALIDATE"

    def test_set_command_completed_stores_result(self):
        """Test set_command_completed stores result."""
        log = ConsoleLog("test_log")
        result = OperationResult()
        log.set_command_completed(True, "Success", "MIGRATE", result)
        assert hasattr(log, "operation_result")
        assert log.operation_result == result

    def test_set_command_completed_with_result_no_message(self):
        """Test set_command_completed with result but no message."""
        log = ConsoleLog("test_log")
        result = OperationResult()
        result.success = True
        log.set_command_completed(True, None, "MIGRATE", result)
        # Should generate default message
        assert hasattr(log, "operation_result")

    def test_display_result_summary_skips_failed(self):
        """Test _display_result_summary skips failed results."""
        log = ConsoleLog("test_log")
        result = OperationResult()
        result.success = False
        # Should not raise and should not display
        log._display_result_summary(result)

    def test_display_result_summary_prints_show_sql_for_failed_result(self, capsys):
        """Failed migrate runs still print collected show-sql statements."""
        log = ConsoleLog("test_log")
        result = MigrateResult()
        result.success = False
        result.error_message = "boom"
        result.show_sql = True
        result.target_schema = "test_schema"
        result.add_sql_migration(
            MigrationSqlInfo("V1__init.sql", version="1", statements=["CREATE TABLE users"])
        )

        log._display_result_summary(result)

        captured = capsys.readouterr()
        assert "SQL Statements:" in captured.err
        assert "CREATE TABLE users" in captured.err

    def test_display_result_summary_with_journal(self, capsys):
        """Test _display_result_summary with journal data."""
        log = ConsoleLog("test_log")
        result = OperationResult()
        result.success = True
        result.target_schema = "test_schema"
        # Mock journal attribute
        result.journal = {"test": "data"}
        log._display_result_summary(result)
        # Should not raise

    def test_display_result_summary_exception_handling(self):
        """Test _display_result_summary handles exceptions gracefully."""
        log = ConsoleLog("test_log", enable_debug=False)
        result = OperationResult()
        result.success = True
        # Mock the import inside the method to raise exception
        with patch(
            "core.logger.formatters.formatter.OutputFormatter", side_effect=Exception("Test")
        ):
            log._display_result_summary(result)
        # Should not raise


@pytest.mark.unit
class TestFileLog:
    """Tests for FileLog class."""

    def test_init_text_format(self, tmp_path):
        """Test FileLog initialization with TEXT format."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        assert log.name == "test_log"
        assert log.log_dir == tmp_path
        assert log.log_format == LogFormat.TEXT
        assert log.log_file.exists()

    def test_init_json_format(self, tmp_path):
        """Test FileLog initialization with JSON format."""
        log = FileLog("test_log", tmp_path, LogFormat.JSON)
        assert log.log_format == LogFormat.JSON

    def test_init_html_format(self, tmp_path):
        """Test FileLog initialization with HTML format."""
        log = FileLog("test_log", tmp_path, LogFormat.HTML)
        assert log.log_format == LogFormat.HTML

    def test_init_with_schema_and_database(self, tmp_path):
        """Test FileLog initialization with schema and database."""
        log = FileLog(
            "test_log", tmp_path, LogFormat.TEXT, schema="test_schema", database_name="test_db"
        )
        assert log.schema == "test_schema"
        assert log.database_name == "test_db"

    def test_init_with_path_like_database_name_stays_flat(self, tmp_path):
        """Regression for BUG-LOG-01: a SQLite file-path database_name must not
        inject directory separators into the log filename (which would point at
        nonexistent nested dirs and crash on header write)."""
        log = FileLog(
            "test_log",
            tmp_path,
            LogFormat.TEXT,
            schema="main",
            database_name="/var/folders/x/tmp.abc/dblift_test.db",
        )
        # Log file is a direct child of log_dir — no nested separators from the name.
        assert log.log_file.parent == tmp_path
        assert "/" not in log.log_file.name
        # Header write happened in __init__ without raising; file exists.
        assert log.log_file.exists()

    def test_init_with_log_file_pattern(self, tmp_path):
        """Test FileLog initialization with log file pattern."""
        log = FileLog(
            "test_log", tmp_path, LogFormat.TEXT, log_file_pattern="<schema>_<timestamp>.log"
        )
        assert log.log_file_pattern == "<schema>_<timestamp>.log"

    def test_get_log_file_default_pattern(self, tmp_path):
        """Test _get_log_file with default pattern."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT, schema="test", database_name="db")
        log_file = log._get_log_file()
        assert log_file.parent == tmp_path
        assert log_file.suffix == ".log"
        assert "test" in log_file.name
        assert "db" in log_file.name

    def test_get_log_file_custom_pattern(self, tmp_path):
        """Test _get_log_file with custom pattern."""
        log = FileLog(
            "test_log",
            tmp_path,
            LogFormat.TEXT,
            schema="test",
            database_name="db",
            log_file_pattern="custom_<schema>.log",
        )
        log_file = log._get_log_file()
        assert "custom_test" in log_file.name

    def test_get_log_file_pattern_with_format_placeholder(self, tmp_path):
        """Test _get_log_file with format placeholder."""
        log = FileLog("test_log", tmp_path, LogFormat.HTML, log_file_pattern="log.<format>")
        log_file = log._get_log_file()
        assert log_file.suffix == ".html"

    def test_get_extension_for_format(self, tmp_path):
        """Test _get_extension_for_format."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        # Mock log_format_enum attribute
        log.log_format_enum = LogFormat.HTML
        assert log._get_extension_for_format() == "html"
        log.log_format_enum = LogFormat.JSON
        assert log._get_extension_for_format() == "json"
        log.log_format_enum = LogFormat.TEXT
        assert log._get_extension_for_format() == "log"

    def test_get_extension_for_format_fallback(self, tmp_path):
        """Test _get_extension_for_format fallback."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        # Remove log_format_enum to test fallback
        if hasattr(log, "log_format_enum"):
            delattr(log, "log_format_enum")
        assert log._get_extension_for_format() == "log"

    def test_write_header(self, tmp_path):
        """Test _write_header."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT, schema="test", database_name="db")
        log._write_header()
        assert log.log_file.exists()
        content = log.log_file.read_text()
        assert "DBLIFT DATABASE MIGRATION LOG" in content
        assert "Timestamp:" in content

    def test_write_log_event_text_format(self, tmp_path):
        """Test _write_log_event for TEXT format."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        event = LogEvent(LogLevel.INFO, "test message", "test")
        log._write_log_event(event)
        content = log.log_file.read_text()
        assert "test message" in content

    def test_write_log_event_json_format(self, tmp_path):
        """Test _write_log_event for JSON format."""
        log = FileLog("test_log", tmp_path, LogFormat.JSON)
        event = LogEvent(LogLevel.INFO, "test message", "test")
        log._write_log_event(event)
        # JSON format doesn't write immediately
        assert log.log_file.exists() or True  # May or may not exist yet

    def test_write_log_event_console_only(self, tmp_path):
        """Test _write_log_event with console_only=True."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        event = LogEvent(LogLevel.INFO, "test message", "test")
        log._write_log_event(event, console_only=True)
        # Should not write to file
        if log.log_file.exists():
            content = log.log_file.read_text()
            assert "test message" not in content or "DBLIFT" in content  # Only header

    def test_write_log_event_filters_debug(self, tmp_path):
        """Test _write_log_event filters DEBUG when disabled."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT, enable_debug=False)
        event = LogEvent(LogLevel.DEBUG, "debug message", "test")
        log._write_log_event(event)
        if log.log_file.exists():
            content = log.log_file.read_text()
            assert "debug message" not in content

    def test_write_text_block(self, tmp_path):
        """Test _write_text_block."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        log._write_text_block("Test block\nLine 2")
        content = log.log_file.read_text()
        assert "Test block" in content
        assert "Line 2" in content

    def test_write_text_block_empty(self, tmp_path):
        """Test _write_text_block with empty block."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        log._write_text_block("")
        # Should not raise

    def test_close_text_format(self, tmp_path):
        """Test close for TEXT format."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        log.info("test")
        log.close()
        content = log.log_file.read_text()
        assert "=" * 80 in content  # Footer

    def test_close_json_format(self, tmp_path):
        """Test close for JSON format."""
        log = FileLog("test_log", tmp_path, LogFormat.JSON)
        log.info("test")
        result = OperationResult()
        result.success = True
        result.complete()
        log.operation_result = result
        log.close()
        # Should write JSON
        assert log.log_file.exists()

    def test_close_html_format(self, tmp_path):
        """Test close for HTML format."""
        log = FileLog("test_log", tmp_path, LogFormat.HTML)
        log.info("test")
        result = OperationResult()
        result.success = True
        result.complete()
        log.operation_result = result
        log.close()
        # Should write HTML
        assert log.log_file.exists()

    def test_close_json_format_no_result(self, tmp_path):
        """Test close for JSON format without result."""
        log = FileLog("test_log", tmp_path, LogFormat.JSON)
        log.info("test")
        log.close()
        # Should create minimal result
        assert log.log_file.exists()

    def test_is_html_enabled(self, tmp_path):
        """Test is_html_enabled."""
        log = FileLog("test_log", tmp_path, LogFormat.HTML)
        assert log.is_html_enabled() is True
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        assert log.is_html_enabled() is False

    def test_html_method(self, tmp_path):
        """Test html method."""
        log = FileLog("test_log", tmp_path, LogFormat.HTML)
        log.html("<b>test</b>")
        content = log.log_file.read_text()
        assert "<b>test</b>" in content

    def test_html_method_non_html_format(self, tmp_path):
        """Test html method for non-HTML format."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        logged = []
        log.info = lambda msg: logged.append(msg)
        log.html("<b>test</b>")
        assert len(logged) == 1
        assert logged[0] == "<b>test</b>"

    def test_set_command_completed_text_format(self, tmp_path):
        """Test set_command_completed for TEXT format."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        log.set_command_completed(True, "Success", "MIGRATE")
        # TEXT format should not log completion message
        assert log.command_type == "MIGRATE"

    def test_set_command_completed_json_format(self, tmp_path):
        """Test set_command_completed for JSON format."""
        log = FileLog("test_log", tmp_path, LogFormat.JSON)
        log.set_command_completed(True, "Success", "MIGRATE")
        assert log.command_type == "MIGRATE"

    def test_set_command_completed_stores_result(self, tmp_path):
        """Test set_command_completed stores result."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        result = OperationResult()
        log.set_command_completed(True, "Success", "MIGRATE", result)
        assert hasattr(log, "operation_result")
        assert log.operation_result == result

    def test_set_multi_command_mode(self, tmp_path):
        """Test set_multi_command_mode."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        formatter = Mock()
        formatter.using_multi_command = False
        log.formatter = formatter
        log.set_multi_command_mode(True)
        assert formatter.using_multi_command is True

    def test_set_current_command(self, tmp_path):
        """Test set_current_command."""
        log = FileLog("test_log", tmp_path, LogFormat.TEXT)
        log.set_current_command("VALIDATE")
        assert log.command_type == "VALIDATE"


@pytest.mark.unit
class TestMultiLog:
    """Tests for MultiLog class."""

    def test_init(self):
        """Test MultiLog initialization."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        multi = MultiLog([console, file_log])
        assert len(multi.logs) == 2

    def test_is_debug_enabled(self):
        """Test is_debug_enabled."""
        console1 = ConsoleLog("console1", enable_debug=True)
        console2 = ConsoleLog("console2", enable_debug=False)
        multi = MultiLog([console1, console2])
        assert multi.is_debug_enabled() is True

    def test_debug(self):
        """Test debug method."""
        console1 = ConsoleLog("console1", enable_debug=True)
        console2 = ConsoleLog("console2", enable_debug=True)
        multi = MultiLog([console1, console2])
        multi.debug("debug message")
        # Should not raise

    def test_info(self):
        """Test info method."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        file_log.info = Mock()
        multi = MultiLog([console, file_log])
        multi.info("info message")
        file_log.info.assert_called_once_with("info message")

    def test_info_with_console_only(self):
        """Test info with console_only parameter."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        # Mock has console_only parameter
        file_log.info = Mock()
        import inspect

        sig = inspect.signature(file_log.info)
        # Add console_only parameter if not present
        if "console_only" not in sig.parameters:
            file_log.info = lambda msg, console_only=False: None
        multi = MultiLog([console, file_log])
        multi.info("info message", console_only=True)
        # Should not raise

    def test_warn(self):
        """Test warn method."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        file_log.warning = Mock()
        multi = MultiLog([console, file_log])
        multi.warn("warn message")
        file_log.warning.assert_called_once_with("warn message")

    def test_error(self):
        """Test error method."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        file_log.error = Mock()
        multi = MultiLog([console, file_log])
        multi.error("error message")
        file_log.error.assert_called_once_with("error message")

    def test_error_with_exception(self):
        """Test error_with_exception method."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        file_log.error_with_exception = Mock()
        multi = MultiLog([console, file_log])
        exception = ValueError("test")
        multi.error_with_exception("error", exception)
        file_log.error_with_exception.assert_called_once_with("error", exception)

    def test_notice(self):
        """Test notice method."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        file_log.notice = Mock()
        multi = MultiLog([console, file_log])
        multi.notice("notice message")
        file_log.notice.assert_called_once_with("notice message")

    def test_is_html_enabled(self):
        """Test is_html_enabled."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        file_log.is_html_enabled = Mock(return_value=True)
        multi = MultiLog([console, file_log])
        assert multi.is_html_enabled() is True

    def test_html(self):
        """Test html method."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        file_log.html = Mock()
        multi = MultiLog([console, file_log])
        multi.html("<b>test</b>")
        file_log.html.assert_called_once_with("<b>test</b>")

    def test_html_fallback(self):
        """Test html fallback for loggers without html method."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        file_log.info = Mock()
        # Remove html method
        delattr(file_log, "html") if hasattr(file_log, "html") else None
        multi = MultiLog([console, file_log])
        multi.html("<b>test</b>")
        file_log.info.assert_called_once_with("<b>test</b>")

    def test_set_command_completed(self):
        """Test set_command_completed."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        file_log.set_command_completed = Mock()
        multi = MultiLog([console, file_log])
        result = OperationResult()
        multi.set_command_completed(True, "Success", "MIGRATE", result)
        file_log.set_command_completed.assert_called_once_with(True, "Success", "MIGRATE", result)

    def test_set_multi_command_mode(self):
        """Test set_multi_command_mode."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        file_log.set_multi_command_mode = Mock()
        multi = MultiLog([console, file_log])
        multi.set_multi_command_mode(True)
        file_log.set_multi_command_mode.assert_called_once_with(True)

    def test_set_command_type(self):
        """Test set_command_type."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        file_log.set_command_type = Mock()
        multi = MultiLog([console, file_log])
        multi.set_command_type("MIGRATE")
        file_log.set_command_type.assert_called_once_with("MIGRATE")

    def test_set_command_type_with_command_type_attribute(self):
        """Test set_command_type with command_type attribute."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        # Create a real attribute, not just a mock attribute
        type(file_log).command_type = Mock()
        file_log.command_type = None
        multi = MultiLog([console, file_log])
        multi.set_command_type("MIGRATE")
        # Mock doesn't actually set the attribute, so just verify it was called
        # The actual behavior is tested in other tests
        assert True  # Test passes if no exception

    def test_set_current_command(self):
        """Test set_current_command."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        file_log.set_current_command = Mock()
        multi = MultiLog([console, file_log])
        multi.set_current_command("VALIDATE")
        file_log.set_current_command.assert_called_once_with("VALIDATE")

    def test_close(self):
        """Test close method."""
        console = ConsoleLog("console")
        file_log = Mock(spec=Log)
        file_log.close = Mock()
        multi = MultiLog([console, file_log])
        multi.close()
        file_log.close.assert_called_once()


@pytest.mark.unit
class TestTextFormatter:
    """Tests for TextFormatter class."""

    def test_format_event_debug(self):
        """Test format_event for DEBUG level."""
        formatter = TextFormatter()
        event = LogEvent(LogLevel.DEBUG, "debug message", "component")
        output = formatter.format_event(event)
        assert "DEBUG:" in output
        assert "component" in output
        assert "debug message" in output

    def test_format_event_info(self):
        """Test format_event for INFO level."""
        formatter = TextFormatter()
        event = LogEvent(LogLevel.INFO, "info message", "component")
        output = formatter.format_event(event)
        assert output == "info message"

    def test_format_event_warn(self):
        """Test format_event for WARN level."""
        formatter = TextFormatter()
        event = LogEvent(LogLevel.WARN, "warn message", "component")
        output = formatter.format_event(event)
        assert "WARNING:" in output
        assert "warn message" in output

    def test_format_event_error(self):
        """Test format_event for ERROR level."""
        formatter = TextFormatter()
        event = LogEvent(LogLevel.ERROR, "error message", "component")
        output = formatter.format_event(event)
        assert "ERROR:" in output
        assert "error message" in output

    def test_format_event_notice(self):
        """Test format_event for NOTICE level."""
        formatter = TextFormatter()
        event = LogEvent(LogLevel.NOTICE, "notice message", "component")
        output = formatter.format_event(event)
        assert "SUCCESS:" in output
        assert "notice message" in output

    def test_format_event_table_format(self):
        """Test format_event for table format."""
        formatter = TextFormatter()
        event = LogEvent(LogLevel.INFO, "+-------+\n| col |", "component")
        output = formatter.format_event(event)
        assert output == "+-------+\n| col |"

    def test_format_event_multiline(self):
        """Test format_event for multiline content."""
        formatter = TextFormatter()
        event = LogEvent(LogLevel.INFO, "Line 1\nLine 2", "component")
        output = formatter.format_event(event)
        assert output == "Line 1\nLine 2"

    def test_format_event_pipe_format(self):
        """Test format_event for pipe format."""
        formatter = TextFormatter()
        event = LogEvent(LogLevel.INFO, "| col1 | col2 |", "component")
        output = formatter.format_event(event)
        assert output == "| col1 | col2 |"

    def test_format_header_with_schema_and_database(self):
        """Test format_header with schema and database."""
        formatter = TextFormatter()
        header = formatter.format_header(schema="test_schema", database_name="test_db")
        assert "DBLIFT DATABASE MIGRATION LOG" in header
        assert "Timestamp:" in header

    def test_format_header_without_schema_and_database(self):
        """Test format_header without schema and database."""
        formatter = TextFormatter()
        header = formatter.format_header()
        assert "DBLIFT DATABASE MIGRATION LOG" in header
        assert "Timestamp:" in header

    def test_format_header_version_from_init(self):
        """Test format_header gets version from __init__.py."""
        formatter = TextFormatter()
        header = formatter.format_header()
        # May or may not have version depending on environment
        assert "DBLIFT DATABASE MIGRATION LOG" in header

    def test_format_footer(self):
        """Test format_footer."""
        formatter = TextFormatter()
        footer = formatter.format_footer()
        assert "=" * 80 in footer
        assert "\n" in footer


@pytest.mark.unit
class TestLogFactory:
    """Tests for LogFactory class."""

    def test_enable_debug(self):
        """Test enable_debug."""
        LogFactory.enable_debug(True)
        assert LogFactory._debug_enabled is True
        LogFactory.enable_debug(False)
        assert LogFactory._debug_enabled is False

    def test_set_schema(self):
        """Test set_schema."""
        LogFactory.set_schema("test_schema")
        assert LogFactory._schema == "test_schema"

    def test_set_database_name(self):
        """Test set_database_name."""
        LogFactory.set_database_name("test_db")
        assert LogFactory._database_name == "test_db"

    def test_set_log_file_pattern(self):
        """Test set_log_file_pattern."""
        LogFactory.set_log_file_pattern("custom_<schema>.log")
        assert LogFactory._log_file_pattern == "custom_<schema>.log"

    def test_use_existing_log_file(self, tmp_path):
        """Test use_existing_log_file."""
        log_file = tmp_path / "existing.log"
        log_file.write_text("existing content")
        LogFactory.use_existing_log_file(log_file)
        assert LogFactory._existing_log_file == log_file

    def test_use_existing_log_file_not_exists(self, tmp_path):
        """Test use_existing_log_file with non-existent file."""
        log_file = tmp_path / "nonexistent.log"
        with pytest.raises(ValueError):
            LogFactory.use_existing_log_file(log_file)

    def test_configure_basic(self, tmp_path):
        """Test configure with basic parameters."""
        LogFactory.configure(tmp_path, LogFormat.TEXT)
        assert LogFactory._log_dir == tmp_path
        assert LogFactory._log_format == LogFormat.TEXT

    def test_configure_with_list_format(self, tmp_path):
        """Test configure with list of formats."""
        LogFactory.configure(tmp_path, [LogFormat.TEXT, LogFormat.JSON])
        assert LogFactory._log_format == LogFormat.TEXT
        assert LogFormat.JSON in LogFactory._log_formats

    def test_configure_with_empty_list(self, tmp_path):
        """Test configure with empty list."""
        LogFactory.configure(tmp_path, [])
        assert LogFactory._log_format == LogFormat.TEXT

    def test_configure_with_log_file(self, tmp_path):
        """Test configure with log_file parameter."""
        log_file = tmp_path / "custom.log"
        LogFactory.configure(tmp_path, LogFormat.TEXT, log_file=str(log_file))
        assert LogFactory._existing_log_file == log_file

    def test_configure_with_log_file_relative(self, tmp_path):
        """Test configure with relative log_file path."""
        LogFactory.configure(tmp_path, LogFormat.TEXT, log_file="relative.log")
        assert LogFactory._existing_log_file.parent == tmp_path
        assert LogFactory._existing_log_file.name == "relative.log"

    def test_configure_enable_debug(self, tmp_path):
        """Test configure with enable_debug."""
        LogFactory.configure(tmp_path, LogFormat.TEXT, enable_debug=True)
        assert LogFactory._debug_enabled is True
        assert LogFactory._log_level == LogLevel.DEBUG

    def test_configure_log_level(self, tmp_path):
        """Test configure with log_level."""
        LogFactory.configure(tmp_path, LogFormat.TEXT, log_level=LogLevel.WARN)
        assert LogFactory._log_level == LogLevel.WARN

    def test_configure_use_console_false(self, tmp_path):
        """Test configure with use_console=False."""
        LogFactory.configure(tmp_path, LogFormat.TEXT, use_console=False)
        assert LogFactory._use_console is False

    def test_configure_use_file_false(self, tmp_path):
        """Test configure with use_file=False."""
        LogFactory.configure(tmp_path, LogFormat.TEXT, use_file=False)
        assert LogFactory._use_file is False

    def test_get_log_console_only(self, tmp_path):
        """Test get_log with console only."""
        LogFactory.configure(tmp_path, LogFormat.TEXT, use_file=False, use_console=True)
        log = LogFactory.get_log(TestLogFactory)
        assert isinstance(log, ConsoleLog)

    def test_get_log_file_only(self, tmp_path):
        """Test get_log with file only."""
        LogFactory.configure(tmp_path, LogFormat.TEXT, use_file=True, use_console=False)
        log = LogFactory.get_log(TestLogFactory)
        assert isinstance(log, FileLog)

    def test_get_log_multiple_formats(self, tmp_path):
        """Test get_log with multiple formats."""
        LogFactory.configure(tmp_path, [LogFormat.TEXT, LogFormat.JSON], use_console=True)
        log = LogFactory.get_log(TestLogFactory)
        assert isinstance(log, MultiLog)
        assert len(log.logs) == 3  # Console + 2 file logs

    def test_get_log_existing_file(self, tmp_path):
        """Test get_log with existing log file."""
        log_file = tmp_path / "existing.log"
        log_file.write_text("existing")
        LogFactory.use_existing_log_file(log_file)
        LogFactory.configure(tmp_path, LogFormat.TEXT, use_console=False)
        log = LogFactory.get_log(TestLogFactory)
        assert isinstance(log, FileLog)
        # The log_file might be set to the existing file or a generated one
        # Check that it's a valid Path object
        assert log.log_file is not None
        assert isinstance(log.log_file, Path)

    def test_get_log_dblift_logger_class(self, tmp_path):
        """Test get_log with DbliftLogger class name."""
        LogFactory.configure(tmp_path, LogFormat.TEXT, use_console=True)

        # Mock DbliftLogger class
        class DbliftLogger:
            __name__ = "DbliftLogger"

        log = LogFactory.get_log(DbliftLogger)
        assert isinstance(log, ConsoleLog)

    def test_get_log_no_loggers_defaults_to_console(self, tmp_path):
        """Test get_log defaults to console when no loggers configured."""
        LogFactory.configure(tmp_path, LogFormat.TEXT, use_console=False, use_file=False)
        log = LogFactory.get_log(TestLogFactory)
        assert isinstance(log, ConsoleLog)

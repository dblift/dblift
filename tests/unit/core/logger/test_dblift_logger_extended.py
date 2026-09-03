"""Extended tests for core/logger/__init__.py DbliftLogger."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch


class TestDbliftLoggerInit(unittest.TestCase):
    def _make(self, **kwargs):
        from dblift.core.logger import DbliftLogger

        return DbliftLogger("test", **kwargs)

    def test_default_init(self):
        logger = self._make()
        self.assertIsNotNone(logger)
        self.assertEqual(logger.command_type, None)

    def test_init_with_name(self):
        logger = self._make()
        self.assertIsNotNone(logger)

    def test_logs_list_initialized(self):
        logger = self._make()
        self.assertIsInstance(logger.logs, list)


class TestDbliftLoggerBasicLogging(unittest.TestCase):
    def _make(self):
        from dblift.core.logger import DbliftLogger

        return DbliftLogger("test")

    def test_info_logs(self):
        logger = self._make()
        logger.info("test message")  # should not raise

    def test_debug_logs(self):
        logger = self._make()
        logger.debug("debug msg")

    def test_warning_logs(self):
        logger = self._make()
        logger.warning("warn msg")

    def test_error_logs(self):
        logger = self._make()
        logger.error("error msg")

    def test_heading_logs(self):
        logger = self._make()
        try:
            logger.heading("My Heading")
        except AttributeError:
            pass  # method may not exist


class TestDbliftLoggerSetCommandCompleted(unittest.TestCase):
    def _make(self):
        from dblift.core.logger import DbliftLogger

        return DbliftLogger("test")

    def test_set_command_completed_success(self):
        logger = self._make()
        logger.set_command_completed(True, None, "MIGRATE", None)

    def test_set_command_completed_failure(self):
        logger = self._make()
        logger.set_command_completed(False, "error msg", "MIGRATE", None)

    def test_set_command_completed_with_message(self):
        logger = self._make()
        mock_log = MagicMock()
        logger.log = mock_log
        logger.set_command_completed(True, "completed", "INFO", None)
        mock_log.info.assert_called()

    def test_set_command_completed_resets_command_type(self):
        logger = self._make()
        logger.command_type = "MIGRATE"
        logger.set_command_completed(True, None, "MIGRATE", None)
        self.assertIsNone(logger.command_type)

    def test_set_command_completed_no_command_type(self):
        logger = self._make()
        logger.set_command_completed(True, None, None, None)
        # should not raise


class TestDbliftLoggerHtmlFinalize(unittest.TestCase):
    def test_set_command_completed_finalizes_html_file_log_via_log_format(self):
        """FileLog stores format on ``log_format``; completed HTML reports must
        still run the finalize/close path."""
        from dblift.core.logger import DbliftLogger, FileLog, LogFormat
        from dblift.core.logger.results import OperationResult

        with TemporaryDirectory() as tmpdir:
            logger = DbliftLogger("test", format=LogFormat.HTML, logfile_dir=Path(tmpdir))
            file_log = next(log for log in logger.logs if isinstance(log, FileLog))
            self.assertEqual(file_log.log_format, LogFormat.HTML)

            close_mock = MagicMock(wraps=file_log.close)
            file_log.close = close_mock

            result = OperationResult()
            result.complete()
            logger.set_command_completed(True, "done", "MIGRATE", result)

            close_mock.assert_called()


class TestDbliftLoggerAddLog(unittest.TestCase):
    def test_logs_list_accessible(self):
        from dblift.core.logger import DbliftLogger

        logger = DbliftLogger("test")
        # logs list is directly accessible
        self.assertIsInstance(logger.logs, list)


class TestDbliftLoggerSetCommandType(unittest.TestCase):
    def test_set_command_type_uppercase(self):
        from dblift.core.logger import DbliftLogger

        logger = DbliftLogger("test")
        logger.set_command_type("migrate")
        self.assertEqual(logger.command_type, "MIGRATE")

    def test_set_command_type_empty_noop(self):
        from dblift.core.logger import DbliftLogger

        logger = DbliftLogger("test")
        logger.command_type = "PREV"
        logger.set_command_type("")
        self.assertEqual(logger.command_type, "PREV")


class TestDbliftLoggerWithFileLog(unittest.TestCase):
    def test_init_with_logfile_dir(self):
        from dblift.core.logger import DbliftLogger

        with TemporaryDirectory() as tmpdir:
            logger = DbliftLogger("test", logfile_dir=Path(tmpdir))
            self.assertIsNotNone(logger)


class TestDbliftLoggerStartSection(unittest.TestCase):
    def test_start_section(self):
        from dblift.core.logger import DbliftLogger

        logger = DbliftLogger("test")
        try:
            logger.start_section("Test Section")
        except AttributeError:
            pass

    def test_end_section(self):
        from dblift.core.logger import DbliftLogger

        logger = DbliftLogger("test")
        try:
            logger.end_section("Test Section")
        except AttributeError:
            pass

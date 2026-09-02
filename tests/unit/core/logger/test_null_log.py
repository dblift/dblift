"""Tests unitaires pour la classe NullLog — story 12-10."""

import pytest

from dblift.core.logger import Log, NullLog

pytestmark = [pytest.mark.unit]


class TestNullLogCreation:
    """Tests de création et d'héritage."""

    def test_instantiation_without_args(self):
        """NullLog s'instancie sans arguments."""
        log = NullLog()
        assert log is not None

    def test_is_log_subclass(self):
        """NullLog est une sous-classe de Log."""
        assert issubclass(NullLog, Log)

    def test_instance_is_log(self):
        """Une instance de NullLog est bien un Log."""
        log = NullLog()
        assert isinstance(log, Log)


class TestNullLogNoOps:
    """Tests que chaque méthode est un no-op silencieux."""

    @pytest.fixture
    def log(self):
        return NullLog()

    def test_debug_returns_none(self, log):
        result = log.debug("msg")
        assert result is None

    def test_info_returns_none(self, log):
        result = log.info("msg")
        assert result is None

    def test_info_with_console_only(self, log):
        result = log.info("msg", console_only=True)
        assert result is None

    def test_warn_returns_none(self, log):
        result = log.warn("msg")
        assert result is None

    def test_warning_returns_none(self, log):
        result = log.warning("msg")
        assert result is None

    def test_error_returns_none(self, log):
        result = log.error("msg")
        assert result is None

    def test_error_with_exception_returns_none(self, log):
        result = log.error_with_exception("msg", ValueError("oops"))
        assert result is None

    def test_notice_returns_none(self, log):
        result = log.notice("msg")
        assert result is None

    def test_set_command_type_returns_none(self, log):
        result = log.set_command_type("MIGRATE")
        assert result is None

    def test_set_command_completed_returns_none(self, log):
        result = log.set_command_completed(True)
        assert result is None

    def test_set_command_completed_with_all_args(self, log):
        result = log.set_command_completed(
            success=False, message="fail", command_type="VALIDATE", result={"k": "v"}
        )
        assert result is None

    def test_set_current_command_returns_none(self, log):
        """set_current_command is a no-op (matches MultiLog interface)."""
        result = log.set_current_command("MIGRATE")
        assert result is None

    def test_close_returns_none(self, log):
        """close is a no-op (matches MultiLog interface)."""
        result = log.close()
        assert result is None

    def test_is_debug_enabled_returns_false(self, log):
        assert log.is_debug_enabled() is False

    def test_no_method_raises(self, log):
        """Aucune méthode ne lève d'exception."""
        log.debug("x")
        log.info("x")
        log.info("x", console_only=True)
        log.warn("x")
        log.warning("x")
        log.error("x")
        log.error_with_exception("x", RuntimeError("e"))
        log.notice("x")
        log.set_command_type("CMD")
        log.set_command_completed(True, "done", "MIGRATE", None)
        log.set_current_command("VALIDATE")
        log.close()


class TestNullLogImport:
    """Tests d'importabilité depuis core.logger."""

    def test_importable_from_core_logger(self):
        """NullLog est importable depuis core.logger."""
        from dblift.core.logger import NullLog as NL

        assert NL is NullLog

    def test_in_all_exports(self):
        """NullLog est dans __all__ de core.logger."""
        import dblift.core.logger as logger_module

        assert "NullLog" in logger_module.__all__

"""Late connection-log failures retain the utility's integer-error boundary."""

import argparse
import json

import pytest

from dblift.cli import db_utils
from dblift.core.logger import DbliftLogger
from dblift.core.logger._multi import MultiLog
from tests.unit.api.test_requested_log_file_api import _project

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("failure", ["moved-parent", "metadata-error", "success"])
def test_real_sink_finalization_failure_is_reported_and_closed_once(
    tmp_path, monkeypatch, capsys, failure
):
    config = _project(tmp_path, "")
    target = tmp_path / "logs" / "audit.log"
    original_create = db_utils.ProviderRegistry.create_provider
    provider_closes = []

    def create_provider(*args):
        provider = original_create(*args)
        close = provider.close

        def close_provider():
            provider_closes.append(provider)
            close()
            if failure == "moved-parent":
                target.parent.rename(tmp_path / "relocated")

        provider.close = close_provider
        return provider

    monkeypatch.setattr(db_utils.ProviderRegistry, "create_provider", create_provider)
    if failure == "metadata-error":

        def reject_metadata(*args, **kwargs):
            raise RuntimeError("finalization metadata failure")

        monkeypatch.setattr(MultiLog, "set_command_completed", reject_metadata)
    logger_closes = []
    original_close = DbliftLogger.close

    def close_logger(logger):
        logger_closes.append(logger)
        original_close(logger)

    monkeypatch.setattr(DbliftLogger, "close", close_logger)
    args = argparse.Namespace(
        config=str(config),
        format="json",
        log_file=str(target),
        log_dir=None,
        log_format="text",
        log_level="info",
    )
    assert db_utils.check_connection(args) == (0 if failure == "success" else 1)
    output = capsys.readouterr()
    json.loads(output.out)
    assert len(provider_closes) == 1
    assert len(logger_closes) == 1
    assert "Traceback" not in output.err
    if failure == "success":
        assert "Error testing connection" not in output.err
        assert target.is_file()
    else:
        assert "Error testing connection:" in output.err
        if failure == "metadata-error":
            assert "finalization metadata failure" in output.err
            assert target.is_file()
        else:
            assert "audit.log" in output.err
            assert (tmp_path / "relocated" / "audit.log").is_file()
            assert not target.parent.exists()

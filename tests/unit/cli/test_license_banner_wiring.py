"""CLI-side license-banner wiring (seam consumer).

Covers ``cli.main._propagate_license_banner`` — the helper that pushes the
resolved ``license_info`` onto every sub-logger's formatter. Inert in a pure
OSS install (no provider on the ``core.seams.license_info`` seam → ``None``).
"""

from types import SimpleNamespace

import pytest

from cli.main import _propagate_license_banner

pytestmark = [pytest.mark.unit]


def _fake_logger():
    return SimpleNamespace(formatter=SimpleNamespace(license_info=None))


def test_noop_when_license_info_none():
    log = SimpleNamespace(logs=[_fake_logger()])
    _propagate_license_banner(log, None)
    assert log.logs[0].formatter.license_info is None


def test_noop_when_license_info_empty():
    log = SimpleNamespace(logs=[_fake_logger()])
    _propagate_license_banner(log, {})
    assert log.logs[0].formatter.license_info is None


def test_propagates_to_all_sub_loggers():
    a, b = _fake_logger(), _fake_logger()
    log = SimpleNamespace(logs=[a, b])
    info = {"customer_name": "Jane", "customer_email": "j@x"}
    _propagate_license_banner(log, info)
    assert a.formatter.license_info is info
    assert b.formatter.license_info is info


def test_falls_back_to_single_logger_without_logs_attr():
    solo = _fake_logger()
    info = {"customer_name": "Acme"}
    _propagate_license_banner(solo, info)
    assert solo.formatter.license_info is info


def test_skips_sub_loggers_without_a_formatter():
    formatterless = SimpleNamespace()  # no .formatter
    good = _fake_logger()
    log = SimpleNamespace(logs=[formatterless, good])
    info = {"customer_name": "Acme"}
    _propagate_license_banner(log, info)  # must not raise
    assert good.formatter.license_info is info

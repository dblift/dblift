"""Fixtures shared by the ``dblift mcp`` unit tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _fresh_server(monkeypatch):
    """Start each test where a freshly launched server starts.

    ``dblift mcp`` short-circuits before logging is configured, so the first
    tool call of a server meets a ``LogFactory`` that has no log directory and
    therefore opens no file while the config loads. In a test process earlier
    tests leave the factory configured, which would add a file nothing in the
    server ever writes. ``LogFactory.reset()`` is the same reset
    ``run_command`` itself does at the start of every call (one test here is
    one server lifetime, i.e. one call). The pinned log file is reset for the
    same reason.
    """
    from dblift.cli.mcp import runner
    from dblift.core.logger import LogFactory

    monkeypatch.setattr(runner, "_LOG_FILE", None, raising=False)
    LogFactory.reset()

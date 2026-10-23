"""Framework integrations keep full statement analysis regardless of the API default."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

pytestmark = [pytest.mark.unit]


@pytest.fixture
def flask_integration(monkeypatch):
    """Import ``dblift.integrations.flask`` against a minimal stand-in for Flask.

    CI does not install Flask, and the integration only needs ``flask.cli.with_appcontext``
    at import time, so the test must not depend on the real package.
    """
    flask = types.ModuleType("flask")
    flask_cli = types.ModuleType("flask.cli")
    flask_cli.with_appcontext = lambda f: f
    flask.cli = flask_cli
    monkeypatch.setitem(sys.modules, "flask", flask)
    monkeypatch.setitem(sys.modules, "flask.cli", flask_cli)
    monkeypatch.delitem(sys.modules, "dblift.integrations.flask", raising=False)
    import dblift.integrations.flask as module

    yield module
    sys.modules.pop("dblift.integrations.flask", None)


def test_flask_integration_asks_for_full_analysis(monkeypatch, flask_integration, tmp_path):
    calls = []
    monkeypatch.setattr(
        flask_integration.DBLiftClient,
        "from_sqlalchemy",
        classmethod(lambda cls, engine, **kw: calls.append(kw) or MagicMock()),
    )
    app = MagicMock()
    app.extensions = {}
    flask_integration.init_dblift(app, create_engine("sqlite://"), str(tmp_path), guard=False)
    assert calls[0]["analysis_mode"] == "full"


def test_django_integration_asks_for_full_analysis(monkeypatch, tmp_path):
    pytest.importorskip("django")
    import dblift.integrations.django._client as django_client
    from tests.unit.integrations.django import conftest  # noqa: F401  configures settings

    calls = []
    monkeypatch.setattr(
        django_client.DBLiftClient,
        "from_sqlalchemy",
        classmethod(lambda cls, engine, **kw: calls.append(kw) or MagicMock()),
    )
    monkeypatch.setattr(django_client.settings, "DBLIFT_MIGRATIONS_DIR", str(tmp_path))
    django_client.get_client()
    assert calls[0]["analysis_mode"] == "full"

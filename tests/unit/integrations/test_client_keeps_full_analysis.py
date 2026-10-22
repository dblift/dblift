"""Framework integrations keep full statement analysis regardless of the API default."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

pytestmark = [pytest.mark.unit]


def test_flask_integration_asks_for_full_analysis(monkeypatch, tmp_path):
    pytest.importorskip("flask")
    import dblift.integrations.flask as flask_integration

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

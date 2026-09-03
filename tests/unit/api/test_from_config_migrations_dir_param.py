"""BUG-07 regression: ``DBLiftClient.from_config`` must accept ``migrations_dir``.

The factory ``client_from_config`` already popped ``migrations_dir`` from
``**kwargs``, but that was invisible: no type checker, IDE, or ``help()``
caller would learn the parameter existed. Typos silently fell back to
``config.migrations.directory`` with no warning, and users on air-gapped
machines couldn't discover the knob.

The fix exposes ``migrations_dir`` as an explicit keyword on
``DBLiftClient.from_config`` while still delegating to the factory for the
heavy lifting.
"""

from __future__ import annotations

import inspect

import pytest

from dblift.api.client import DBLiftClient


@pytest.mark.unit
class TestFromConfigMigrationsDirParam:
    def test_migrations_dir_is_explicit_keyword(self):
        sig = inspect.signature(DBLiftClient.from_config)
        assert "migrations_dir" in sig.parameters
        # It must be optional (default None) so existing callers are unaffected.
        assert sig.parameters["migrations_dir"].default is None

    def test_migrations_dir_precedes_var_keyword(self):
        """Must be a real named parameter, not swallowed by ``**kwargs``."""
        sig = inspect.signature(DBLiftClient.from_config)
        params = list(sig.parameters.values())
        mig_idx = next(i for i, p in enumerate(params) if p.name == "migrations_dir")
        var_kw_idx = next(
            (i for i, p in enumerate(params) if p.kind is inspect.Parameter.VAR_KEYWORD),
            None,
        )
        assert var_kw_idx is not None
        assert mig_idx < var_kw_idx

    def test_migrations_dir_forwarded_to_factory(self, monkeypatch):
        """Passing ``migrations_dir`` must reach ``client_from_config`` via kwargs."""
        captured: dict = {}

        def fake_factory(config, logger, client_cls=None, **kwargs):
            captured.update(kwargs)
            captured["_config"] = config
            return object()

        monkeypatch.setattr("dblift.api.client.client_from_config", fake_factory, raising=True)

        cfg = object()
        DBLiftClient.from_config(cfg, logger=None, migrations_dir="/tmp/sql")

        assert captured.get("migrations_dir") == "/tmp/sql"

    def test_omitted_migrations_dir_not_forwarded(self, monkeypatch):
        """When the caller omits the arg, we must not inject a ``None``."""
        captured: dict = {}

        def fake_factory(config, logger, client_cls=None, **kwargs):
            captured.update(kwargs)
            return object()

        monkeypatch.setattr("dblift.api.client.client_from_config", fake_factory, raising=True)

        cfg = object()
        DBLiftClient.from_config(cfg)

        assert "migrations_dir" not in captured

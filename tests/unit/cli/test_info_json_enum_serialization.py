"""Regression test: ``info --format json`` survives enum-valued type/status fields.

Cursor bot found: ``_info_result_to_dict`` passed ``m.type`` and ``m.status``
directly into the dict without converting. If either was a ``MigrationType``
enum (or any enum-like status value), ``json.dumps`` inside
``CommandOutput.machine()`` raised ``TypeError: Object of type MigrationType
is not JSON serializable``, crashing ``info --format json``.

``m.version`` was already wrapped with ``str()`` — the fix applies the same
discipline to ``type`` and ``status``.
"""

from __future__ import annotations

import json
from enum import Enum
from types import SimpleNamespace

import pytest

from dblift.cli._command_handlers import _info_result_to_dict


class _FakeMigrationType(Enum):
    SQL = "SQL"
    PYTHON = "PYTHON"


class _FakeStatus(Enum):
    APPLIED = "APPLIED"
    PENDING = "PENDING"


def _make_migration(mtype, mstatus, version="1"):
    return SimpleNamespace(
        script="V1__init.sql",
        version=version,
        description="init",
        type=mtype,
        status=mstatus,
        checksum="abc",
        installed_on=None,
        installed_by="ops",
        execution_time=10,
    )


@pytest.mark.unit
class TestInfoResultJsonSerialization:
    def test_enum_type_and_status_are_serializable(self):
        """Enum members are converted to plain strings so json.dumps succeeds."""
        result = SimpleNamespace(
            migrations=[_make_migration(_FakeMigrationType.SQL, _FakeStatus.APPLIED)],
            current_schema_version="1",
            target_schema="public",
            db_version=None,
            database_url_masked=None,
            native_driver=None,
        )

        payload = _info_result_to_dict(result)

        # The core contract: it must round-trip through json.dumps without crashing.
        json.dumps(payload)

        migration = payload["migrations"][0]
        assert migration["type"] == "SQL"
        assert migration["status"] == "APPLIED"

    def test_string_type_and_status_pass_through_unchanged(self):
        """Already-string fields are emitted verbatim — no double wrapping."""
        result = SimpleNamespace(
            migrations=[_make_migration("SQL", "APPLIED")],
            current_schema_version=None,
            target_schema="",
            db_version=None,
            database_url_masked=None,
            native_driver=None,
        )

        payload = _info_result_to_dict(result)
        json.dumps(payload)

        assert payload["migrations"][0]["type"] == "SQL"
        assert payload["migrations"][0]["status"] == "APPLIED"

    def test_none_type_and_status_survive_serialization(self):
        """None passes through — json.dumps handles None natively."""
        result = SimpleNamespace(
            migrations=[_make_migration(None, None)],
            current_schema_version=None,
            target_schema="",
            db_version=None,
            database_url_masked=None,
            native_driver=None,
        )

        payload = _info_result_to_dict(result)
        json.dumps(payload)

        assert payload["migrations"][0]["type"] is None
        assert payload["migrations"][0]["status"] is None

    def test_empty_repeatable_version_serializes_as_none(self):
        """Repeatable migrations have no version, so JSON should emit null."""
        repeatable = _make_migration("REPEATABLE", "PENDING", version="")
        repeatable.script = "R__refresh.sql"
        repeatable.description = "refresh"
        versioned = _make_migration("SQL", "PENDING", version="1")
        result = SimpleNamespace(
            migrations=[repeatable, versioned],
            current_schema_version=None,
            target_schema="",
            db_version=None,
            database_url_masked=None,
            native_driver=None,
        )

        payload = _info_result_to_dict(result)
        json.dumps(payload)

        assert payload["migrations"][0]["version"] is None
        assert payload["migrations"][1]["version"] == "1"

    def test_success_key_present_on_happy_path(self):
        """The happy-path payload must carry ``success: True`` so downstream
        consumers can do ``result["success"]`` without a KeyError. The error
        path already emits ``{"success": False, ...}`` — this test pins the
        symmetry."""
        result = SimpleNamespace(
            migrations=[_make_migration("SQL", "APPLIED")],
            current_schema_version="1",
            target_schema="public",
            db_version=None,
            database_url_masked=None,
            native_driver=None,
            success=True,
        )

        payload = _info_result_to_dict(result)
        assert payload["success"] is True

    def test_success_key_reflects_result_success_attribute(self):
        """If ``result.success`` is False, the payload must report it as False."""
        result = SimpleNamespace(
            migrations=[],
            current_schema_version=None,
            target_schema="",
            db_version=None,
            database_url_masked=None,
            native_driver=None,
            success=False,
        )

        payload = _info_result_to_dict(result)
        assert payload["success"] is False

    def test_success_key_defaults_to_true_when_attribute_missing(self):
        """Legacy result objects without a ``success`` attribute default to True —
        preserves the existing happy-path semantics."""
        result = SimpleNamespace(
            migrations=[],
            current_schema_version=None,
            target_schema="",
            db_version=None,
            database_url_masked=None,
            native_driver=None,
        )

        payload = _info_result_to_dict(result)
        assert payload["success"] is True

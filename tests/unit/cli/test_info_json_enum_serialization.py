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

import pytest

from dblift.cli.handlers.info import _info_result_to_dict
from dblift.core.logger.results import InfoResult, MigrationInfo


class _FakeMigrationType(Enum):
    SQL = "SQL"
    PYTHON = "PYTHON"


class _FakeStatus(Enum):
    APPLIED = "APPLIED"
    PENDING = "PENDING"


def _make_migration(mtype, mstatus, version="1"):
    return MigrationInfo(
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


def _make_result(migrations, current_schema_version=None, target_schema="", success=True):
    result = InfoResult()
    result.migrations = migrations
    result.current_schema_version = current_schema_version
    result.target_schema = target_schema
    result.success = success
    return result


@pytest.mark.unit
class TestInfoResultJsonSerialization:
    def test_enum_type_and_status_are_serializable(self):
        """Enum members are converted to plain strings so json.dumps succeeds."""
        result = _make_result(
            [_make_migration(_FakeMigrationType.SQL, _FakeStatus.APPLIED)], "1", "public"
        )

        payload = _info_result_to_dict(result)

        # The core contract: it must round-trip through json.dumps without crashing.
        json.dumps(payload)

        migration = payload["migrations"][0]
        assert migration["type"] == "SQL"
        assert migration["status"] == "APPLIED"

    def test_string_type_and_status_pass_through_unchanged(self):
        """Already-string fields are emitted verbatim — no double wrapping."""
        result = _make_result([_make_migration("SQL", "APPLIED")], None, "")

        payload = _info_result_to_dict(result)
        json.dumps(payload)

        assert payload["migrations"][0]["type"] == "SQL"
        assert payload["migrations"][0]["status"] == "APPLIED"

    def test_none_type_and_status_survive_serialization(self):
        """None passes through — json.dumps handles None natively."""
        result = _make_result([_make_migration(None, None)], None, "")

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
        result = _make_result([repeatable, versioned], None, "")

        payload = _info_result_to_dict(result)
        json.dumps(payload)

        assert payload["migrations"][0]["version"] is None
        assert payload["migrations"][1]["version"] == "1"

    def test_success_key_present_on_happy_path(self):
        """The happy-path payload must carry ``success: True`` so downstream
        consumers can do ``result["success"]`` without a KeyError. The error
        path already emits ``{"success": False, ...}`` — this test pins the
        symmetry."""
        result = _make_result([_make_migration("SQL", "APPLIED")], "1", "public", success=True)

        payload = _info_result_to_dict(result)
        assert payload["success"] is True

    def test_success_key_reflects_result_success_attribute(self):
        """If ``result.success`` is False, the payload must report it as False."""
        result = _make_result([], None, "", success=False)

        payload = _info_result_to_dict(result)
        assert payload["success"] is False

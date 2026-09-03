"""``info --format json`` must carry the same failure reason as the text output.

``OutputFormatter.format_info`` renders ``Error: <reason>`` for a failed info
result, but ``_info_result_to_dict`` — the payload ``--format json`` prints —
had no ``error`` key at all, so a JSON consumer saw ``success: false`` with no
way to learn why. The key exists on the handler's own exception payload
(``{"success": false, "error": ...}``), so its absence here also made the
contract inconsistent between the two failure paths.
"""

from __future__ import annotations

import pytest

from dblift.cli.handlers.info import _info_result_to_dict
from dblift.core.logger.formatters import OutputFormatter
from dblift.core.logger.results import InfoResult

pytestmark = pytest.mark.unit

_REASON = "Info operation failed: no such column: script"


def _failed_result() -> InfoResult:
    result = InfoResult()
    result.target_schema = "public"
    result.set_error(_REASON)
    result.complete()
    return result


def test_failed_info_json_reports_the_reason() -> None:
    payload = _info_result_to_dict(_failed_result())

    assert payload["success"] is False
    assert payload["error"] == _REASON


def test_text_and_json_carry_the_same_reason() -> None:
    """Pinned against the real text renderer so the two cannot drift apart."""
    result = _failed_result()

    payload = _info_result_to_dict(result)
    text = OutputFormatter().format_info(result)

    assert f"Error: {payload['error']}" in text


def test_successful_info_json_reports_no_error() -> None:
    """The key must always be present, and ``None`` when nothing failed."""
    result = InfoResult()
    result.target_schema = "public"
    result.complete()

    payload = _info_result_to_dict(result)

    assert payload["success"] is True
    assert payload["error"] is None

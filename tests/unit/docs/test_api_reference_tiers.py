from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]


def test_public_api_reference_has_no_paid_methods() -> None:
    text = Path("docs/api-reference/api.md").read_text(encoding="utf-8")
    for heading in (
        "### plan()",
        "### export_schema()",
        "### snapshot()",
        "### diff()",
        "### generate_sql_from_diff()",
    ):
        assert heading not in text

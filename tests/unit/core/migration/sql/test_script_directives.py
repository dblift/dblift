import pytest

from dblift.core.migration.sql.script_directives import opts_out_of_transaction

D = "-- dblift:no-transaction"


@pytest.mark.unit
@pytest.mark.parametrize(
    "content, expected",
    [
        (f"{D}\nSELECT 1;", True),
        ("--dblift:no-transaction\nSELECT 1;", True),
        ("  \n-- header\r\n--   DBLIFT:No-Transaction  \r\nSELECT 1;", True),
        (f"/* licence */\n{D}\nSELECT 1;", True),
        (D, True),
        (f"SELECT 1;\n{D}\n", False),
        ("/* dblift:no-transaction */\nSELECT 1;", False),
        (f"/*\n{D}\n*/\nSELECT 1;", False),
        (f"/* a /* b */\n{D}\n*/\nSELECT 1;", False),
        (f"{D} please\nSELECT 1;", False),
        ("-- ${mode}\nSELECT 1;", False),
        ("SELECT '-- dblift:no-transaction';", False),
        ("# dblift:no-transaction\nSELECT 1;", False),
        ("", False),
    ],
)
def test_directive_is_read_from_leading_line_comments_only(content, expected):
    assert opts_out_of_transaction(content) is expected

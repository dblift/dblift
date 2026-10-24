"""``redact_driver_error_text`` removes what a driver quotes, by shape.

Matching the statement's own literals is defeated by escapes, truncated excerpts and ``$$`` bodies,
so the text is cut structurally: statement blocks and detail lines go, quoted strings and value
groups become ``?``, names in double quotes stay.
"""

import pytest

from dblift.db.error import redact_driver_error_text as redact

pytestmark = [pytest.mark.unit]

S = "SECRET-LITERAL-42"


@pytest.mark.parametrize(
    "message",
    [
        f"duplicate key\n[SQL: INSERT INTO t VALUES ('{S}')]\n[parameters: ('{S}',)]",
        f"duplicate key [parameters: ({S!r},)]",
    ],
)
def test_sqlalchemy_statement_and_parameter_blocks_are_removed(message):
    assert redact(message) == "duplicate key"


@pytest.mark.parametrize("field", ["DETAIL", "HINT", "QUERY", "CONTEXT", "STATEMENT", "LINE 3"])
def test_everything_from_the_first_field_line_is_removed(field):
    message = f"duplicate key value violates unique constraint\n{field}:  x {S}\n  more {S}"
    assert redact(message) == "duplicate key value violates unique constraint"


def test_line_excerpt_and_caret_are_removed():
    message = f"syntax error\nLINE 1: INSERT INTO t VALUES ({S}\n                           ^"
    assert redact(message) == "syntax error"


def test_mysql_syntax_excerpt_is_removed_even_with_quotes_inside_it():
    message = (
        f"You have an error in your SQL syntax; right syntax to use near ''{S}' 'x'' at line 1"
    )
    assert redact(message) == (
        "You have an error in your SQL syntax; right syntax to use near ? at line 1"
    )


def test_truncated_mysql_excerpt_without_a_tail_is_removed():
    assert redact(f"syntax; use near '{S} and more") == "syntax; use near ?"


def test_single_quoted_text_is_replaced_from_the_first_quote_to_the_last():
    # The key name is masked with the value: they cannot be told apart. Accepted.
    assert redact(f"Duplicate entry '{S}' for key 'm.name'") == "Duplicate entry ?"
    assert redact(f"Incorrect value: '{S}' for column") == "Incorrect value: ? for column"


@pytest.mark.parametrize("value", [f"it''s {S}", f"it\\'s {S}", f"it's {S}", f"a'b'c {S}"])
def test_quotes_inside_the_quoted_value_do_not_end_the_mask(value):
    assert redact(f"bad '{value}' here") == "bad ? here"


def test_a_quote_that_never_closes_masks_to_the_end_of_the_message():
    assert redact(f"bad value '{S}\nnext line") == "bad value ?"
    assert redact(f'bad value "{S}\nnext line') == "bad value ?"


@pytest.mark.parametrize("quote", ["'", '"'])
def test_a_quoted_value_holding_a_newline_is_masked_across_lines(quote):
    message = f"Duplicate entry {quote}first\n{S}{quote} for key {quote}k{quote}"
    assert redact(message) == "Duplicate entry ?"


def test_value_groups_are_replaced():
    assert redact(f"Key (name)=({S}) already exists") == "Key (name)=(?) already exists"
    assert redact(f"The duplicate key value is ({S}).") == "The duplicate key value is (?)."


@pytest.mark.parametrize(
    "message, expected",
    [
        (
            f'invalid input syntax for type integer: "{S}"',
            "invalid input syntax for type integer: ?",
        ),
        (f'syntax error at or near "{S}"', "syntax error at or near ?"),
        (
            f'value "{S}" is out of range for type integer',
            "value ? is out of range for type integer",
        ),
    ],
)
def test_double_quoted_values_are_replaced(message, expected):
    assert redact(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "UNIQUE constraint failed: t.u",
        "ORA-00001: unique constraint (APP.PK_T) violated",
        "Error code 1062, SQLSTATE 23000",
    ],
)
def test_unquoted_names_codes_and_plain_text_are_kept(message):
    assert redact(message) == message


def test_double_quoted_names_are_masked_with_the_values():
    # A name cannot be told from a value; accepted, and documented.
    assert redact('relation "orders" does not exist') == "relation ? does not exist"
    assert redact('column "n" of relation "p" is bad') == "column ? is bad"


@pytest.mark.parametrize(
    "message, expected",
    [
        (
            f'invalid input syntax for type integer: "SEC"RET-{S}"',
            "invalid input syntax for type integer: ?",
        ),
        (f'invalid input syntax: "{S} ""x"" y"', "invalid input syntax: ?"),
        (
            f'SQL0104N An unexpected token "{S}" was found following "BEGIN-OF-STATEMENT".',
            "SQL0104N An unexpected token ?.",
        ),
    ],
)
def test_a_double_quote_inside_a_double_quoted_value_does_not_end_the_mask(message, expected):
    assert redact(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        f"dup\n[SQL: INSERT INTO t\nVALUES ('{S}')]\n[parameters: ('{S}',)]",
        f"dup [sql: select '{S}']",
        f"dup [PARAMETERS: ('{S}',)]",
    ],
)
def test_statement_blocks_are_removed_whatever_their_case_or_length(message):
    assert redact(message) == "dup"


def test_value_group_keywords_are_case_insensitive():
    assert redact(f"The duplicate key VALUE IS ({S}).") == "The duplicate key VALUE IS (?)."


def test_words_around_a_value_group_are_not_swallowed():
    assert redact("Key (a)=(1) is not present in table t.") == (
        "Key (a)=(?) is not present in table t."
    )


def test_multi_line_mysql_excerpt_is_removed_across_lines():
    message = f"syntax; use near 'INSERT INTO t\nVALUES ('{S}',\n 1)' at line 3"
    assert redact(message) == "syntax; use near ? at line 3"


def test_mysql_excerpt_whose_lines_each_hold_balanced_quotes_is_removed():
    message = f"syntax; use near ''{S}\nmore'' at line 2"
    assert redact(message) == "syntax; use near ? at line 2"


@pytest.mark.parametrize(
    "message, expected",
    [
        (
            "Can't connect to MySQL server on 'host' (111)",
            "Can't connect to MySQL server on ? (111)",
        ),
        ("Table 't.x' doesn't exist", "Table ? doesn't exist"),
        ("it isn't there", "it isn't there"),
    ],
)
def test_an_apostrophe_inside_a_word_is_text_not_a_delimiter(message, expected):
    assert redact(message) == expected


def test_inner_apostrophes_in_a_quoted_value_are_still_masked():
    assert redact(f"Duplicate entry 'SEC'RET-{S}' for key 'k'") == "Duplicate entry ?"
    assert redact(f"bad 'it's {S}' here") == "bad ? here"


ORA_NUMBER = (
    "ORA-01722: unable to convert string value containing 'S' to a number: \n"
    f"ORA-03302: (ORA-01722 details) invalid string value: {S}\n"
    "Help: https://docs.oracle.com/error-help/db/ora-01722/"
)


def test_oracle_unquoted_invalid_string_value_is_masked_and_the_rest_kept():
    masked = redact(ORA_NUMBER)
    assert S not in masked
    assert masked.splitlines()[0].startswith("ORA-01722: unable to convert string value")
    assert "ORA-03302: (ORA-01722 details) invalid string value: ?" in masked
    assert masked.endswith("Help: https://docs.oracle.com/error-help/db/ora-01722/")


@pytest.mark.parametrize(
    "message, expected",
    [
        (f"invalid number: {S}", "invalid number: ?"),
        (f"invalid value: {S} here", "invalid value: ?"),
        (f"bad value: {S}", "bad value: ?"),
        (f"oops: value {S}", "oops: value ?"),
        (f"The duplicate key value is {S}", "The duplicate key value is ?"),
        (
            f"ORA-00001: x\nORA-03302: (ORA-00001 details) invalid number: {S}",
            "ORA-00001: x\nORA-03302: (ORA-00001 details) invalid number: ?",
        ),
    ],
)
def test_unquoted_value_tails_are_masked(message, expected):
    assert redact(message) == expected


@pytest.mark.parametrize(
    "message, expected",
    [
        (f"ORA-01722: custom detail: {S}", "ORA-01722: custom detail: ?"),
        (
            f"ORA-06502: PL/SQL: numeric or value error: {S}",
            "ORA-06502: PL/SQL: numeric or value error: ?",
        ),
    ],
)
def test_an_unknown_oracle_tail_after_a_colon_is_masked(message, expected):
    assert redact(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "ORA-06502: PL/SQL: value or conversion error: character to number conversion error",
        "ORA-06502: PL/SQL: value or conversion error: character string buffer too small",
        "ORA-12899: value too large for column ? (actual: 60, maximum: 10)",
        "ORA-00001: unique constraint (APP.SYS_C1) violated on table APP.T columns (V)",
        "ORA-02290: check constraint (APP.SYS_C1) violated",
        "ORA-01858: A non-numeric character was found instead of a numeric character.",
        "ORA-12541: TNS:no listener",
        "ORA-06550: line 1, column 13:",
    ],
)
def test_known_oracle_texts_are_kept(message):
    assert redact(message) == message


@pytest.mark.parametrize(
    "message, expected",
    [
        (
            'ORA-01400: cannot insert NULL into ("APP"."T"."NN")',
            "ORA-01400: cannot insert NULL into (?)",
        ),
        (
            'ORA-12899: value too large for column "APP"."T"."V" (actual: 35, maximum: 10)',
            "ORA-12899: value too large for column ? (actual: 35, maximum: 10)",
        ),
        (
            "ORA-03301: (ORA-00001 details) row with column values (V:'dup') already exists",
            "ORA-03301: (ORA-00001 details) row with column values (V:?) already exists",
        ),
    ],
)
def test_oracle_quoted_identifiers_and_values_keep_their_masking(message, expected):
    assert redact(message) == expected


def test_oracle_invalid_identifier_after_a_masked_name_is_kept():
    assert redact('ORA-00904: "SECRET": invalid identifier') == "ORA-00904: ?: invalid identifier"


def test_oracle_user_raised_errors_are_kept_whatever_their_punctuation():
    colon = "ORA-20001: Order rejected: customer X is blocked"
    plain = "ORA-20001: Order rejected for customer X"
    assert redact(colon) == colon
    assert redact(plain) == plain
    assert redact("ORA-20999: a: b") == "ORA-20999: a: b"


def test_oracle_codes_just_outside_the_user_range_are_not_exempt():
    assert redact("ORA-19999: x: y") == "ORA-19999: x: ?"
    assert redact("ORA-21000: x: y") == "ORA-21000: x: ?"


def test_oracle_invalid_identifier_and_missing_table_are_fixed_phrases():
    assert redact("ORA-00904: T.COL: invalid identifier") == "ORA-00904: T.COL: invalid identifier"
    assert redact("ORA-00942: SCOTT.T: table or view does not exist") == (
        "ORA-00942: SCOTT.T: table or view does not exist"
    )


def test_text_after_an_already_masked_label_is_not_masked_again():
    assert redact('ORA-00999: "SECRET": some other detail') == "ORA-00999: ?: some other detail"

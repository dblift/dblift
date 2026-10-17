"""DuckDB lexical facts from docs/sql-parsing/duckdb.md."""

from dblift.core.sql_parser.lexical_spec import LexicalSpec, SegmentScriptRules

#: Code points from U+0080 on that an identifier may hold: every one except the engine's blanks.
_NON_BLANK = (
    r"\x80-\x9f\xa1-\u1fff\u200c-\u202e\u2030-\u205e\u2061-\u2fff\u3001-\ufefe\uff00-\U0010ffff"
)

DUCKDB_RULES = SegmentScriptRules(
    # ASCII blanks, then U+00A0, U+2000 to U+200B, U+202F, U+205F, U+2060, U+3000 and U+FEFF.
    blanks=(
        " \t\n\f\r\u00a0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u200b"
        "\u202f\u205f\u2060\u3000\ufeff"
    ),
    text_blanks=" \t\n\f\r",
    word=rf"[A-Za-z_{_NON_BLANK}][A-Za-z0-9_${_NON_BLANK}]*",
    number=r"[0-9][0-9A-Za-z_]*",
    escape_letters="Ee",
    dollar_tag=rf"\$(?:[A-Za-z_{_NON_BLANK}][A-Za-z0-9_{_NON_BLANK}]*)?\$",
    parameter=rf"\$[A-Za-z0-9_{_NON_BLANK}]*",
    line_comment_ends="\r\n",
    command_prefix=".",
    refused_character="\x00",
    refused_character_name="NUL",
    refused_reason="the engine reads the script up to it and silently drops the rest",
)

DUCKDB_SPEC = LexicalSpec(
    name="duckdb",
    client_name="duckdb shell",
    nested_comments=True,
    leading_bom_is_blank=True,
    redaction_reads_engine=False,
    segment_script=DUCKDB_RULES,
)

"""MySQL lexical facts from docs/sql-parsing/mysql.md."""

from dblift.core.sql_parser.lexical_spec import DelimiterScriptRules, LexicalSpec, ProgramRules

MYSQL_PROGRAMS = ProgramRules(
    head_verbs=frozenset({"CREATE", "ALTER"}),
    fillers=frozenset({"OR", "REPLACE"}),
    create_only_fillers=frozenset({"AGGREGATE"}),
    definer="DEFINER",
    current_user="CURRENT_USER",
    kinds=frozenset({"PROCEDURE", "FUNCTION", "TRIGGER", "EVENT"}),
    alter_kinds=frozenset({"EVENT"}),
    body_open="BEGIN",
    body_close="END",
    block_words=frozenset({"IF", "LOOP", "WHILE", "REPEAT", "CASE", "FOR"}),
    case_word="CASE",
    statement_starts=frozenset({";", ":", "BEGIN", "THEN", "ELSE", "DO", "LOOP", "REPEAT"}),
)

_TERMINATED_COMMANDS = frozenset(
    {
        "EXIT", "QUIT", "STATUS", "HELP", "?", "REHASH", "PRINT", "NOPAGER", "NOTEE",
        "NOWARNING", "WARNINGS", "CLEAR", "RESETCONNECTION", "EDIT",
    }
)  # fmt: skip
_ARGUMENT_COMMANDS = frozenset(
    {
        "SOURCE", "CONNECT", "SYSTEM", "TEE", "CHARSET", "PROMPT", "PAGER",
        "QUERY_ATTRIBUTES", "SSL_SESSION_DATA_PRINT",
    }
)  # fmt: skip

MYSQL_RULES = DelimiterScriptRules(
    command="DELIMITER",
    initial=";",
    max_length=15,
    argument_quotes="'\"`",
    blanks=" \t\r\x0b\x0c",
    line_word=r"[A-Za-z_]+|\?",
    bare_commands=frozenset({"GO", "EGO"}),
    terminated_commands=_TERMINATED_COMMANDS,
    argument_commands=_ARGUMENT_COMMANDS,
    unterminated_commands=frozenset({"USE", "HELP", "?"}),
    statement_words=frozenset({"USE"}),
    exit_commands=frozenset({"EXIT", "QUIT"}),
    escape="\\",
    escape_text=frozenset({"N"}),
    string_quotes="'\"",
    hash_comment="#",
    dash_comment="--",
    executable_openers=("/*!",),
    hint_opener="/*+",
    hint_opening_line_only=True,
    word_part="A-Za-z0-9_$\u0080-\U0010ffff",
    qualifiers="@.",
    session_mode="NO_BACKSLASH_ESCAPES",
    session_mode_verbs=("SET", "PREPARE"),
    program=MYSQL_PROGRAMS,
)

MYSQL_SPEC = LexicalSpec(
    name="mysql",
    client_name="mysql",
    quoted_identifier="`",
    quoted_identifier_escape=False,
    string_quote_doubling=False,
    plain_string_escapes=True,
    leading_bom_is_blank=True,
    redaction_reads_engine=False,
    delimiter_script=MYSQL_RULES,
)

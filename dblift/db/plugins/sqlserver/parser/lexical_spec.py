"""SQL Server lexical facts from docs/sql-parsing/sqlserver.md."""

from dblift.core.sql_parser.lexical_spec import (
    BatchScriptRules,
    DivisionRules,
    HeadStep,
    LexicalSpec,
)

_ROUTINES = (("PROCEDURE",), ("PROC",), ("TRIGGER",), ("FUNCTION",))

_DIVISION = DivisionRules(
    routine_heads=(
        (HeadStep((("CREATE",), ("ALTER",))), HeadStep(_ROUTINES)),
        (
            HeadStep((("CREATE",),)),
            HeadStep((("OR", "ALTER"), ("OR", "REPLACE"))),
            HeadStep(_ROUTINES),
        ),
    ),
    block_open="BEGIN",
    block_open_exempt=frozenset({"TRAN", "TRANSACTION", "DISTRIBUTED", "CONVERSATION", "DIALOG"}),
    case_word="CASE",
    block_close="END",
    split_heads=frozenset({"CREATE", "ALTER", "DROP", "TRUNCATE"}),
    clause_exemptions=(
        (("ALTER", "TABLE"), (("ALTER", "COLUMN"), ("DROP", "COLUMN"), ("DROP", "CONSTRAINT"))),
    ),
)

SQLSERVER_BATCHES = BatchScriptRules(
    separator="GO",
    word_start="A-Za-z_@#$",
    word_part="A-Za-z0-9_@#$",
    bare_commands=("EXIT", "QUIT", "RESET", "ED"),
    colon_commands=(
        "setvar",
        "r",
        "connect",
        "on",
        "exit",
        "quit",
        "list",
        "listvar",
        "error",
        "out",
        "perftrace",
        "help",
        "serverlist",
        "xml",
        "reset",
        "ed",
    ),
    shell_prefix="!!",
    command_followers=frozenset(" \t\r-=(['/"),
    unmeasured_blanks=frozenset("\x0b\x0c"),
    tail_comment="--",
    max_repeat=1_000_000,
    lone_cr_words=("GO",),
    variable_reference=("$(", ")"),
    blanks=" \t\r",
    ignored_in_code=";",
    division=_DIVISION,
)

SQLSERVER_SPEC = LexicalSpec(
    name="sqlserver",
    client_name="sqlcmd",
    nested_comments=False,
    quoted_identifier='"',
    bracket_identifier=("[", "]"),
    leading_bom_is_blank=True,
    silent_unclaimed=True,
    placeholder_open=None,
    batch_script=SQLSERVER_BATCHES,
)

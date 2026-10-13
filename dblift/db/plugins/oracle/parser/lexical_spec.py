"""Oracle lexical facts from docs/sql-parsing/oracle.md."""

from typing import Tuple

from dblift.core.sql_parser.lexical_spec import (
    ClientScriptRules,
    DirectiveAction,
    DirectiveRule,
    HeadPattern,
    HeadStep,
    LexicalSpec,
)

_BLOCK = (("DECLARE",), ("BEGIN",))
_UNITS = tuple(
    (word,) for word in ("FUNCTION", "PROCEDURE", "PACKAGE", "TYPE", "TRIGGER", "LIBRARY")
)
_CREATE = HeadStep((("CREATE",),))
_OR_REPLACE = HeadStep((("OR", "REPLACE"),), optional=True)
_AND = HeadStep((("AND", "COMPILE"), ("AND", "RESOLVE")), optional=True)
_NOFORCE = HeadStep((("NOFORCE",),), optional=True)

# The shapes of a PL/SQL unit head (spec section 5), matched in this order.
_UNIT_HEADS: Tuple[HeadPattern, ...] = (
    (HeadStep(_BLOCK),),
    (
        HeadStep((("<",),)),
        HeadStep((("<",),)),
        HeadStep((("*",),)),
        HeadStep(((">",),)),
        HeadStep(((">",),)),
        HeadStep(_BLOCK),
    ),
    (
        _CREATE,
        _OR_REPLACE,
        HeadStep((("EDITIONABLE",), ("NONEDITIONABLE",)), optional=True),
        HeadStep(_UNITS),
    ),
    (
        _CREATE,
        _OR_REPLACE,
        _AND,
        _NOFORCE,
        HeadStep((("JAVA", "SOURCE"), ("JAVA", "CLASS"), ("JAVA", "RESOURCE"))),
    ),
    (
        _CREATE,
        _OR_REPLACE,
        _AND,
        _NOFORCE,
        HeadStep((("IF", "NOT", "EXISTS"),), optional=True),
        HeadStep((("MLE", "MODULE"),)),
    ),
)

_DROP = DirectiveAction.DROP_RECORD
_POLICY = DirectiveAction.RECORD_POLICY
_DEFINE = DirectiveAction.DEFINE
_EXEC = DirectiveAction.EXEC
_EXIT = DirectiveAction.EXIT
_REJECT = DirectiveAction.REJECT

# One-word client commands (spec section 6), first match wins: (word, minimum abbreviation, action).
_DIRECTIVES: Tuple[DirectiveRule, ...] = (
    DirectiveRule("SHOW", 3, _DROP),
    DirectiveRule("SPOOL", 3, _DROP),
    DirectiveRule("PROMPT", 3, _DROP, free_text=True),
    DirectiveRule("REMARK", 3, _DROP, free_text=True),
    DirectiveRule("COLUMN", 3, _DROP),
    DirectiveRule("TTITLE", 3, _DROP),
    DirectiveRule("BTITLE", 3, _DROP),
    DirectiveRule("REPHEADER", 4, _DROP),
    DirectiveRule("REPFOOTER", 4, _DROP),
    DirectiveRule("BREAK", 3, _DROP),
    DirectiveRule("COMPUTE", 4, _DROP),
    DirectiveRule("CLEAR", 2, _DROP),
    DirectiveRule("TIMING", 4, _DROP),
    DirectiveRule("VARIABLE", 3, _DROP),
    DirectiveRule("PRINT", 3, _DROP),
    DirectiveRule("DESCRIBE", 4, _DROP),
    DirectiveRule("DEFINE", 3, _DEFINE),
    DirectiveRule("UNDEFINE", 5, _DEFINE),
    DirectiveRule("EXECUTE", 4, _EXEC),
    DirectiveRule("EXIT", 4, _EXIT),
    DirectiveRule("QUIT", 4, _EXIT),
    DirectiveRule("START", 3, _REJECT),
    DirectiveRule("HOST", 2, _REJECT),
    DirectiveRule("ACCEPT", 3, _REJECT),
    DirectiveRule("PAUSE", 3, _REJECT),
    DirectiveRule("CONNECT", 4, _REJECT),
    DirectiveRule("DISCONNECT", 4, _REJECT),
    DirectiveRule("PASSWORD", 5, _REJECT),
)

# SET options the splitter does not drop; any other SET option is dropped and recorded.
_SET_OPTIONS: Tuple[DirectiveRule, ...] = (
    DirectiveRule("SERVEROUTPUT", 9, _POLICY),
    DirectiveRule("DEFINE", 3, _DEFINE),
    DirectiveRule("SCAN", 4, _DEFINE),
    DirectiveRule("ESCAPE", 3, _REJECT),
    DirectiveRule("CONCAT", 3, _REJECT),
    DirectiveRule("SQLTERMINATOR", 4, _REJECT),
    DirectiveRule("BLOCKTERMINATOR", 3, _REJECT),
    DirectiveRule("SQLBLANKLINES", 4, _REJECT),
    DirectiveRule("SQLPREFIX", 6, _REJECT),
    DirectiveRule("CMDSEP", 4, _REJECT),
)

ORACLE_SPEC = LexicalSpec(
    name="oracle",
    client_name="SQL*Plus",
    terminator_respects_parens=True,
    alternative_quotes=("q'", "nq'"),
    alternative_quote_pairs=(("[", "]"), ("{", "}"), ("<", ">"), ("(", ")")),
    quoted_identifier_escape=False,
    parameter_prefix="",
    placeholder_open=None,
    client_script=ClientScriptRules(
        unit_heads=_UNIT_HEADS,
        max_head_tokens=8,
        line_terminator="/",
        discard_line=".",
        directives=_DIRECTIVES,
        set_command=("SET", 3),
        set_options=_SET_OPTIONS,
        set_sql_words=frozenset({"ROLE", "TRANSACTION", "CONSTRAINT", "CONSTRAINTS"}),
        prefix_directives=(("@@", "@@"), ("@", "@"), ("!", "!")),
        sql_follow_words=(("CONNECT", "TO"),),
        whenever_command="WHENEVER",
        whenever=(("SQLERROR", _POLICY), ("OSERROR", _DROP)),
        whenever_min_abbrev=8,
        policy_actions=("EXIT", "CONTINUE"),
        slash_record_ends_at_line_end=True,
        refuse_terminator_text_on_empty_buffer=True,
        tail_record_ends_at_last_token=True,
        policy_projection=("WHENEVER SQLERROR",),
        substitution_char="&",
        exec_wrapper=("BEGIN ", "; END;"),
    ),
)

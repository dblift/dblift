"""Oracle lexical facts from docs/sql-parsing/oracle.md."""

from typing import Tuple

from dblift.core.sql_parser.lexical_spec import (
    ClientScriptRules,
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
        directives=(),
        set_options=(),
        set_sql_words=frozenset(),
        prefix_directives=(),
        sql_follow_words=(),
        whenever=(),
        whenever_min_abbrev=8,
        policy_actions=("EXIT", "CONTINUE"),
        slash_record_ends_at_line_end=True,
        tail_record_ends_at_last_token=True,
        policy_projection=("WHENEVER SQLERROR",),
        substitution_char="&",
        exec_wrapper=("BEGIN ", "; END;"),
    ),
)

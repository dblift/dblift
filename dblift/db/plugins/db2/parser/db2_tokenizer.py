"""Db2 tokenizer settings that literal masking reads."""

from dblift.core.sql_parser.base_tokenizer import BaseTokenizer


class DB2NestingCommentTokenizer(BaseTokenizer):
    """Carries only the flag: Db2 nests ``/* ... */`` (checked with the CLP and ``ibm_db``).

    Literal masking reads it; the splitter does not.
    """

    NESTED_BLOCK_COMMENTS = True

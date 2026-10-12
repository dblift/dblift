"""Plugin-owned facts consumed by the shared lexical scanner."""

from dataclasses import dataclass
from typing import FrozenSet, Tuple


@dataclass(frozen=True)
class LexicalSpec:
    """Only lexical rules; no parser callbacks or alternative implementations."""

    name: str
    client_name: str = "SQL client"
    nested_comments: bool = False
    quoted_identifier: str = '"'
    escape_prefixes: Tuple[str, ...] = ()
    plain_string_escapes: bool = False
    dollar_quotes: bool = False
    meta_prefix: str = ""
    safe_meta_commands: FrozenSet[str] = frozenset()
    combine_terminator: str = ""
    copy_from_stdin: bool = False
    terminator_respects_parens: bool = False
    routine_heads: Tuple[Tuple[str, ...], ...] = ()
    block_opener: Tuple[str, str] = ("", "")
    nested_block_keywords: FrozenSet[str] = frozenset()
    block_closer: str = ""

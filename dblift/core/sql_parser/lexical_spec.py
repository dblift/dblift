"""Plugin-owned facts consumed by the shared lexical scanner."""

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional, Tuple


class DirectiveAction(Enum):
    """What the splitter does with a client directive line."""

    DROP_RECORD = "drop_record"
    DEFINE = "define"
    EXEC = "exec"
    EXIT = "exit"
    REJECT = "reject"


@dataclass(frozen=True)
class DirectiveRule:
    """A one-word client command, its documented minimum abbreviation and its action."""

    word: str
    min_abbrev: int
    action: DirectiveAction
    free_text: bool = False


@dataclass(frozen=True)
class HeadStep:
    """One step of a unit-head pattern: alternative word sequences, ``*`` matches any token.

    An optional step is skipped only when the next token is no alternative's first
    word; a first-word match followed by a mismatch fails the pattern.
    """

    alternatives: Tuple[Tuple[str, ...], ...]
    optional: bool = False


HeadPattern = Tuple[HeadStep, ...]


@dataclass(frozen=True)
class ClientScriptRules:
    """Line-oriented client script rules (a client that reads a script line by line)."""

    unit_heads: Tuple[HeadPattern, ...]
    max_head_tokens: int
    line_terminator: str
    discard_line: str
    directives: Tuple[DirectiveRule, ...]
    set_command: Tuple[str, int]
    set_options: Tuple[DirectiveRule, ...]
    set_sql_words: FrozenSet[str]
    prefix_directives: Tuple[Tuple[str, str], ...]
    sql_follow_words: Tuple[Tuple[str, str], ...]
    whenever_command: str
    whenever: Tuple[Tuple[str, DirectiveAction], ...]
    whenever_min_abbrev: int
    policy_actions: Tuple[str, ...]
    slash_record_ends_at_line_end: bool
    refuse_terminator_text_on_empty_buffer: bool
    tail_record_ends_at_last_token: bool
    policy_projection: Tuple[str, ...]
    substitution_char: str
    exec_wrapper: Tuple[str, str]


@dataclass(frozen=True)
class DivisionRules:
    """How one batch is divided into the statements analysis reads (not what the client sends)."""

    routine_heads: Tuple[HeadPattern, ...]
    block_open: str
    block_open_exempt: FrozenSet[str]
    case_word: str
    block_close: str
    split_heads: FrozenSet[str]
    clause_exemptions: Tuple[Tuple[Tuple[str, str], Tuple[Tuple[str, str], ...]], ...]


@dataclass(frozen=True)
class BatchScriptRules:
    """A client that cuts a script into batches at separator lines."""

    separator: str
    word_start: str
    word_part: str
    bare_commands: Tuple[str, ...]
    colon_commands: Tuple[str, ...]
    shell_prefix: str
    command_followers: FrozenSet[str]
    unmeasured_blanks: FrozenSet[str]
    tail_comment: str
    max_repeat: int
    lone_cr_words: Tuple[str, ...]
    variable_reference: Tuple[str, str]
    blanks: str
    ignored_in_code: str
    division: DivisionRules


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
    sqlite_shell: bool = False
    completion_table: Tuple[Tuple[int, ...], ...] = ()
    alternative_quotes: Tuple[str, ...] = ()
    alternative_quote_pairs: Tuple[Tuple[str, str], ...] = ()
    quoted_identifier_escape: bool = True
    parameter_prefix: str = "$"
    placeholder_open: Optional[str] = "${"
    client_script: Optional[ClientScriptRules] = None
    bracket_identifier: Tuple[str, ...] = ()
    leading_bom_is_blank: bool = False
    silent_unclaimed: bool = False
    batch_script: Optional[BatchScriptRules] = None

    def __post_init__(self) -> None:
        """A client reads a script by lines or by batches, never both."""
        if self.client_script is not None and self.batch_script is not None:
            raise ValueError("client_script and batch_script are mutually exclusive")

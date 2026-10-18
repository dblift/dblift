"""Plugin-owned facts consumed by the shared lexical scanner."""

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional, Tuple

#: A byte order mark at the start of a script.
BOM = "\ufeff"


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
    separator_followers: FrozenSet[str]
    unmeasured_blanks: FrozenSet[str]
    tail_comment: str
    max_repeat: int
    lone_cr_words: Tuple[str, ...]
    variable_reference: Tuple[str, str]
    blanks: str
    ignored_in_code: str
    division: DivisionRules


@dataclass(frozen=True)
class ProgramRules:
    """Statements whose ``BEGIN ... END`` body a ``;`` does not end (beyond the client)."""

    head_verbs: FrozenSet[str]
    create_verb: str
    fillers: FrozenSet[str]
    create_only_fillers: FrozenSet[str]
    definer: str
    current_user: str
    kinds: FrozenSet[str]
    alter_kinds: FrozenSet[str]
    body_open: str
    body_close: str
    block_words: FrozenSet[str]
    case_word: str
    statement_starts: FrozenSet[str]


@dataclass(frozen=True)
class DelimiterScriptRules:
    """A client that reads a script line by line and ends a statement at a delimiter the script changes.

    It reads a CRLF pair as LF and refuses a NUL byte (not fields: every such client does). ``initial`` is read for
    the starting delimiter and for every place a plain ``;`` is meant: the terminator run of a command line, fragments,
    and the stored-program condition (the extension runs only under the initial delimiter).
    """

    command: str
    initial: str
    max_length: int
    argument_quotes: str
    blanks: str
    line_word: str
    bare_commands: FrozenSet[str]
    terminated_commands: FrozenSet[str]
    argument_commands: FrozenSet[str]
    unterminated_commands: FrozenSet[str]
    statement_words: FrozenSet[str]
    exit_commands: FrozenSet[str]
    escape: str
    escape_text: FrozenSet[str]
    string_quotes: str
    hash_comment: str
    dash_comment: str
    executable_openers: Tuple[str, ...]
    hint_opener: str
    hint_opening_line_only: bool
    word_part: str
    qualifiers: str
    session_mode: str
    session_mode_verbs: Tuple[str, ...]
    program: ProgramRules


@dataclass(frozen=True)
class RoutineRules:
    """Statements whose ``BEGIN ... END`` body a terminator at a line end does not end."""

    create_verb: str
    replace_word: str
    kinds: FrozenSet[str]
    package_kind: str
    package_openers: FrozenSet[str]
    alter_verb: str
    alter_kinds: FrozenSet[str]
    body_open: str
    depth_words: FrozenSet[str]
    body_close: str
    end_qualifiers: FrozenSet[str]
    case_word: str


@dataclass(frozen=True)
class TerminatorScriptRules:
    """A client that reads a script line by line and ends a statement at a line whose last non-blank
    characters are the active terminator.

    The CR of a CRLF pair is not part of its line and a lone CR is a character (not fields: no such
    client differs). ``initial`` is read for the starting terminator, for the stray-terminator
    character and for the ``terminator then comment`` ending, which applies under it only.
    """

    initial: str
    blanks: str
    directive_name: str
    directive: str
    directive_value: str
    directive_syntax: str
    line_comment: str
    comment_block: str
    word: str
    leading_word: str
    command_prefixes: str
    command_words: FrozenSet[str]
    command_phrases: FrozenSet[Tuple[str, ...]]
    sql_phrases: FrozenSet[Tuple[str, ...]]
    epilogue_words: FrozenSet[Tuple[str, ...]]
    epilogue: str
    driver_name: str
    routine: RoutineRules


@dataclass(frozen=True)
class BlankPassRules:
    """The pass an engine runs over the whole script before it parses, replacing each blank by a space.

    The pass skips quoted text (a doubled quote stays inside; a backslash means nothing to it), a
    ``comment`` to the end of its line and a dollar-quoted string, and knows no other comment. A
    ``dollar`` followed by tag characters and a second ``dollar`` opens a string closed by the same
    tag, searched from the opener's last ``dollar``; the closing tag's last ``dollar`` may begin the
    next tag. A tag that is never closed ends the pass, and so does a quote that is never closed:
    from there every blank is kept, and the parser reads it as a word character. A ``dollar`` followed
    by tag characters but no second ``dollar`` skips that run of characters, blanks included, and
    reads on from the character that ended it. A tag starts with a ``tag_first`` character or any
    non-ASCII one and goes on with ``tag_rest`` characters or non-ASCII ones.

    ``word_part`` is what a word may hold where blanks were replaced, ``kept_word_part`` where they were kept.
    """

    quotes: str
    comment: str
    dollar: str
    tag_first: str
    tag_rest: str
    word_part: str
    kept_word_part: str


@dataclass(frozen=True)
class SegmentScriptRules:
    """A script cut at each ``;`` outside lexemes; a line that starts with the client's command prefix
    while no statement text is pending is a client command, refused.

    ``word``, ``number``, ``dollar_tag`` and ``parameter`` are regular expressions read at the
    cursor. ``blanks`` are skipped between tokens; ``text_blanks`` are stripped from a record's ends
    when records are assembled from the tokens.
    A word ending in an ``escape_letters`` character (alone, or after characters ``str.isdigit()``
    accepts) that touches a quote opens an escape string. A line comment ends at the first of
    ``line_comment_ends``. ``refused_character`` is refused anywhere, before any other reading.
    """

    blanks: str
    text_blanks: str
    word: str
    number: str
    escape_letters: str
    dollar_tag: str
    parameter: str
    line_comment_ends: str
    command_prefix: str
    refused_character: str
    refused_character_name: str
    refused_reason: str
    blank_pass: Optional[BlankPassRules] = None


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
    #: Whether literal masking reads the text through this specification. False keeps the dialect's
    #: own tokenizer: SQL Server masking reads comments as the server does, which differs from
    #: the client's batch reading.
    redaction_reads_engine: bool = True
    delimiter_script: Optional[DelimiterScriptRules] = None
    #: False: a doubled string quote closes the literal and opens the next, as a client does.
    string_quote_doubling: bool = True
    terminator_script: Optional[TerminatorScriptRules] = None
    segment_script: Optional[SegmentScriptRules] = None

    def __post_init__(self) -> None:
        """A client reads a script by lines, batches, a delimiter, terminator lines or segments."""
        rules = (
            self.client_script,
            self.batch_script,
            self.delimiter_script,
            self.terminator_script,
            self.segment_script,
        )
        if sum(rule is not None for rule in rules) > 1:
            raise ValueError(
                "client_script, batch_script, delimiter_script, terminator_script and "
                "segment_script are mutually exclusive"
            )
        if self.segment_script is not None and self.sqlite_shell:
            raise ValueError("segment_script and sqlite_shell are mutually exclusive")

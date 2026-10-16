"""The stored-program tracker of a statement: whether a ``;`` ends it."""

from dblift.core.sql_parser.lexical_spec import ProgramRules


class ProgramBody:
    """Fed the words and punctuation of one statement outside strings and comments."""

    def __init__(self, rules: ProgramRules) -> None:
        """Start with nothing read."""
        self.rules = rules
        self.reset()

    def reset(self) -> None:
        """A new statement."""
        self.is_program = False

    @property
    def open(self) -> bool:
        """True inside a body: a ``;`` here does not end the statement."""
        return False

    def word(self, word: str) -> None:
        """A word, upper-cased, outside lexemes and comments and not qualified."""

    def quoted(self) -> None:
        """A string, a quoted name or a qualified word."""

    def punct(self, char: str) -> None:
        """Any other code character."""

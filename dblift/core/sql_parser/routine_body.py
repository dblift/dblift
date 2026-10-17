"""What one statement of a terminator script has shown so far: tokens and a stray terminator."""

from dblift.core.sql_parser.lexical_spec import RoutineRules


class RoutineBody:
    """The words and symbols of the statement being read, counted the way the client counts them."""

    def __init__(self, rules: RoutineRules) -> None:
        """Start a statement: nothing read yet."""
        self.rules = rules
        self.tokens = 0
        self.stray = False
        self.semi_at = -1
        self._semicolon = False

    @property
    def code(self) -> bool:
        """Whether anything but terminators and comments was read."""
        return self.tokens > 0

    @property
    def inside(self) -> bool:
        """Whether a routine body is open."""
        return False

    def literal(self) -> None:
        """A string or a quoted identifier."""
        self._token()

    def word(self, upper: str) -> None:
        """A word, in upper case."""
        self._token()

    def symbol(self, char: str) -> None:
        """Any other character that is not a blank."""
        self.settle()
        self._token()

    def semicolon(self, column: int) -> None:
        """The statement terminator character, at ``column`` of the text being read."""
        self.settle()
        self._semicolon, self.semi_at = True, column

    def settle(self) -> None:
        """A token that is not a word settles a pending ``END``."""

    def _token(self) -> None:
        self.tokens += 1
        if self._semicolon:
            self.stray = True

"""What one statement of a terminator script has shown so far: its head, its body and its tokens."""

from typing import List, Optional

from dblift.core.sql_parser.lexical_spec import RoutineRules


class RoutineBody:
    """The words and symbols of the statement being read, and whether a routine body is open.

    A body opens at the first body word outside parentheses (a package body at its first opener) of
    a routine statement, or at the first word of a compound statement, and closes at the ``END``
    that matches it: ``BEGIN`` and ``CASE`` open a level, ``END`` closes one, and ``END`` followed
    by a qualifier word closes nothing it counted.
    """

    def __init__(self, rules: RoutineRules) -> None:
        """Start a statement: nothing read yet."""
        self.rules = rules
        self.tokens = 0
        self.stray = False
        self.semi_at = -1
        self._semicolon = False
        self._words: List[str] = []
        self._routine: Optional[bool] = None
        self._package = False
        self._opened = False
        self._depth = 0
        self._parens = 0
        self._pending_end = False

    @property
    def code(self) -> bool:
        """Whether anything but terminators and comments was read."""
        return self.tokens > 0

    @property
    def inside(self) -> bool:
        """Whether a routine body is open."""
        return self._opened and self._depth > 0

    def literal(self) -> None:
        """A string or a quoted identifier."""
        self._token()

    def word(self, upper: str) -> None:
        """A word, in upper case."""
        self._token()
        rules = self.rules
        if self._pending_end:
            self._pending_end = False
            if upper in rules.end_qualifiers:
                return
            self._depth -= 1
            if upper == rules.case_word:
                return
        if self._routine is None:
            self._head(upper)
        elif self._routine and not self._opened:
            openers = rules.package_openers if self._package else frozenset({rules.body_open})
            if upper in openers and self._parens == 0:
                self._opened, self._depth = True, 1
        elif self._routine and self._depth > 0:
            if upper in rules.depth_words:
                self._depth += 1
            elif upper == rules.body_close:
                self._pending_end = True

    def symbol(self, char: str) -> None:
        """Any other character that is not a blank."""
        self.settle()
        self._token()
        self._parens += (char == "(") - (char == ")")

    def semicolon(self, column: int) -> None:
        """The statement terminator character, at ``column`` of the text being read."""
        self.settle()
        if not self.inside:
            self._semicolon, self.semi_at = True, column

    def settle(self) -> None:
        """A token that is not a word settles a pending ``END``: it closes a level."""
        if self._pending_end:
            self._pending_end = False
            self._depth -= 1

    def _token(self) -> None:
        self.tokens += 1
        if self._semicolon:
            self.stray = True

    def _head(self, word: str) -> None:
        rules = self.rules
        self._words.append(word)
        first = self._words[0]
        if first == rules.body_open:
            self._routine, self._opened, self._depth = True, True, 1
        elif first == rules.create_verb:
            target = 3 if self._words[1:2] == [rules.replace_word] else 1
            if len(self._words) > target:
                self._package = self._words[target] == rules.package_kind
                self._routine = self._package or self._words[target] in rules.kinds
        elif first == rules.alter_verb:
            if len(self._words) > 1:
                self._routine = self._words[1] in rules.alter_kinds
        else:
            self._routine = False

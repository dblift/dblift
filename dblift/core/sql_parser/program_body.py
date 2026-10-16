"""The stored-program tracker of a statement: whether a ``;`` ends it."""

from typing import List

from dblift.core.sql_parser.lexical_spec import ProgramRules


class ProgramBody:
    """Whether the statement being read is a stored program whose BEGIN ... END body stays whole.

    Fed the words and punctuation of the statement outside strings and comments. The head is
    ``CREATE [OR REPLACE] [DEFINER = user@host] [AGGREGATE] PROCEDURE|FUNCTION|TRIGGER|EVENT`` or
    ``ALTER [DEFINER = ...] EVENT``; the body opens at the first ``BEGIN`` at parenthesis depth 0.
    """

    def __init__(self, rules: ProgramRules) -> None:
        """Start with nothing read."""
        self.rules = rules
        self.reset()

    def reset(self) -> None:
        """A new statement."""
        self.head = "start"
        self.verb = ""
        self.is_program = False
        self.stack: List[str] = []
        self.depth = 0
        self.prev = ""
        self.after_end = False

    @property
    def open(self) -> bool:
        """True inside a body: a ``;`` here does not end the statement."""
        return self.is_program and bool(self.stack)

    def word(self, word: str) -> None:
        """A word, upper-cased, outside lexemes and comments and not qualified."""
        if not self.is_program:
            self._head("word", word)
        else:
            self._body(word)
        self.prev = word

    def quoted(self) -> None:
        """A string, a quoted name or a qualified word."""
        if not self.is_program:
            self._head("quoted", "")
        self.prev = "'"

    def punct(self, char: str) -> None:
        """Any other code character; parentheses track the depth."""
        if not self.is_program:
            self._head("punct", char)
        else:
            if char == "(":
                self.depth += 1
            elif char == ")" and self.depth:
                self.depth -= 1
            self.after_end = False
        self.prev = char

    def _head(self, kind: str, value: str) -> None:
        rules = self.rules
        head = self.head
        if head == "done":
            return
        if head == "start":
            if kind == "word" and value in rules.head_verbs:
                self.verb, self.head = value, "verb"
            else:
                self.head = "done"
        elif head == "definer_eq":
            self.head = "definer_user" if (kind, value) == ("punct", "=") else "done"
        elif head == "definer_user":
            if kind == "word" and value == rules.current_user:
                self.head = "definer_current"
            elif kind in ("word", "quoted"):
                self.head = "definer_at"
            else:
                self.head = "done"
        elif head == "definer_current":
            if (kind, value) == ("punct", "("):
                self.head = "definer_close"
            else:
                self.head = "verb"
                self._head(kind, value)
        elif head == "definer_close":
            self.head = "verb" if (kind, value) == ("punct", ")") else "done"
        elif head == "definer_at":
            if (kind, value) == ("punct", "@"):
                self.head = "definer_host"
            else:
                self.head = "verb"
                self._head(kind, value)
        elif head == "definer_host":
            self.head = "verb" if kind in ("word", "quoted") else "done"
        else:  # "verb": the words between the head verb and the kind of object
            creating = self.verb == rules.create_verb
            if kind != "word":
                self.head = "done"
            elif value in rules.fillers or (value in rules.create_only_fillers and creating):
                return
            elif value == rules.definer:
                self.head = "definer_eq"
            elif value in rules.kinds and (creating or value in rules.alter_kinds):
                self.is_program, self.head = True, "done"
            else:
                self.head = "done"

    def _body(self, word: str) -> None:
        rules = self.rules
        stack = self.stack
        after_end, self.after_end = self.after_end, False
        if word == rules.body_close:
            if stack:
                stack.pop()
            self.after_end = True
            return
        if after_end and word in rules.block_words:
            return  # END IF, END LOOP, END WHILE, END REPEAT, END CASE, END FOR
        if not stack:
            if word == rules.body_open and self.depth == 0:
                stack.append(rules.body_open)
            return
        if word == rules.body_open and self.depth == 0:
            stack.append(rules.body_open)
        elif word == rules.case_word:
            statement = (
                self.depth == 0 and self.prev in rules.statement_starts and stack[-1] != "CASE_EXPR"
            )
            stack.append(rules.case_word if statement else "CASE_EXPR")
        elif (
            word in rules.block_words
            and self.depth == 0
            and self.prev in rules.statement_starts
            and stack[-1] != "CASE_EXPR"
        ):
            stack.append(word)

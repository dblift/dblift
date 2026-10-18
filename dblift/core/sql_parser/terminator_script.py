"""The client's reading of one terminator script: lines, terminator, records, refusals."""

import re
from dataclasses import replace
from typing import List, Mapping, Optional, Sequence, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_spec import TerminatorScriptRules
from dblift.core.sql_parser.routine_body import RoutineBody
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.terminator_lines import Line, read_lines
from dblift.core.sql_parser.tokens import Token, TokenType

_COMMENT_OPENER = "/*"
_COMMENT_CLOSER = "*/"


class TerminatorScript:
    """One script cut by lines, read from the lexemes found in its masked text."""

    def __init__(
        self,
        rules: TerminatorScriptRules,
        client_name: str,
        text: str,
        origin: int,
        text_blanks: str,
    ) -> None:
        """Classify the lines of ``text``: the script without its byte order mark (``origin`` long)."""
        self.rules = rules
        self.text_blanks = text_blanks
        self.client_name = client_name
        self.text = text
        self.origin = origin
        self.lines, self.masked, self.malformed = read_lines(rules, text)

    def assemble(
        self, tokens: Sequence[Token], marks: Mapping[int, Tuple[int, bool]], open_lexeme: int
    ) -> List[Statement]:
        """The records, or the refusal, for ``tokens`` read from ``masked``.

        ``marks`` gives the comment depth at each line end inside a comment; ``open_lexeme`` is
        where a lexeme left open at the end of the script begins (-1: none). Nothing is kept
        between calls.
        """
        return _Walk(self, tokens, marks, open_lexeme).run()


class _Walk:
    """One pass over the lines, in order, with one cursor into the tokens."""

    def __init__(
        self,
        script: TerminatorScript,
        tokens: Sequence[Token],
        marks: Mapping[int, Tuple[int, bool]],
        open_lexeme: int,
    ) -> None:
        self.script = script
        self.rules = script.rules
        self.text_blanks = script.text_blanks
        self.client = script.client_name
        self.text = script.text
        self.tokens = tokens
        self.marks = marks
        self.open_lexeme = open_lexeme
        self.leading = re.compile(self.rules.leading_word)
        self.epilogue = re.compile(self.rules.epilogue)
        self.k = 0
        self.records: List[Statement] = []
        self.epilogues: List[bool] = []
        self.segs: List[Tuple[int, int]] = []
        self.body = RoutineBody(self.rules.routine)
        self.start = self.unit_start = self.line_end = 0
        self.stray_line = self.last_code = self.block_line = 0
        self.block_code = False
        self.in_string = self.in_comment = False

    # --- the pass ---------------------------------------------------------------------

    def run(self) -> List[Statement]:
        """Walk the lines, then the end of the script, then the epilogue."""
        for line in self.script.lines:
            self.line_end = line.end
            self._line(line)
        if self.segs:
            self.body.settle()
            self._skip_to(len(self.text))
            if self._state(len(self.text))[1]:
                raise UnsafeStatementSplitError(
                    f"the block comment opened on line {self.block_line} is not closed before "
                    "the end of the script: the statements inside it would be dropped"
                )
            if self.body.inside:
                raise UnsafeStatementSplitError(
                    f"the routine body starting on line {self.start} is not closed "
                    "before the end of the script"
                )
            self._end(None, self.last_code)
        return self._epilogue()

    def _line(self, line: Line) -> None:
        if line.kind == "directive":
            self._directive(line)
        elif line.kind == "comment":
            if self.segs:
                self._append(line)
                self._feed(line.start, line.start + len(line.text), line.number)
        elif line.kind == "block":
            raise UnsupportedMetaCommandError(
                f"{self.client} comment block {self.rules.comment_block!r} on line {line.number}: "
                f"the {self.client} skips it, dblift does not run {self.client} input syntax"
            )
        else:
            self._code(line)

    def _code(self, line: Line) -> None:
        if not self.segs:
            if line.kind == "blank":
                return
            self.start, self.body = line.number, RoutineBody(self.rules.routine)
            self.unit_start = line.start + len(line.text) - len(line.text.lstrip(self.rules.blanks))
            self.stray_line = self.last_code = 0
        self._append(line)
        if line.body_end >= 0:
            self._cut(line)
            return
        self._feed(line.start, line.start + len(line.text), line.number)
        if self._ends_before_a_comment(line):
            self.segs[-1] = (line.start, line.start + self.body.semi_at)
            self._end(line.terminator)

    def _append(self, line: Line) -> None:
        last = line.end - 1 if self.text[line.end - 1] == "\n" else line.end
        self.segs.append((line.start, last))

    def _directive(self, line: Line) -> None:
        rules = self.rules
        if self.segs:
            if any(self._state(line.start)):
                raise UnsafeStatementSplitError(
                    f"{rules.directive_name} on line {line.number} stands inside a string, a "
                    f"quoted identifier or a comment: the {self.client} honours it there and cuts the "
                    "statement; close it first"
                )
        if self.script.malformed == line.number:
            raise UnsafeStatementSplitError(
                f"malformed {rules.directive_name} directive on line {line.number}: "
                f"expected {rules.directive_syntax}"
            )
        origin = self.script.origin
        first = line.start + len(line.text) - len(line.text.lstrip(rules.blanks))
        self.records.append(
            Statement(
                line.text.strip(),
                line.number,
                None,
                "directive",
                source_start=first + origin,
                source_end=line.end + origin,
            )
        )
        self.epilogues.append(False)

    def _cut(self, line: Line) -> None:
        """A line ending in the terminator ends the statement unless a lexeme or body is open."""
        end, terminator = line.body_end, line.terminator
        self._feed(line.start, end, line.number)
        if self._overlaps_a_comment_delimiter(end, terminator):
            raise UnsafeStatementSplitError(
                f"line {line.number} ends with {terminator!r}, which is also part of a comment "
                f"delimiter: the {self.client} cuts the statement there, the splitter cannot tell "
                "the two readings apart; put the comment on a line of its own"
            )
        self.body.settle()
        if self.in_string:
            raise UnsafeStatementSplitError(
                f"line {line.number} ends with {terminator!r} inside a string or a quoted "
                f"identifier: the {self.client} cuts the statement there and the server rejects "
                "both halves; close the literal before the end of the line"
            )
        if self.body.inside or self.in_comment:
            return  # a body is kept whole; a comment runs to its close, whatever its lines end with
        self.segs[-1] = (line.start, end)
        self._end(terminator)

    def _ends_before_a_comment(self, line: Line) -> bool:
        """The initial terminator followed only by comments on its line ends the statement there."""
        body, rules = self.body, self.rules
        if line.terminator != rules.initial or body.semi_at < 0 or body.stray or body.inside:
            return False
        if self.in_string or self.in_comment:
            return False
        rest = line.text[body.semi_at + 1 :].lstrip(rules.blanks)
        return rest.startswith((rules.line_comment, _COMMENT_OPENER))

    # --- lexeme state from the token cursor --------------------------------------------

    def _skip_to(self, position: int) -> None:
        tokens, k, size = self.tokens, self.k, len(self.tokens)
        while k < size and tokens[k].pos < position:
            k += 1
        self.k = k

    def _state(self, position: int) -> Tuple[bool, bool]:
        """(string or identifier open, block comment open) at ``position``, after token k - 1."""
        if self.k == 0:
            return False, False
        token = self.tokens[self.k - 1]
        end = token.pos + len(token.text)
        if end <= position and not (token.pos == self.open_lexeme and position >= end):
            return False, False
        if token.type in (TokenType.STRING, TokenType.IDENTIFIER):
            return True, False
        return False, token.type == TokenType.COMMENT and self.text.startswith(
            _COMMENT_OPENER, token.pos
        )

    def _feed(self, first: int, end: int, number: int) -> None:
        """Feed the tokens that start in ``text[first:end]`` to the statement being read."""
        self._skip_to(first)
        string_before, comment_before = self._state(first)
        body, tokens, initial = self.body, self.tokens, self.rules.initial
        stray_before, count_before = body.stray, body.tokens
        body.semi_at = -1
        k, size = self.k, len(tokens)
        while k < size and tokens[k].pos < end:
            token = tokens[k]
            k += 1
            if token.type == TokenType.SYMBOL:
                if token.text == initial:
                    body.semicolon(token.pos - first)
                else:
                    body.symbol(token.text)
            elif token.type == TokenType.KEYWORD:
                body.word(token.text.upper())
            elif token.type != TokenType.COMMENT:
                body.literal()
        self.k = k
        self.in_string, self.in_comment = self._state(end)
        read = body.tokens > count_before
        if read or string_before or self.in_string or (comment_before and self.block_code):
            self.last_code = len(self.segs)  # the line is code, not a comment after the code
        if not comment_before and self.in_comment:
            self.block_code = read
            self.block_line = number
        if body.stray and not stray_before:
            self.stray_line = number

    def _overlaps_a_comment_delimiter(self, end: int, terminator: str) -> bool:
        """Whether the terminator, read with the character before it, opens or closes a comment."""
        last = self.tokens[self.k - 1] if self.k else None
        depth, before = 0, ""
        if last is not None and last.pos + len(last.text) > end:
            if not self.text.startswith(_COMMENT_OPENER, last.pos):
                return False  # a string, an identifier or a line comment spans the end of the body
            depth, alone = self.marks[end]
            before = self.text[end - 1] if alone else ""
        elif last is not None and last.type == TokenType.SYMBOL and last.pos + 1 == end:
            before = self.text[end - 1]
        return self._flips(before + terminator, depth)

    def _flips(self, text: str, depth: int) -> bool:
        level, i, line_comment = depth, 0, self.rules.line_comment
        while i < len(text):
            if level:
                if text.startswith(_COMMENT_OPENER, i):
                    level, i = level + 1, i + 2
                elif text.startswith(_COMMENT_CLOSER, i):
                    level, i = level - 1, i + 2
                else:
                    i += 1
            elif text.startswith(line_comment, i):
                break
            elif text.startswith(_COMMENT_OPENER, i):
                level, i = 1, i + 2
            else:
                i += 1
        return bool(level) != bool(depth)

    # --- records -------------------------------------------------------------------------

    def _end(self, terminator: Optional[str], cut: int = -1) -> None:
        """End the statement: emit it unless empty, refuse it if the client cannot send it as is."""
        segs = self.segs if cut < 0 else self.segs[:cut]
        text, start = self.text, self.start
        for first, last in segs:  # the statement starts on the first line with anything on it
            if text[first:last].strip(self.text_blanks):
                break
            start += 1
        statement = "\n".join(text[first:last] for first, last in segs).strip(self.text_blanks)
        body, stray_line = self.body, self.stray_line
        self.segs, self.body = [], RoutineBody(self.rules.routine)
        if not statement or not (body.code or statement.isspace()):
            return  # only characters the client keeps are a statement: the server rejects it
        epilogue = self._command(statement, start)
        if body.stray:
            raise UnsafeStatementSplitError(
                f"line {stray_line} has code after a {self.rules.initial!r} in the middle of a "
                "line: "
                f"the {self.client} sends it whole and the server rejects it, and the "
                f"{self.rules.driver_name} driver runs only the text before the "
                f"{self.rules.initial!r}; put each statement on its own line, ended by the "
                f"terminator, or declare another terminator with {self.rules.directive_name}"
            )
        origin = self.script.origin
        self.records.append(
            Statement(
                statement,
                start,
                terminator,
                "sql",
                source_start=self.unit_start + origin,
                source_end=self.line_end + origin,
            )
        )
        self.epilogues.append(epilogue)

    def _command(self, statement: str, number: int) -> bool:
        """True for the commands a script may end with; refuses every other client command."""
        rules, client = self.rules, self.client
        if statement[0] in rules.command_prefixes:
            raise UnsupportedMetaCommandError(
                f"{client} command {statement[0]!r} on line {number}: "
                "dblift does not run client commands"
            )
        words = self._leading_words(statement)
        if not words:
            return False
        if any(words[: len(known)] == known for known in rules.epilogue_words):
            if not self.epilogue.match(statement):
                raise UnsafeStatementSplitError(
                    f"{words[0]} on line {number} is not alone on its line: the {client} joins it "
                    "with what follows and the server rejects the text; end it with the terminator"
                )
            return True
        if any(words[: len(known)] == known for known in rules.sql_phrases):
            return False
        if words[0] in rules.command_words or any(
            words[: len(known)] == known for known in rules.command_phrases
        ):
            raise UnsupportedMetaCommandError(
                f"{client} command {words[0]} on line {number}: dblift does not run client commands"
            )
        return False

    def _leading_words(self, statement: str) -> Tuple[str, ...]:
        words: Tuple[str, ...] = ()
        for token in statement.split(None, 3)[:3]:
            match = self.leading.match(token)
            if match is None:
                break
            words += (match.group().upper(),)
            if match.end() < len(token):
                break
        return words

    def _epilogue(self) -> List[Statement]:
        """An epilogue command is recorded and dropped when nothing but epilogue commands follow."""
        last_sql = max(
            (i for i, r in enumerate(self.records) if r.kind == "sql" and not self.epilogues[i]),
            default=-1,
        )
        out: List[Statement] = []
        for index, record in enumerate(self.records):
            if self.epilogues[index]:
                if index < last_sql:
                    raise UnsupportedMetaCommandError(
                        f"{self.client} command {record.text.split(None, 1)[0].upper()} on line "
                        f"{record.line}: dblift does not run client commands"
                    )
                record = replace(record, kind="directive")
            out.append(record)
        return out

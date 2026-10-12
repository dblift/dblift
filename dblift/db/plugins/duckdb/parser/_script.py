"""Cut a DuckDB script into the statements the engine receives.

docs/sql-parsing/duckdb.md sections 1 to 6. A statement ends at a ``;`` outside strings, quoted
identifiers, dollar-quoted strings and comments. Block comments nest, ``E'...'`` strings read a
backslash, ``$tag$ ... $tag$`` closes only on the same tag, and a line that starts with ``.`` while
no statement text is pending is a ``duckdb`` shell command, which is refused: the shell runs it and
the engine cannot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError

#: The engine reads 18 non-ASCII code points as blanks: U+00A0, U+2000 to U+200B, U+202F, U+205F,
#: U+2060, U+3000 and U+FEFF. ``_NON_BLANK`` is every other code point from U+0080 on, which an
#: identifier may hold; a blank glued to a dollar quote or an ``E`` must not read as part of a word.
_BLANKS_UNICODE = (
    "\xa0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u200b"
    "\u202f\u205f\u2060\u3000\ufeff"
)
_NON_BLANK = (
    "\x80-\x9f\xa1-\u1fff\u200c-\u202e\u2030-\u205e\u2061-\u2fff\u3001-\ufefe" "\uff00-\U0010ffff"
)
#: An identifier is a letter, ``_`` or a non-blank non-ASCII character, then those, digits and
#: ``$``: so ``a$$b`` and ``SELECT$$a`` are words and a dollar quote cannot open inside one.
_IDENT = re.compile(rf"[A-Za-z_{_NON_BLANK}][A-Za-z0-9_${_NON_BLANK}]*")
_NUMBER = re.compile(r"[0-9][0-9A-Za-z_]*")
#: ``$tag$`` or ``$$``: the tag starts like an identifier and has no ``$``; ``$1`` and ``$name`` are
#: parameters and do not match.
_TAG = re.compile(rf"\$(?:[A-Za-z_{_NON_BLANK}][A-Za-z0-9_{_NON_BLANK}]*)?\$")
_PARAMETER = re.compile(rf"\$[A-Za-z0-9_{_NON_BLANK}]*")
_LINE_END = re.compile(r"[\r\n]")
_COMMENT_EDGE = re.compile(r"/\*|\*/")
_BLANKS = " \t\n\f\r"


@dataclass(frozen=True)
class Unit:
    """One statement: its text without the terminator, its first line, what ended it."""

    text: str
    line: int
    terminator: Optional[str]


def scan_script(script: str, *, comment_only: bool = False) -> List[Unit]:
    """The statements of ``script``; ``comment_only`` keeps the comment-only segments as units."""
    text = script[1:] if script.startswith("\ufeff") else script
    return _Scanner(text, comment_only).run()


def _is_escape_prefix(word: str) -> bool:
    """``E`` or ``e`` alone, or after digits (``1E'a'`` is the number 1 and an E string)."""
    return word[-1] in "Ee" and (len(word) == 1 or word[:-1].isdigit())


class _Scanner:
    def __init__(self, text: str, comment_only: bool) -> None:
        nul = text.find("\x00")
        if nul >= 0:
            raise UnsafeStatementSplitError(
                f"a NUL character on line {text.count(chr(10), 0, nul) + 1}: the engine reads "
                "the script up to it and silently drops the rest"
            )
        self.text = text
        self.comment_only = comment_only
        self.units: List[Unit] = []
        self.code = False
        self.segment = 0
        self.segment_line = 1
        self.line = 1

    def run(self) -> List[Unit]:
        text, size, i = self.text, len(self.text), 0
        while i < size:
            char = text[i]
            if char == "\n":
                self.line += 1
                i += 1
            elif char in " \t\f\r" or char in _BLANKS_UNICODE:
                i += 1
            elif char == "." and not self.code and (i == 0 or text[i - 1] == "\n"):
                self._refuse_command(i)
            elif text.startswith("--", i):
                end = _LINE_END.search(text, i)
                i = size if end is None else end.start()
            elif text.startswith("/*", i):
                i = self._block_comment(i)
            elif char == "'":
                self.code = True
                i = self._plain_string(i)
            elif char == '"':
                self.code = True
                i = self._quoted(i, '"')
            elif char == "$":
                self.code = True
                i = self._dollar(i)
            elif char == ";":
                self._finish(i, ";")
                self.segment, self.segment_line = i + 1, self.line
                i += 1
            else:
                self.code = True
                i = self._word(i)
        self._finish(size, None)
        return self.units

    def _refuse_command(self, i: int) -> None:
        command = self.text[i:].split(None, 1)[0]
        raise UnsupportedMetaCommandError(
            f"duckdb shell command {command!r} on line {self.line}: the shell runs it and the "
            "engine cannot; dblift does not run client commands"
        )

    def _word(self, i: int) -> int:
        """A word, a number or one other character; an ``E`` touching a quote opens an E string."""
        text = self.text
        match = _IDENT.match(text, i) or _NUMBER.match(text, i)
        if match is None:
            return i + 1
        end = match.end()
        if text.startswith("'", end) and _is_escape_prefix(match.group()):
            return self._escape_string(end)
        return end

    def _block_comment(self, i: int) -> int:
        """Block comments nest; one never closed is sent as it stands (the engine rejects it)."""
        text, depth, j = self.text, 1, i + 2
        while depth:
            edge = _COMMENT_EDGE.search(text, j)
            if edge is None:
                self.code = True
                self.line += text.count("\n", i)
                return len(text)
            depth += 1 if edge.group() == "/*" else -1
            j = edge.end()
        self.line += text.count("\n", i, j)
        return j

    def _quoted(self, i: int, closer: str) -> int:
        """A quoted identifier; a doubled quote is two lexemes in a row, so no escape rule."""
        end = self.text.find(closer, i + 1)
        if end < 0:
            self.line += self.text.count("\n", i)
            return len(self.text)
        self.line += self.text.count("\n", i, end)
        return end + 1

    def _plain_string(self, i: int) -> int:
        return self._quoted(i, "'")

    def _escape_string(self, quote: int) -> int:
        """``E'...'``: a backslash takes the next character, ``''`` is a quote; ``quote`` opens."""
        text, size, j = self.text, len(self.text), quote + 1
        while j < size:
            char = text[j]
            if char == "\\":
                j += 2
            elif char == "'":
                if text.startswith("'", j + 1):
                    j += 2
                    continue
                self.line += text.count("\n", quote, j)
                return j + 1
            else:
                j += 1
        self.line += text.count("\n", quote)
        return size

    def _dollar(self, i: int) -> int:
        """``$tag$ ... $tag$`` (closes on the same tag only), else a parameter such as ``$1``."""
        opener = _TAG.match(self.text, i)
        if opener is None:
            return _PARAMETER.match(self.text, i).end()  # type: ignore[union-attr]
        tag = opener.group()
        end = self.text.find(tag, opener.end())
        if end < 0:
            self.line += self.text.count("\n", i)
            return len(self.text)
        self.line += self.text.count("\n", i, end)
        return end + len(tag)

    def _finish(self, end: int, terminator: Optional[str]) -> None:
        raw = self.text[self.segment : end]
        if self.code or (self.comment_only and raw.strip(_BLANKS)):
            text = raw.lstrip(_BLANKS)
            line = self.segment_line + raw.count("\n", 0, len(raw) - len(text))
            self.units.append(Unit(text.rstrip(_BLANKS), line, terminator))
        self.code = False

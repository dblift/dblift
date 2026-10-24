"""A per-rules cache keyed by object identity: hashing a rules object costs more than its use."""

from typing import Callable, Dict, Generic, Tuple, TypeVar

from dblift.core.sql_parser.lexical_spec import BatchScriptRules

T = TypeVar("T")


class RulesCache(Generic[T]):
    """Build a value from a ``BatchScriptRules`` once and look it up by the object's identity."""

    def __init__(self, build: Callable[[BatchScriptRules], T], limit: int = 64) -> None:
        """``build`` makes the value; the cache is cleared past ``limit`` entries."""
        self._build = build
        self._limit = limit
        self._entries: Dict[int, Tuple[BatchScriptRules, T]] = {}

    def get(self, rules: BatchScriptRules) -> T:
        """The value for ``rules``, built on first use."""
        entry = self._entries.get(id(rules))
        if entry is None or entry[0] is not rules:
            if len(self._entries) > self._limit:
                self._entries.clear()
            entry = self._entries[id(rules)] = (rules, self._build(rules))
        return entry[1]

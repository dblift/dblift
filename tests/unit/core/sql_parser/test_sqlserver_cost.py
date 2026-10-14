"""Splitting a SQL Server script costs time linear in its size, whatever its shape."""

import time

import pytest

from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC

#: shape name -> (script of n units, n for the small size). Each shape stresses one reader.
SHAPES = {
    "one lexeme across many lines": (
        lambda n: "SELECT '" + "line of text\n" * n + "'\nGO\n",
        950000,
    ),
    "many GO batches": (lambda n: "SELECT 1\nGO\n" * n, 28000),
    "many head lines": (lambda n: "SELECT 1\n  x1\n  y2 AS c,\n" * n + "GO\n", 14000),
    "one line of comments, words and semicolons": (
        lambda n: "/**/ " * n + "/**/ SELECT 1; " * n + "\r" * n + "x GO x\nGO\n",
        20000,
    ),
}


def best_of(script, runs=3):
    engine = LexicalEngine(SQLSERVER_SPEC)
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        engine.split(script)
        times.append(time.perf_counter() - start)
    return min(times)


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_sqlserver_cost_grows_linearly(shape):
    """A 4x larger script takes about 4x as long: the ratio of the best times stays at or below 8."""
    make, n = SHAPES[shape]
    small = best_of(make(n))
    large = best_of(make(4 * n))
    assert large / small <= 8, f"{shape}: {small:.3f}s -> {large:.3f}s"


IDENTIFIERS = {
    "quoted identifier": (lambda n: 'SELECT "' + "line of text\n" * n + '"\nGO\n', 950000),
    "bracketed identifier": (lambda n: "SELECT [" + "line of text\n" * n + "]\nGO\n", 950000),
}


@pytest.mark.parametrize("shape", sorted(IDENTIFIERS))
def test_sqlserver_identifier_cost_grows_linearly(shape):
    """A quoted or bracketed name across many lines is read in time linear in its length."""
    make, n = IDENTIFIERS[shape]
    small = best_of(make(n))
    large = best_of(make(4 * n))
    assert large / small <= 8, f"{shape}: {small:.3f}s -> {large:.3f}s"

"""Tests for the public ``table_references`` helper in ``dependency_analyzer``."""

import pytest

from dblift.core.sql_generator.dependency_analyzer import DependencyAnalyzer, table_references

pytestmark = [pytest.mark.unit]


def test_table_references_returns_unqualified_table():
    assert table_references("SELECT id FROM users") == [(None, "users")]


def test_table_references_includes_schema_qualified_join():
    refs = set(table_references("SELECT * FROM users u JOIN sales.Orders o ON o.user_id = u.id"))

    assert (None, "users") in refs
    assert ("sales", "orders") in refs


def test_table_references_strips_identifier_quoting():
    refs = set(table_references('SELECT * FROM "app"."users" JOIN [dbo].[orders] ON 1 = 1'))

    assert ("app", "users") in refs
    assert ("dbo", "orders") in refs


def test_table_references_is_empty_without_from_or_join():
    assert table_references("SELECT 1") == []


def test_table_references_matches_the_private_extractor():
    query = "SELECT * FROM a JOIN s.b ON 1 = 1 LEFT JOIN c ON 1 = 1"

    assert sorted(table_references(query), key=str) == sorted(
        DependencyAnalyzer()._extract_table_references_from_query(query), key=str
    )


def test_table_references_are_sorted_unqualified_first():
    query = "SELECT * FROM zeta JOIN s2.b ON 1 = 1 JOIN alpha ON 1 = 1 JOIN s1.c ON 1 = 1"

    assert table_references(query) == [
        (None, "alpha"),
        (None, "b"),
        (None, "c"),
        (None, "zeta"),
        ("s1", "c"),
        ("s2", "b"),
    ]

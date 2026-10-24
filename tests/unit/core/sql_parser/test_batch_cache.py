"""The per-rules cache builds once per rules object and stays bounded."""

from dataclasses import replace

from dblift.core.sql_parser.batch_cache import RulesCache
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_BATCHES


def test_a_value_is_built_once_per_rules_object():
    built = []
    cache = RulesCache(lambda rules: built.append(rules) or len(built))
    first = cache.get(SQLSERVER_BATCHES)
    assert cache.get(SQLSERVER_BATCHES) == first
    other = replace(SQLSERVER_BATCHES, max_repeat=3)
    assert cache.get(other) != first
    assert len(built) == 2


def test_the_cache_is_cleared_past_its_limit():
    built = []
    cache = RulesCache(lambda rules: built.append(rules) or len(built), limit=2)
    variants = [replace(SQLSERVER_BATCHES, max_repeat=n) for n in range(1, 5)]
    for rules in variants:
        cache.get(rules)
    assert len(built) == 4
    cache.get(variants[0])  # forgotten when the cache was cleared
    assert len(built) == 5

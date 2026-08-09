"""Guard the type-normalization surface consumed by extension packages.

``core.normalization`` and the ``type_equivalents()`` quirks hook have no
call sites inside this repository — schema comparison is not part of the
open-source command set. A repository-local search therefore reads them as
dead code, and an audit acting on that reading would break every installed
extension that performs cross-dialect type comparison.

These tests exist so that deletion fails here first, with an explanation,
instead of downstream.
"""

import pytest

from core.normalization import DataTypeNormalizer
from db.provider_registry import ProviderRegistry

# Dialects whose plugins ship a non-empty alias table. Kept explicit: an
# accidental emptying is the failure mode this guards against.
DIALECTS_WITH_TYPE_ALIASES = [
    "postgresql",
    "mysql",
    "oracle",
    "sqlserver",
    "db2",
    "sqlite",
    "duckdb",
]


@pytest.mark.unit
def test_normalizer_is_importable_from_the_package_root():
    """Consumers import this symbol; it must stay exported."""
    assert DataTypeNormalizer is not None


@pytest.mark.unit
def test_normalizer_builds_its_dialect_tables():
    """The normalizer must survive construction against the live registry."""
    normalizer = DataTypeNormalizer()
    assert normalizer.type_equivalents


@pytest.mark.unit
@pytest.mark.parametrize("dialect", DIALECTS_WITH_TYPE_ALIASES)
def test_dialect_exposes_type_equivalents(dialect: str):
    """Every listed plugin must keep a populated alias→canonical table."""
    ProviderRegistry.discover_plugins()
    equivalents = ProviderRegistry.get_quirks(dialect).type_equivalents()

    assert isinstance(equivalents, dict)
    assert equivalents, f"{dialect} lost its type_equivalents table"

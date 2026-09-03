"""Normalization utilities for schema objects.

This package provides data type normalization helpers used when comparing
SQL objects across dialects.

**Not dead code.** Nothing inside this repository calls
:class:`~core.normalization.type_normalizer.DataTypeNormalizer` — schema
comparison is not part of the open-source command set. It is a published
surface consumed by installed extension packages, together with the
``type_equivalents()`` quirks hook it reads from every dialect plugin
(see :mod:`dblift.core.dialect_boundary`). A repository-local "no call sites"
search will therefore look conclusive and be wrong; removing either the
normalizer or the quirks hook breaks those consumers.
"""

from dblift.core.normalization.type_normalizer import DataTypeNormalizer

__all__ = ["DataTypeNormalizer"]

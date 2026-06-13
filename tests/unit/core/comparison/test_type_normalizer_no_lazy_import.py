"""Tests structurels pour valider la suppression du lazy import dans type_normalizer.

Story 16-22: Split type mapping data to remove circular import in type_normalizer.
Vérifie que le lazy import a été remplacé par un import module-level depuis type_constants,
que type_constants.py est un module feuille sans imports projet, et que
CanonicalTypeMapper reste importable via le package core.normalization.
"""

import inspect
import sys

import pytest


@pytest.mark.unit
class TestTypeNormalizerNoLazyImport:
    """AC#6 — Tests structurels : absence du lazy import."""

    def test_no_lazy_import_in_build_method(self):
        """_build_cross_dialect_equivalents ne contient aucun import lazy."""
        from core.comparison.type_normalizer import DataTypeNormalizer

        source = inspect.getsource(DataTypeNormalizer._build_cross_dialect_equivalents)
        assert (
            "from core.normalization" not in source
        ), "Lazy import toujours présent dans _build_cross_dialect_equivalents"

    def test_type_normalizer_importable_at_module_level(self):
        """core.comparison.type_normalizer est importable sans ImportError."""
        mod_name = "core.comparison.type_normalizer"
        saved = sys.modules.pop(mod_name, None)
        try:
            import core.comparison.type_normalizer  # noqa: F401
        finally:
            if saved is not None:
                sys.modules[mod_name] = saved

    def test_canonical_to_variants_accessible_at_module_level(self):
        """CANONICAL_TO_VARIANTS est accessible depuis type_constants."""
        from core.normalization.type_constants import CANONICAL_TO_VARIANTS

        assert "INTEGER" in CANONICAL_TO_VARIANTS
        assert isinstance(CANONICAL_TO_VARIANTS["INTEGER"], set)


@pytest.mark.unit
class TestTypeConstantsLeafModule:
    """AC#7 — Tests structurels : type_constants.py est un module feuille."""

    def test_type_constants_has_no_project_imports(self):
        """type_constants.py ne contient aucun import projet (module feuille)."""
        import core.normalization.type_constants as mod

        source = inspect.getsource(mod)
        lines = source.splitlines()
        for line in lines:
            stripped = line.strip()
            assert not stripped.startswith(
                "from core"
            ), f"Import projet détecté dans type_constants.py: {line!r}"
            assert not stripped.startswith(
                "import core"
            ), f"Import projet détecté dans type_constants.py: {line!r}"

    def test_canonical_to_variants_not_in_type_mappings_source(self):
        """CANONICAL_TO_VARIANTS n'est plus défini inline dans type_mappings.py."""
        import core.normalization.type_mappings as mod

        source = inspect.getsource(mod)
        assert (
            "CANONICAL_TO_VARIANTS: Dict" not in source
        ), "CANONICAL_TO_VARIANTS est encore défini inline dans type_mappings.py"


@pytest.mark.unit
class TestRuntimeCompatibility:
    """AC#8 — Aucune régression runtime."""

    def test_canonical_type_mapper_still_importable_via_package(self):
        """from core.normalization import CanonicalTypeMapper fonctionne en runtime."""
        from core.normalization import CanonicalTypeMapper

        assert CanonicalTypeMapper is not None

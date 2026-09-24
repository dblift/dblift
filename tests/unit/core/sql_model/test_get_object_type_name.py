from unittest.mock import MagicMock

import pytest

from dblift.core.sql_model.base import SqlObjectType, get_object_type_name

pytestmark = [pytest.mark.unit]


class TestGetObjectTypeName:
    """Tests de la fonction utilitaire get_object_type_name."""

    def _make_obj(self, object_type):
        obj = MagicMock()
        obj.object_type = object_type
        return obj

    def test_returns_value_for_enum_type(self):
        """Retourne .value quand object_type est un SqlObjectType enum."""
        obj = self._make_obj(SqlObjectType.TABLE)
        assert get_object_type_name(obj) == "TABLE"

    def test_returns_value_for_view_type(self):
        """Fonctionne pour VIEW."""
        obj = self._make_obj(SqlObjectType.VIEW)
        assert get_object_type_name(obj) == "VIEW"

    def test_returns_value_for_index_type(self):
        """Fonctionne pour INDEX."""
        obj = self._make_obj(SqlObjectType.INDEX)
        assert get_object_type_name(obj) == "INDEX"

    def test_returns_str_for_non_enum_type(self):
        """Retourne str() quand object_type n'est pas un SqlObjectType enum."""
        obj = self._make_obj("CUSTOM_TYPE")
        assert get_object_type_name(obj) == "CUSTOM_TYPE"

    def test_returns_str_for_unknown_string(self):
        """Retourne la chaîne brute pour un type inconnu."""
        obj = self._make_obj("UNKNOWN_OBJECT")
        assert get_object_type_name(obj) == "UNKNOWN_OBJECT"

    def test_equivalent_to_original_pattern_with_enum(self):
        """Équivalence exacte avec le pattern hasattr original (enum case)."""
        obj = self._make_obj(SqlObjectType.SEQUENCE)
        original = (
            obj.object_type.value if hasattr(obj.object_type, "value") else str(obj.object_type)
        )
        assert get_object_type_name(obj) == original

    def test_equivalent_to_original_pattern_with_string(self):
        """Équivalence exacte avec le pattern hasattr original (string case)."""
        obj = self._make_obj("RAW_STRING")
        original = (
            obj.object_type.value if hasattr(obj.object_type, "value") else str(obj.object_type)
        )
        assert get_object_type_name(obj) == original

    def test_importable_from_core_sql_model_base(self):
        """get_object_type_name est importable depuis core.sql_model.base."""
        import importlib

        mod = importlib.import_module("dblift.core.sql_model.base")
        assert hasattr(mod, "get_object_type_name")
        assert callable(mod.get_object_type_name)

    def test_returns_str_for_none_type(self):
        """None object_type → str(None) = 'None', sans exception."""
        obj = self._make_obj(None)
        result = get_object_type_name(obj)
        assert result == "None"

    def test_behavior_change_non_enum_with_value_attr(self):
        """Documente le changement vs pattern hasattr original.

        Avec hasattr: un objet non-SqlObjectType ayant .value retournait .value.
        Avec isinstance: retourne str(obj) — comportement intentionnel (Dev Notes 20-11).
        """
        obj = self._make_obj(MagicMock())  # MagicMock a un .value auto-généré
        obj.object_type.value = "mock_value"
        # isinstance(MagicMock(), SqlObjectType) est False → str() path
        result = get_object_type_name(obj)
        assert result != "mock_value"  # contrairement à l'ancien hasattr
        assert isinstance(result, str)

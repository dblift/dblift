import pytest

from db.plugins.oracle.parser._object_extractor import extract_objects


@pytest.mark.unit
class TestExtractObjectsRegexIndexEmptyColumnGuard:
    def test_extract_objects_regex_index_empty_column_no_crash(self):
        """CREATE INDEX avec colonne vide dans la liste ne leve pas IndexError."""
        sql = "CREATE INDEX idx ON my_table(col1, , col2)"
        # Ne doit pas lever IndexError
        result = extract_objects(sql, default_schema="MYSCHEMA")
        assert result is not None

    def test_extract_objects_regex_index_empty_column_skips_empty(self):
        """La colonne vide est exclue, les colonnes valides sont presentes."""
        sql = "CREATE INDEX idx ON my_table(col1, , col2)"
        result = extract_objects(sql, default_schema="MYSCHEMA")
        indexes = [obj for obj in result if hasattr(obj, "columns")]
        assert len(indexes) == 1
        # Le parseur preserve la casse d'origine — colonnes lowercase dans le SQL d'entree
        assert "col1" in indexes[0].columns
        assert "col2" in indexes[0].columns
        # L'entree vide ne doit pas figurer dans les colonnes
        assert "" not in indexes[0].columns
        assert any(c.strip() == "" for c in indexes[0].columns) is False

    def test_extract_objects_regex_index_whitespace_only_column_skips(self):
        """Une colonne composee d'espaces est exclue du resultat."""
        sql = "CREATE INDEX idx ON my_table(col1,   , col2)"
        result = extract_objects(sql, default_schema="MYSCHEMA")
        indexes = [obj for obj in result if hasattr(obj, "columns")]
        assert len(indexes) == 1
        # Le parseur preserve la casse : ["col1", "col2"] (lowercase comme dans le SQL)
        assert indexes[0].columns == ["col1", "col2"]

    def test_extract_objects_regex_index_all_columns_empty_returns_empty_list(self):
        """Si toutes les colonnes sont vides, columns est [] sans exception."""
        # Ce cas est artificiel mais ne doit pas crasher
        # Note: le regex ([^)]+) exige au moins un char non-`)`, donc ( , , ) peut ne pas matcher
        sql = "CREATE INDEX idx ON my_table( , , )"
        result = extract_objects(sql, default_schema="MYSCHEMA")
        # Si le regex matche, aucune colonne valide ne doit etre presente
        indexes = [obj for obj in result if hasattr(obj, "columns")]
        for idx in indexes:
            assert idx.columns == [], f"Expected no columns but got {idx.columns}"

    def test_extract_objects_regex_index_normal_columns_unchanged(self):
        """Le comportement nominal (colonnes valides) est inchange apres le fix."""
        sql = 'CREATE INDEX MY_IDX ON MY_TABLE(COL1, COL2, "col3")'
        result = extract_objects(sql, default_schema="MYSCHEMA")
        indexes = [obj for obj in result if hasattr(obj, "columns")]
        assert len(indexes) == 1
        assert len(indexes[0].columns) == 3
        # Unquoted uppercase colonnes preservent leur casse ; colonne quotee preserve la minuscule
        assert "COL1" in indexes[0].columns
        assert "COL2" in indexes[0].columns
        assert "col3" in indexes[0].columns

    def test_extract_objects_regex_index_trailing_comma_no_crash(self):
        """Un trailing comma (col1,) produit une entree vide qui est filtree."""
        sql = "CREATE INDEX idx ON my_table(col1,)"
        result = extract_objects(sql, default_schema="MYSCHEMA")
        indexes = [obj for obj in result if hasattr(obj, "columns")]
        assert len(indexes) == 1
        assert indexes[0].columns == ["col1"]
        assert "" not in indexes[0].columns

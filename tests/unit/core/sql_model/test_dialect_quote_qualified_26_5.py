"""Characterization tests for quote_qualified (story 26-5).

quote_qualified had ZERO coverage before this story. These tests pin the
exact pre-refactor behaviour so the Oracle-branch → quirks-capability
migration (``quote_qualified_folds_to_uppercase``) and the quoting →
quirks delegation stay byte-identical.

Critical invariant: Oracle upper-cases the folded identifier + schema,
but DB2 (which shares Oracle's identifier-folding quirks) does NOT.
"""

import pytest

from core.sql_model.dialect import quote_qualified

pytestmark = [pytest.mark.unit]


class TestQuoteQualifiedUppercaseFolding:
    """Oracle upper-cases; DB2 (identical folding quirks) must NOT."""

    def test_oracle_uppercases_schema_and_identifier(self):
        assert quote_qualified("oracle", "myschema", "mytable") == '"MYSCHEMA"."MYTABLE"'

    def test_oracle_uppercases_mixed_case_input(self):
        assert quote_qualified("Oracle", "MixedCase", "TableName") == '"MIXEDCASE"."TABLENAME"'

    def test_oracle_uppercases_identifier_only_when_no_schema(self):
        assert quote_qualified("oracle", None, "mytable") == '"MYTABLE"'

    def test_oracle_empty_schema_treated_as_no_schema(self):
        assert quote_qualified("oracle", "", "mytable") == '"MYTABLE"'

    def test_db2_does_not_uppercase_despite_folding_quirks(self):
        # Whole point of story 26-5: DB2 shares Oracle's identifier-folding
        # quirks but quote_qualified must leave its idents unchanged.
        assert quote_qualified("db2", "myschema", "mytable") == '"myschema"."mytable"'

    def test_db2_identifier_only_unchanged(self):
        assert quote_qualified("db2", None, "mytable") == '"mytable"'


class TestQuoteQualifiedNonUppercasingDialects:
    """All non-Oracle dialects leave identifier case untouched."""

    @pytest.mark.parametrize(
        "dialect, schema, identifier, expected",
        [
            ("postgresql", "myschema", "mytable", '"myschema"."mytable"'),
            ("postgresql", None, "mytable", '"mytable"'),
            ("mysql", "myschema", "mytable", "`myschema`.`mytable`"),
            ("sqlserver", "myschema", "mytable", "[myschema].[mytable]"),
            ("sqlite", "main", "mytable", '"main"."mytable"'),
            # CosmosDB quirks set empty quote chars (NoSQL).
            ("cosmosdb", "db", "cont", "db.cont"),
            # None / unknown dialect → ANSI double-quote, no folding.
            (None, "sch", "tbl", '"sch"."tbl"'),
            ("unknown_db", "sch", "tbl", '"sch"."tbl"'),
        ],
    )
    def test_quote_qualified_parametric(self, dialect, schema, identifier, expected):
        result = quote_qualified(dialect, schema, identifier)
        assert result == expected, (
            f"quote_qualified({dialect!r}, {schema!r}, {identifier!r}) → "
            f"{result!r}, expected {expected!r}"
        )

    def test_no_schema_returns_bare_quoted_identifier(self):
        assert quote_qualified("postgresql", None, "tbl") == '"tbl"'
        assert quote_qualified("mysql", "", "tbl") == "`tbl`"

    def test_quote_qualified_is_module_function(self):
        # Importable and callable as a plain module-level function.
        assert quote_qualified("postgresql", "s", "t") == '"s"."t"'

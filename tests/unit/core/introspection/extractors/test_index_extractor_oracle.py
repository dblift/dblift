"""Oracle index extractor regressions."""

import pytest

from core.introspection.extractors.index_extractor import IndexExtractor


@pytest.mark.unit
def test_oracle_domain_index_preserves_metadata_ddl():
    extractor = IndexExtractor(provider=object(), dialect="oracle")
    definition = (
        "CREATE INDEX IDX_DOCS_TEXT ON DOCS(CONTENT) "
        "INDEXTYPE IS CTXSYS.CONTEXT PARAMETERS ('lexer my_lexer')"
    )
    rows = [
        {
            "index_name": "IDX_DOCS_TEXT",
            "column_name": "CONTENT",
            "ordinal_position": 1,
            "is_unique": "N",
            "index_type": "DOMAIN",
            "definition": definition,
        }
    ]

    parsed = extractor._parse_vendor_rows("DOCS", rows)
    indexes = extractor._build_index_objects("APP", "DOCS", parsed)

    assert len(indexes) == 1
    assert indexes[0].type == "DOMAIN"
    assert indexes[0].definition == definition

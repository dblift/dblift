"""DuckDB's query text for a single cut of the original SQL script."""


def single_query_text(statement: str) -> str:
    import duckdb

    parsed = duckdb.extract_statements(statement)
    assert len(parsed) == 1, statement
    return parsed[0].query

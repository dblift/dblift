from dblift.core.sql_parser import statement
from dblift.core.sql_parser.statement import Statement


def test_analysis_projects_executed_sql_once_and_keeps_copy_header() -> None:
    records = [
        Statement("CREATE TABLE skipped(id INT)", 1, "GO", repeat=0),
        Statement(
            "SELECT 1; SELECT 2;", 3, "GO", repeat=3, analysis_statements=("SELECT 1;", "SELECT 2;")
        ),
        Statement(
            "COPY t FROM STDIN;\n\n\\.",
            6,
            "\\.",
            kind="copy_stdin",
            analysis_statements=("COPY t FROM STDIN;",),
        ),
        Statement("DELIMITER //", 10, None, kind="directive"),
        Statement("unanalysable text", 11, None, analysis_statements=()),
        Statement("SELECT 3", 12, None),
    ]

    assert statement.analysis_sql(records) == [
        "SELECT 1;", "SELECT 2;", "COPY t FROM STDIN;", "SELECT 3"
    ]


def test_record_offsets_are_optional_original_source_half_open_spans() -> None:
    original = "SELECT 1;\nGO 2\n"
    record = Statement(
        "SELECT 1;",
        1,
        "GO",
        repeat=2,
        source_start=0,
        source_end=len(original),
    )
    assert original[record.source_start : record.source_end] == original
    assert Statement("SELECT 2", 1, None).source_start is None
    assert Statement("SELECT 2", 1, None).source_end is None

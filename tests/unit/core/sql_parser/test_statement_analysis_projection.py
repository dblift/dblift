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
    ]

    assert statement.analysis_sql(records) == ["SELECT 1;", "SELECT 2;", "COPY t FROM STDIN;"]

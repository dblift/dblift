from dblift.core.migration.sql.script_analysis import analyse_script


def test_pending_statement_snippet_masks_sqlite_literal():
    analysis = analyse_script("INSERT INTO t VALUES ('private-token');", "sqlite")

    snippet = analysis.to_dict()["statements"][0]["snippet"]
    assert "private-token" not in snippet
    assert "INSERT INTO t VALUES" in snippet

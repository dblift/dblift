"""The mixed-transaction-modes lint judges the same unit the engine runs: the batch."""

from dblift.core.migration.sql.lint import lint_script


def _mixed(script):
    return [
        f for f in lint_script(script, "sqlserver").findings if f.code == "mixed-transaction-modes"
    ]


def test_a_flagged_statement_inside_a_batch_does_not_mix_with_its_neighbours():
    # one batch, one autocommit unit: the engine does not refuse it
    assert _mixed("CREATE TABLE t (id INT);\nRECONFIGURE;\n") == []


def test_a_flagged_batch_beside_a_transactional_batch_is_mixed():
    findings = _mixed("CREATE TABLE t (id INT);\nGO\nRECONFIGURE;\n")
    assert len(findings) == 1 and findings[0].severity == "error"


def test_a_script_of_only_flagged_batches_is_not_mixed():
    assert _mixed("RECONFIGURE;\nGO\nALTER DATABASE d SET RECOVERY SIMPLE;\n") == []

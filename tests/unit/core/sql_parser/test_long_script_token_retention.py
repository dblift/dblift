"""Many short statements should not retain tokens for the whole script."""

import gc
import tracemalloc

import pytest

from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.db2.parser.lexical_spec import DB2_SPEC
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC


@pytest.mark.parametrize("spec", [DB2_SPEC, POSTGRESQL_SPEC, DUCKDB_SPEC, MYSQL_SPEC])
def test_many_short_statements_do_not_retain_script_wide_tokens(spec):
    count = 640
    script = "INSERT INTO t VALUES (1);\n" * count
    gc.collect()
    tracemalloc.start()
    try:
        records = LexicalEngine(spec).split(script)
        retained, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert len(records) == count
    assert all(record.text == "INSERT INTO t VALUES (1)" for record in records)
    assert retained > 0
    assert peak < retained * 2.5

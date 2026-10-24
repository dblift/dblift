"""The journal does constant work per recorded statement, not work per statement so far.

Counted rather than timed: a counting ``JournalEntry`` tallies every read of the
fields the journal uses to look entries up, so the assertion holds on any machine.
"""

import pytest

from dblift.core.migration.journals import migration_journal as mj

pytestmark = pytest.mark.unit


class _CountingEntry(mj.JournalEntry):
    reads = 0

    @property
    def entry_type(self):
        type(self).reads += 1
        return self.__dict__["_entry_type"]

    @entry_type.setter
    def entry_type(self, value):
        self.__dict__["_entry_type"] = value

    @property
    def statement_index(self):
        type(self).reads += 1
        return self.__dict__["_statement_index"]

    @statement_index.setter
    def statement_index(self, value):
        self.__dict__["_statement_index"] = value


def _lookups_for(monkeypatch, statements: int) -> int:
    monkeypatch.setattr(mj, "JournalEntry", _CountingEntry)
    _CountingEntry.reads = 0
    journal = mj.MigrationJournal()
    journal.start_migration("V1__big.sql")
    for index in range(statements):
        journal.record_statement_start(f"INSERT INTO t VALUES ({index})", index)
        journal.record_statement_complete(f"INSERT INTO t VALUES ({index})", index, 1)
    journal.end_migration("V1__big.sql", success=True)
    return _CountingEntry.reads


def test_journal_work_grows_linearly_with_statement_count(monkeypatch):
    small = _lookups_for(monkeypatch, 1_000)
    large = _lookups_for(monkeypatch, 4_000)
    assert large <= small * 4.5, f"{small} -> {large} entry reads for 4x the statements"


def test_rerecording_a_statement_index_still_replaces_the_earlier_entry():
    journal = mj.MigrationJournal()
    journal.start_migration("V1__a.sql")
    journal.record_statement_start("A", 0)
    journal.record_statement_start("B", 1)
    journal.record_statement_start("A2", 0)
    journal.record_statement_complete("A", 0, 1)
    journal.end_migration("V1__a.sql", success=False)
    journal.current_migration_id = "V1__a.sql"
    journal.end_migration("V1__a.sql", success=True)

    entries = journal.get_migration_journal("V1__a.sql")
    assert [(e.entry_type.value, e.statement_index, e.statement) for e in entries] == [
        ("MIGRATION_START", 0, ""),
        ("STATEMENT_START", 1, "B"),
        ("STATEMENT_START", 0, "A2"),
        ("STATEMENT_COMPLETE", 0, "A"),
        ("MIGRATION_COMPLETE", 0, ""),
    ]


def _migrate_reads(monkeypatch, tmp_path, statements: int) -> int:
    from sqlalchemy import create_engine

    from dblift.api import DBLiftClient

    migrations = tmp_path / f"m{statements}"
    migrations.mkdir()
    body = "CREATE TABLE t (id INTEGER, v TEXT);\n" + "".join(
        f"INSERT INTO t (id, v) VALUES ({i}, 'row {i}');\n" for i in range(statements)
    )
    (migrations / "V1__big.sql").write_text(body)
    monkeypatch.setattr(mj, "JournalEntry", _CountingEntry)
    _CountingEntry.reads = 0
    engine = create_engine(f"sqlite:///{tmp_path / f'app{statements}.db'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    try:
        assert client.migrate().success
    finally:
        client.close()
        engine.dispose()
    return _CountingEntry.reads


def test_migrate_journal_work_grows_linearly_with_statement_count(monkeypatch, tmp_path):
    small = _migrate_reads(monkeypatch, tmp_path, 250)
    large = _migrate_reads(monkeypatch, tmp_path, 1_000)
    assert 0 < small and large <= small * 4.5, f"{small} -> {large} reads for 4x the statements"


def test_returned_journal_is_a_copy():
    journal = mj.MigrationJournal()
    journal.start_migration("V1__a.sql")
    journal.get_migration_journal("V1__a.sql").clear()
    assert len(journal.get_migration_journal("V1__a.sql")) == 1

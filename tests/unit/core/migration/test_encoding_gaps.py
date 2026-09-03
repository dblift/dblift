"""Encoding failures must stop the run, and detection must not flatten cp1252.

Two gaps found while qualifying 4.0.0:

* A migration whose bytes do not decode was collected as an "invalid script",
  logged at warning level and skipped. ``migrate`` then reported "No pending
  migrations found" and exited 0, so a latin-1 migration produced a green
  deploy that did nothing. The decoding itself is strict, which is right — the
  file is never half-read — but the verdict has to reach the command.
* ``iso-8859-1`` decodes every possible byte sequence, so it matched first for
  anything non-UTF-8 and detection never reached another candidate. A file
  written in Windows-1252 came back as latin-1 and its ``€`` (0x80) became a
  C1 control character, which is silent corruption rather than a failure.
"""

import pytest

from dblift.core.migration.encoding import (
    MigrationEncodingError,
    detect_file_encoding,
    read_migration_text,
)

pytestmark = [pytest.mark.unit]


class TestUndecodableScriptsStopTheRun:
    def test_reading_an_undecodable_script_raises(self, tmp_path):
        script = tmp_path / "V1__accents.sql"
        script.write_bytes("CREATE TABLE café (id INT);".encode("latin-1"))

        with pytest.raises(MigrationEncodingError):
            read_migration_text(script, configured_encoding="utf-8")

    def test_the_script_manager_does_not_downgrade_it_to_a_warning(self, tmp_path):
        """The regression itself.

        ``MigrationEncodingError`` subclasses ``ValueError``, and the scan
        caught ``ValueError`` to skip files that are not migrations at all —
        a wrong filename, say. An unreadable file *is* a migration; skipping it
        turns a deploy that applied nothing into a success.
        """
        from dblift.core.logger import NullLog
        from dblift.core.migration.scripting.migration_script_manager import (
            MigrationScriptManager,
        )

        (tmp_path / "V1__accents.sql").write_bytes("CREATE TABLE café (id INT);".encode("latin-1"))
        manager = MigrationScriptManager(NullLog(), script_encoding="utf-8")

        with pytest.raises(MigrationEncodingError):
            manager.load_migration_scripts(tmp_path)

    def test_a_file_that_is_simply_not_a_migration_is_still_skipped(self, tmp_path):
        """The behaviour the ValueError branch exists for must survive.

        A README beside the migrations is not an error; only a file that
        cannot be read is.
        """
        from dblift.core.logger import NullLog
        from dblift.core.migration.scripting.migration_script_manager import (
            MigrationScriptManager,
        )

        (tmp_path / "V1__ok.sql").write_text("CREATE TABLE t (id INT);", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("not a migration", encoding="utf-8")
        manager = MigrationScriptManager(NullLog(), script_encoding="utf-8")

        migrations = manager.load_migration_scripts(tmp_path)

        assert sum(len(v) for v in migrations.values()) == 1


class TestWindows1252Detection:
    def test_a_euro_sign_survives_detection(self, tmp_path):
        """0x80 is ``€`` in cp1252 and a control character in latin-1.

        Reporting latin-1 here loses the character without any error, which is
        the outcome detection exists to avoid.
        """
        script = tmp_path / "V1__euro.sql"
        script.write_bytes("INSERT INTO t VALUES ('12 €');".encode("windows-1252"))

        assert detect_file_encoding(script) in ("cp1252", "windows-1252")
        assert "€" in read_migration_text(script, detect_encoding=True)

    def test_plain_latin1_text_is_still_read_correctly(self, tmp_path):
        """cp1252 and latin-1 agree outside 0x80–0x9F, so accents are safe either way."""
        script = tmp_path / "V1__accents.sql"
        script.write_bytes("INSERT INTO t VALUES ('café');".encode("latin-1"))

        assert "café" in read_migration_text(script, detect_encoding=True)

    def test_utf8_still_wins(self, tmp_path):
        """Detection must not start guessing at single-byte encodings for valid UTF-8."""
        script = tmp_path / "V1__utf8.sql"
        script.write_bytes("INSERT INTO t VALUES ('café €');".encode("utf-8"))

        assert detect_file_encoding(script) == "utf-8"
        assert "€" in read_migration_text(script, detect_encoding=True)

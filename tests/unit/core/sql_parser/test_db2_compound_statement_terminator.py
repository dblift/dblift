"""DB2 compound bodies must survive a missing trailing statement terminator.

A migration whose final statement is a compound block — a trigger, a procedure
or a bare ``BEGIN ATOMIC`` block — is valid DB2 without a trailing ``;`` or
``@``. The parser must still keep the whole block together instead of cutting
it at the first semicolon inside the body.
"""

import pytest

from db.plugins.db2.parser.db2_regex_parser import DB2RegexParser

PRELUDE = "CREATE TABLE audit_log (id INTEGER, msg VARCHAR(100))"

TRIGGER_BODY = """CREATE TRIGGER trg_audit
AFTER INSERT ON employees
REFERENCING NEW AS n
FOR EACH ROW
BEGIN ATOMIC
    INSERT INTO audit_log (id, msg) VALUES (n.id, 'inserted');
    UPDATE counters SET c = c + 1;
END"""

PROCEDURE_BODY = """CREATE PROCEDURE do_thing(IN p INTEGER)
LANGUAGE SQL
BEGIN
    DECLARE v INTEGER;
    SET v = p + 1;
    INSERT INTO audit_log (id, msg) VALUES (v, 'done');
END"""

COMPOUND_BODY = """BEGIN ATOMIC
    INSERT INTO audit_log (id, msg) VALUES (1, 'a');
    UPDATE counters SET c = c + 1;
END"""

TERMINATORS = pytest.mark.parametrize("terminator", ["", ";", "@"], ids=["none", "semicolon", "at"])


@pytest.mark.unit
class TestDB2CompoundStatementTerminator:
    """The trailing terminator is optional on the last compound statement."""

    @TERMINATORS
    def test_trigger_body_is_one_statement(self, terminator):
        parser = DB2RegexParser()

        statements = parser.split_statements(f"{PRELUDE};\n\n{TRIGGER_BODY}{terminator}")

        assert statements == [PRELUDE, TRIGGER_BODY]

    @TERMINATORS
    def test_procedure_body_is_one_statement(self, terminator):
        parser = DB2RegexParser()

        statements = parser.split_statements(f"{PRELUDE};\n\n{PROCEDURE_BODY}{terminator}")

        assert statements == [PRELUDE, PROCEDURE_BODY]

    @TERMINATORS
    def test_compound_block_is_one_statement(self, terminator):
        parser = DB2RegexParser()

        statements = parser.split_statements(f"{PRELUDE};\n\n{COMPOUND_BODY}{terminator}")

        assert statements == [PRELUDE, COMPOUND_BODY]

    def test_unterminated_trigger_keeps_internal_semicolons(self):
        parser = DB2RegexParser()

        statements = parser.split_statements(TRIGGER_BODY)

        assert len(statements) == 1
        assert statements[0].count(";") == 2

    def test_unterminated_procedure_keeps_internal_semicolons(self):
        parser = DB2RegexParser()

        statements = parser.split_statements(PROCEDURE_BODY)

        assert len(statements) == 1
        assert statements[0].count(";") == 3


@pytest.mark.unit
class TestDB2CompoundBlockBoundaries:
    """A compound block ends at its own END, never at a later one.

    ``extract_compound_statements`` returns the span it matched, so unlike the
    boolean detection gates its boundary is what the splitter actually cuts on.
    """

    def test_unterminated_compound_does_not_swallow_a_trailing_case_expression(self):
        parser = DB2RegexParser()
        compound = "BEGIN ATOMIC\n  INSERT INTO audit_log VALUES (1);\nEND"
        query = "SELECT CASE WHEN id = 1 THEN 'x' ELSE 'y' END"

        statements = parser.split_statements(f"{compound}\n{query}")

        assert statements == [compound, query]

    def test_unterminated_compound_does_not_swallow_trailing_sql(self):
        parser = DB2RegexParser()
        compound = "BEGIN ATOMIC\n  INSERT INTO audit_log VALUES (1);\nEND"
        query = "SELECT * FROM audit_log"

        statements = parser.split_statements(f"{compound}\n{query}")

        assert statements == [compound, query]

    def test_two_compounds_with_the_second_unterminated(self):
        parser = DB2RegexParser()
        first = "BEGIN ATOMIC\n  INSERT INTO audit_log VALUES (1);\nEND"
        second = "BEGIN ATOMIC\n  UPDATE counters SET c = c + 1;\nEND"

        statements = parser.split_statements(f"{first};\n{second}")

        assert statements == [first, second]

    def test_case_expression_inside_a_compound_does_not_close_it(self):
        parser = DB2RegexParser()
        compound = (
            "BEGIN ATOMIC\n"
            "  SET g = CASE WHEN s > 90 THEN 'A' ELSE 'B' END;\n"
            "  INSERT INTO audit_log VALUES (g);\n"
            "END"
        )

        assert parser.split_statements(compound) == [compound]

    def test_nested_block_inside_a_compound_does_not_close_it(self):
        parser = DB2RegexParser()
        compound = (
            "BEGIN ATOMIC\n"
            "  BEGIN\n"
            "    INSERT INTO audit_log VALUES (1);\n"
            "  END;\n"
            "  UPDATE counters SET c = c + 1;\n"
            "END"
        )

        assert parser.split_statements(compound) == [compound]

    def test_end_if_inside_a_compound_does_not_close_it(self):
        parser = DB2RegexParser()
        compound = (
            "BEGIN ATOMIC\n"
            "  IF s = 1 THEN\n"
            "    INSERT INTO audit_log VALUES (1);\n"
            "  END IF;\n"
            "END"
        )

        assert parser.split_statements(compound) == [compound]

    def test_end_while_inside_a_compound_does_not_close_it(self):
        parser = DB2RegexParser()
        compound = """BEGIN ATOMIC
  WHILE s < 10 DO
    SET s = s + 1;
  END WHILE;
END"""

        assert parser.split_statements(compound) == [compound]


@pytest.mark.unit
class TestDB2CompoundDetectionStaysNarrow:
    """Ordinary statements ending in the word END must not be treated as blocks."""

    def test_insert_mentioning_end_is_not_a_block(self):
        parser = DB2RegexParser()
        sql = "INSERT INTO audit_log (id, msg) VALUES (1, 'the END')"

        assert not parser._has_sqlpl_blocks(sql)
        assert not parser._has_trigger_blocks(sql)
        assert parser.split_statements(sql) == [sql]

    def test_case_expression_ending_the_script_is_not_a_block(self):
        parser = DB2RegexParser()
        sql = "SELECT CASE WHEN id = 1 THEN 'x' ELSE 'y' END FROM audit_log"

        assert not parser._has_sqlpl_blocks(sql)
        assert not parser._has_trigger_blocks(sql)
        assert parser.split_statements(sql) == [sql]

    def test_external_procedure_followed_by_case_expression(self):
        parser = DB2RegexParser()
        external = "CREATE PROCEDURE ext_proc() LANGUAGE C EXTERNAL NAME 'lib!fn'"
        query = "SELECT CASE WHEN id = 1 THEN 'x' END FROM audit_log"

        statements = parser.split_statements(f"{external};\n{query}")

        assert statements == [external, query]

    def test_end_inside_string_and_comment_does_not_close_the_block(self):
        parser = DB2RegexParser()
        trigger = """CREATE TRIGGER trg_quoted
AFTER INSERT ON employees
REFERENCING NEW AS n
FOR EACH ROW
BEGIN ATOMIC
    -- END of the preamble; keep going
    INSERT INTO audit_log (id, msg) VALUES (n.id, 'END; of message');
    UPDATE counters SET c = c + 1;
END"""

        assert parser.split_statements(trigger) == [trigger]

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
class TestDB2CaseEndContinuations:
    """A CASE expression's ``END`` can be followed by almost anything.

    ``_find_block_end`` used to only recognise a CASE's closing ``END`` when
    the next token was ``;``, ``,`` or ``)``. Any other legal continuation —
    ``INTO``, ``AS``, or a bare ``FROM`` — was mistaken for the *enclosing*
    block's own ``END``, truncating the block early.
    """

    def test_case_end_into_inside_a_procedure_does_not_close_it(self):
        parser = DB2RegexParser()
        procedure = """CREATE PROCEDURE do_thing()
LANGUAGE SQL
BEGIN
    DECLARE v INTEGER;
    SELECT CASE WHEN id = 1 THEN 10 ELSE 20 END INTO v FROM t;
    INSERT INTO audit_log VALUES (v);
END"""

        assert parser.split_statements(procedure) == [procedure]

    def test_case_end_as_inside_a_procedure_does_not_close_it(self):
        parser = DB2RegexParser()
        procedure = """CREATE PROCEDURE do_thing()
LANGUAGE SQL
BEGIN
    DECLARE v VARCHAR(10);
    SET v = (SELECT CASE WHEN id = 1 THEN 'x' ELSE 'y' END AS label FROM t);
    INSERT INTO audit_log VALUES (v);
END"""

        assert parser.split_statements(procedure) == [procedure]

    def test_case_end_from_inside_a_procedure_does_not_close_it(self):
        parser = DB2RegexParser()
        procedure = """CREATE PROCEDURE do_thing()
LANGUAGE SQL
BEGIN
    DECLARE v INTEGER;
    SET v = (SELECT CASE WHEN id = 1 THEN 10 ELSE 20 END FROM t);
    INSERT INTO audit_log VALUES (v);
END"""

        assert parser.split_statements(procedure) == [procedure]

    def test_procedural_case_end_case_does_not_poison_the_enclosing_end(self):
        """A procedural ``CASE ... END CASE`` must not re-open a CASE depth.

        The scanner only advanced past the three letters of ``END`` when it
        recognised ``END CASE`` as closing the CASE statement, so the ``CASE``
        keyword right after it was re-read on the next iteration and matched
        by the generic CASE-expression-open detector - poisoning case_depth
        and making the block's own terminating ``END`` look like it belongs
        to a still-open CASE expression instead of closing the block.
        """
        parser = DB2RegexParser()
        procedure = """CREATE PROCEDURE classify(IN p_score INTEGER)
LANGUAGE SQL
BEGIN
    DECLARE v_grade CHAR(1);
    CASE
        WHEN p_score >= 90 THEN SET v_grade = 'A';
        WHEN p_score >= 80 THEN SET v_grade = 'B';
        ELSE SET v_grade = 'F';
    END CASE;
    INSERT INTO grades VALUES (v_grade);
END"""

        assert parser.split_statements(procedure) == [procedure]

    def test_end_case_immediately_followed_by_enclosing_end_with_semicolons(self):
        """A pre-existing bug that predates PR #115's condition widening.

        With explicit ``;`` terminators on both the CASE statement's own
        ``END CASE`` and the block's own ``END`` (``...END CASE; END;``),
        the block was already reported as unterminated before PR #115 - the
        same missing skip-past-the-matched-keyword after a recognised
        control-end poisons the scan here too, and the fix for the CASE
        self-poisoning regression above resolves it as a side effect.
        """
        parser = DB2RegexParser()
        procedure = """CREATE PROCEDURE classify(IN p_score INTEGER)
LANGUAGE SQL
BEGIN
    DECLARE v_grade CHAR(1);
    CASE
        WHEN p_score >= 90 THEN SET v_grade = 'A';
        ELSE SET v_grade = 'F';
    END CASE;
    INSERT INTO grades VALUES (v_grade);
END;"""

        assert parser.split_statements(procedure) == [procedure.rstrip(";")]


@pytest.mark.unit
class TestDB2EndControlKeywordSeparatorWhitespace:
    """The whitespace between ``END`` and a control keyword can be any SQL
    whitespace, not just a space or a tab.

    ``_find_block_end`` recognises ``END CASE``/``END IF``/... by skipping
    whitespace after ``END`` and reading the next word. That skip only
    checked ``sql[j] in (" ", "\\t")`` - a newline or CRLF between ``END``
    and the keyword defeated the lookahead entirely, so the control-end went
    unrecognised and was counted as the block's own terminating ``END``
    instead, truncating the block early (the same self-poisoning regression
    the previous round's fix addressed, reappearing for this input shape).
    """

    def test_end_case_separated_by_newline_is_still_recognised(self):
        from db.plugins.db2.parser.parser_config import DB2Config

        sql = "CREATE PROCEDURE p() BEGIN CASE x WHEN 1 THEN SET y=1; END\nCASE; END"

        assert DB2Config()._find_block_end(sql, sql.index("BEGIN")) == 68

    def test_end_case_separated_by_crlf_is_still_recognised(self):
        from db.plugins.db2.parser.parser_config import DB2Config

        sql = "CREATE PROCEDURE p() BEGIN CASE x WHEN 1 THEN SET y=1; END\r\nCASE; END"

        assert DB2Config()._find_block_end(sql, sql.index("BEGIN")) is not None

    SEPARATORS = pytest.mark.parametrize(
        "separator",
        [" ", "\t", "\n", "\r\n", "   ", " \n ", "\n\t"],
        ids=[
            "space",
            "tab",
            "newline",
            "crlf",
            "multi-space",
            "space-newline-space",
            "newline-tab",
        ],
    )

    KEYWORDS = pytest.mark.parametrize(
        "keyword,body",
        [
            ("CASE", "    CASE\n        WHEN x = 1 THEN SET y = 1;\n    END"),
            ("IF", "    IF x > 0 THEN\n        SET x = x + 1;\n    END"),
            ("WHILE", "    WHILE x < 10 DO\n        SET x = x + 1;\n    END"),
            (
                "LOOP",
                "    lbl: LOOP\n        SET x = x + 1;\n        IF x >= 10 THEN LEAVE lbl; END IF;\n    END",
            ),
            (
                "FOR",
                "    FOR v AS SELECT id FROM t DO\n        INSERT INTO log VALUES (v.id);\n    END",
            ),
            ("REPEAT", "    REPEAT\n        SET x = x + 1;\n    UNTIL x >= 10\n    END"),
        ],
        ids=["case", "if", "while", "loop", "for", "repeat"],
    )

    @SEPARATORS
    @KEYWORDS
    def test_end_keyword_recognised_across_separators(self, separator, keyword, body):
        parser = DB2RegexParser()
        procedure = (
            f"CREATE PROCEDURE p(IN x INTEGER)\n"
            f"LANGUAGE SQL\n"
            f"BEGIN\n"
            f"{body}{separator}{keyword};\n"
            f"    INSERT INTO t VALUES (x);\n"
            f"END"
        )

        assert parser.split_statements(procedure) == [procedure]


@pytest.mark.unit
class TestDB2ControlEndKeywordRequiresWordBoundary:
    """The keyword read after ``END`` must be a whole word, not a prefix.

    ``_find_block_end`` reads the word following ``END`` by scanning
    ``.isalpha()`` characters and comparing the result against the control
    keyword list. That scan has no *right-hand* word-boundary check, unlike
    the ``BEGIN``/``CASE``-open detectors earlier in the same function (which
    both check the character just past the match isn't alnum). So
    ``END IF1`` reads only ``IF`` (stopping at the digit), matches it as
    ``END IF``, and treats a CASE expression's real closing ``END`` as a
    control-structure end instead - leaving ``case_depth`` open and making
    the enclosing block's own terminating ``END`` look like it still belongs
    to that phantom-open CASE.
    """

    def test_end_immediately_followed_by_identifier_starting_with_if_is_not_end_if(self):
        from db.plugins.db2.parser.parser_config import DB2Config

        sql = (
            "CREATE PROCEDURE p(IN x INTEGER)\nLANGUAGE SQL\nBEGIN\n"
            "    SET x = (SELECT CASE WHEN x = 1 THEN 1 END IF1 FROM t);\n"
            "    SET x = x + 1;\nEND"
        )

        assert DB2Config()._find_block_end(sql, sql.index("BEGIN")) == len(sql)

    def test_case_expression_alias_starting_with_a_control_keyword_does_not_truncate_the_procedure(
        self,
    ):
        parser = DB2RegexParser()
        procedure = (
            "CREATE PROCEDURE p(IN x INTEGER)\nLANGUAGE SQL\nBEGIN\n"
            "    SET x = (SELECT CASE WHEN x = 1 THEN 1 END IF1 FROM t);\n"
            "    SET x = x + 1;\nEND"
        )

        assert parser.split_statements(procedure) == [procedure]

    @pytest.mark.parametrize(
        "alias",
        [
            "IF1",
            "LOOP2",
            "WHILE_FLAG",
            "CASE9",
            "FOR3",
            "REPEAT7",
            # DB2 also permits '#' and '$' in unquoted identifiers - the
            # word-boundary check has to recognise those as identifier
            # characters too, not just alnum/underscore.
            "IF#1",
            "LOOP$2",
        ],
    )
    def test_case_expression_alias_prefixed_by_a_control_keyword_does_not_truncate_the_procedure(
        self, alias
    ):
        parser = DB2RegexParser()
        procedure = (
            "CREATE PROCEDURE p(IN x INTEGER)\nLANGUAGE SQL\nBEGIN\n"
            f"    SET x = (SELECT CASE WHEN x = 1 THEN 1 END {alias} FROM t);\n"
            "    SET x = x + 1;\nEND"
        )

        assert parser.split_statements(procedure) == [procedure]

    @pytest.mark.parametrize("identifier", ["CASE_STATUS", "CASE9_FLAG", "CASE#X"])
    def test_identifier_prefixed_by_case_does_not_open_a_phantom_case_expression(self, identifier):
        """A variable/column named e.g. ``CASE_STATUS`` is not the ``CASE`` keyword.

        The ``CASE``-open detector's own word-boundary check had the same
        ``isalnum()``-only gap as the ``END``-lookahead above - it lives a
        few lines earlier in the same function and was never exercised by
        rounds 1-2, but it's the identical bug class.
        """
        parser = DB2RegexParser()
        procedure = f"CREATE PROCEDURE p(IN v INTEGER)\nLANGUAGE SQL\nBEGIN\n    SET v = {identifier} + 1;\nEND"

        assert parser.split_statements(procedure) == [procedure]

    @pytest.mark.parametrize("identifier", ["BEGIN_DATE", "BEGIN9_TS", "BEGIN#X"])
    def test_identifier_prefixed_by_begin_does_not_open_a_phantom_block(self, identifier):
        """A variable/column named e.g. ``BEGIN_DATE`` is not the ``BEGIN`` keyword.

        Same bug class as ``CASE_STATUS`` above, for the ``BEGIN``-open
        detector's word-boundary check.
        """
        parser = DB2RegexParser()
        procedure = f"CREATE PROCEDURE p(IN v INTEGER)\nLANGUAGE SQL\nBEGIN\n    SET v = {identifier} + 1;\nEND"

        assert parser.split_statements(procedure) == [procedure]


@pytest.mark.unit
class TestDB2ControlEndKeywordsDoNotSelfPoison:
    """``END IF``/``END WHILE``/``END LOOP``/``END FOR``/``END REPEAT`` are safe.

    The CASE self-poisoning bug above happens because CASE has *two* roles in
    the scanner: a generic CASE-expression-open detector (incrementing
    ``case_depth`` on any bare ``CASE`` token) and the control-end lookahead
    that recognises ``END CASE``. Re-scanning the word ``CASE`` after only
    skipping ``END`` therefore re-triggers the opener. IF/WHILE/FOR/LOOP/
    REPEAT have no such generic opener anywhere in ``_find_block_end`` - only
    ``BEGIN`` and ``CASE`` increment a depth counter - so re-scanning those
    keywords after their own control-end is inert. These tests pin that down
    so a future opener added for one of them doesn't silently reintroduce the
    same class of bug.
    """

    def test_end_if_does_not_poison_the_enclosing_end(self):
        parser = DB2RegexParser()
        procedure = """CREATE PROCEDURE p(IN x INTEGER)
LANGUAGE SQL
BEGIN
    IF x > 0 THEN
        SET x = x + 1;
    END IF;
    INSERT INTO t VALUES (x);
END"""

        assert parser.split_statements(procedure) == [procedure]

    def test_end_while_does_not_poison_the_enclosing_end(self):
        parser = DB2RegexParser()
        procedure = """CREATE PROCEDURE p(IN x INTEGER)
LANGUAGE SQL
BEGIN
    WHILE x < 10 DO
        SET x = x + 1;
    END WHILE;
    INSERT INTO t VALUES (x);
END"""

        assert parser.split_statements(procedure) == [procedure]

    def test_end_loop_does_not_poison_the_enclosing_end(self):
        parser = DB2RegexParser()
        procedure = """CREATE PROCEDURE p(IN x INTEGER)
LANGUAGE SQL
BEGIN
    lbl: LOOP
        SET x = x + 1;
        IF x >= 10 THEN
            LEAVE lbl;
        END IF;
    END LOOP;
    INSERT INTO t VALUES (x);
END"""

        assert parser.split_statements(procedure) == [procedure]

    def test_end_for_does_not_poison_the_enclosing_end(self):
        parser = DB2RegexParser()
        procedure = """CREATE PROCEDURE p()
LANGUAGE SQL
BEGIN
    FOR v AS SELECT id FROM t DO
        INSERT INTO log VALUES (v.id);
    END FOR;
    INSERT INTO t VALUES (1);
END"""

        assert parser.split_statements(procedure) == [procedure]

    def test_end_repeat_does_not_poison_the_enclosing_end(self):
        parser = DB2RegexParser()
        procedure = """CREATE PROCEDURE p(IN x INTEGER)
LANGUAGE SQL
BEGIN
    REPEAT
        SET x = x + 1;
    UNTIL x >= 10
    END REPEAT;
    INSERT INTO t VALUES (x);
END"""

        assert parser.split_statements(procedure) == [procedure]


@pytest.mark.unit
class TestDB2TriggerControlStructureLookahead:
    """Triggers must recognise ``END IF`` / ``END WHILE`` like other blocks.

    ``extract_trigger_blocks`` used to keep its own depth counter that
    decremented on *any* ``END``, with no lookahead for control structures.
    An ``IF ... END IF`` inside a trigger body therefore truncated the
    trigger early, even though the identical body works inside a procedure.
    """

    def test_end_if_inside_a_trigger_does_not_close_it(self):
        parser = DB2RegexParser()
        trigger = """CREATE TRIGGER trg_audit
AFTER INSERT ON employees
REFERENCING NEW AS n
FOR EACH ROW
BEGIN ATOMIC
    IF n.id > 0 THEN
        INSERT INTO audit_log (id, msg) VALUES (n.id, 'inserted');
    END IF;
    UPDATE counters SET c = c + 1;
END"""

        assert parser.split_statements(trigger) == [trigger]

    def test_identical_if_end_if_body_works_in_both_procedure_and_trigger(self):
        parser = DB2RegexParser()
        procedure = """CREATE PROCEDURE do_thing()
LANGUAGE SQL
BEGIN
    IF 1 > 0 THEN
        INSERT INTO audit_log VALUES (1);
    END IF;
    UPDATE counters SET c = c + 1;
END"""
        trigger = """CREATE TRIGGER trg_audit
AFTER INSERT ON employees
REFERENCING NEW AS n
FOR EACH ROW
BEGIN ATOMIC
    IF 1 > 0 THEN
        INSERT INTO audit_log VALUES (1);
    END IF;
    UPDATE counters SET c = c + 1;
END"""

        assert parser.split_statements(procedure) == [procedure]
        assert parser.split_statements(trigger) == [trigger]


@pytest.mark.unit
class TestDB2BlockDetectionGateAgreesWithExtractor:
    """A gate that accepts an input must have the extractor return one block.

    ``_has_sqlpl_blocks`` / ``_has_compound_statements`` / ``_has_trigger_blocks``
    decide whether ``split_statements`` treats the input as a block at all; the
    matching ``extract_*_blocks`` then has to actually find it. If the gate says
    yes and the extractor comes back empty (or splits it into more than one
    piece), the block silently falls through to semicolon-splitting and gets
    truncated — exactly how both bugs above were previously invisible to the
    boolean gates.
    """

    @pytest.mark.parametrize(
        "sql",
        [
            "CREATE PROCEDURE p() LANGUAGE SQL BEGIN SELECT 1; END;",
            "CREATE PROCEDURE p() LANGUAGE SQL BEGIN SELECT CASE WHEN 1=1 THEN 1 END INTO v FROM t; END",
            "CREATE FUNCTION f() RETURNS INTEGER LANGUAGE SQL BEGIN RETURN 1; END;",
        ],
    )
    def test_sqlpl_gate_agrees_with_extractor(self, sql):
        parser = DB2RegexParser()
        assert parser._has_sqlpl_blocks(sql)
        assert len(parser.config.extract_sqlpl_blocks(sql)) == 1

    @pytest.mark.parametrize(
        "sql",
        [
            "BEGIN ATOMIC SELECT 1; END;",
            "BEGIN ATOMIC SELECT CASE WHEN 1=1 THEN 1 END FROM t; END",
            "BEGIN ATOMIC IF 1=1 THEN SELECT 1; END IF; END;",
        ],
    )
    def test_compound_gate_agrees_with_extractor(self, sql):
        parser = DB2RegexParser()
        assert parser._has_compound_statements(sql)
        assert len(parser.config.extract_compound_statements(sql)) == 1

    @pytest.mark.parametrize(
        "sql",
        [
            "CREATE TRIGGER t AFTER INSERT ON tbl FOR EACH ROW BEGIN ATOMIC SELECT 1; END;",
            "CREATE TRIGGER t AFTER INSERT ON tbl FOR EACH ROW "
            "BEGIN ATOMIC IF 1=1 THEN SELECT 1; END IF; END;",
        ],
    )
    def test_trigger_gate_agrees_with_extractor(self, sql):
        parser = DB2RegexParser()
        assert parser._has_trigger_blocks(sql)
        assert len(parser.config.extract_trigger_blocks(sql)) == 1


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

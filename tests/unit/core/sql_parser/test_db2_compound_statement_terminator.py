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

    def test_nbsp_between_end_and_control_keyword_is_not_treated_as_separator(self):
        """A non-breaking space (U+00A0) is not DB2 whitespace.

        DB2's lexer rejects ``END<NBSP>WHILE`` with a syntax error - unlike
        an ordinary space, tab, or newline, NBSP is not a legal separator
        between ``END`` and a control keyword. ``_find_block_end`` doesn't
        validate DB2 syntax, it only locates block boundaries, so the
        correct behaviour here isn't to raise: the lookahead simply doesn't
        skip the NBSP, doesn't recognise "WHILE" as following it, and falls
        through to treating this ``END`` as the block's own terminating
        ``END`` - closing the block right there, before the real one.
        """
        from db.plugins.db2.parser.parser_config import DB2Config

        sql = (
            "CREATE PROCEDURE p(IN x INTEGER)\nLANGUAGE SQL\nBEGIN\n"
            "    WHILE x < 10 DO\n"
            "        SET x = x + 1;\n"
            "    END WHILE;\n"
            "    INSERT INTO t VALUES (x);\n"
            "END"
        )
        inner_end = sql.index("END WHILE")

        end_pos = DB2Config()._find_block_end(sql, sql.index("BEGIN"))

        assert end_pos == inner_end + 3


@pytest.mark.unit
class TestDB2EndKeywordRequiresRightWordBoundary:
    """The literal ``END`` match itself needs a right-hand word boundary too.

    ``_find_block_end``'s ``BEGIN``- and ``CASE``-open detectors already check
    both sides of their match (the character before *and* the character just
    past it isn't an identifier character). The ``END`` detector only ever
    checked the left side. So an identifier that merely *starts* with the
    letters ``END`` - ``ENDDATE``, ``END_IF``, ``ENDLESS``, ``ENDPOINT``,
    ``ENDCASE`` - had its first three characters mistaken for a genuine
    closing ``END`` token, corrupting ``depth``/``case_depth`` mid-scan and
    truncating the rest of the block. Confirmed live on DB2 12.1: a procedure
    declaring ``ENDDATE`` as a variable name compiles and runs unmodified.
    """

    def test_variable_named_enddate_does_not_truncate_the_procedure(self):
        from db.plugins.db2.parser.parser_config import DB2Config

        sql = """CREATE PROCEDURE P1()
BEGIN
  DECLARE ENDDATE DATE;
  SET ENDDATE = CURRENT DATE;
  SELECT 1 FROM SYSIBM.SYSDUMMY1;
END
"""

        assert DB2Config()._find_block_end(sql, sql.index("BEGIN")) == len(sql)

    def test_variable_named_enddate_survives_split_statements(self):
        parser = DB2RegexParser()
        procedure = """CREATE PROCEDURE P1()
BEGIN
  DECLARE ENDDATE DATE;
  SET ENDDATE = CURRENT DATE;
  SELECT 1 FROM SYSIBM.SYSDUMMY1;
END"""

        assert parser.split_statements(procedure) == [procedure]

    @pytest.mark.parametrize(
        "identifier",
        [
            "ENDDATE",
            "END_IF",
            "ENDLESS",
            "ENDPOINT",
            "ENDCASE",
            # DB2 also permits '#' and '$' in unquoted identifiers.
            "END#X",
            "END$Y",
        ],
    )
    def test_identifier_starting_with_end_does_not_truncate_the_procedure(self, identifier):
        parser = DB2RegexParser()
        procedure = f"CREATE PROCEDURE p(IN v INTEGER)\nLANGUAGE SQL\nBEGIN\n    SET v = {identifier} + 1;\nEND"

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
            # Whole extra words glued on with no separator at all, not just
            # a single trailing character - the lookahead reads the entire
            # alpha run before comparing, so these must be rejected too.
            "IFSTATUS",
            "WHILECOUNT",
            "LOOPINDEX",
            "FORNAME",
            "REPEATCOUNT",
            "CASETYPE",
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

    @pytest.mark.parametrize("identifier", ["CASE_STATUS", "CASE9_FLAG", "CASE#X", "CASETYPE"])
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

    @pytest.mark.parametrize("identifier", ["BEGIN_DATE", "BEGIN9_TS", "BEGIN#X", "BEGINDATE"])
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
            # Confirmed live against DB2 12.1.5.0: a trigger body may open
            # with plain BEGIN (no ATOMIC) and compiles/fires correctly, so
            # the gate is right to accept it - the extractor used to require
            # literal "BEGIN ATOMIC" and silently skip this shape instead.
            "CREATE TRIGGER t AFTER INSERT ON tbl FOR EACH ROW BEGIN SELECT 1; END;",
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


@pytest.mark.unit
class TestDB2CommentDetectorsRespectInComment:
    """``--`` must not be recognised as a fresh line-comment opener while a
    block comment is already open; ``/*`` must be, because DB2 nests block
    comments.

    ``_find_block_end`` used to guard its ``--`` and ``/*`` detectors with
    only ``not in_string`` - unlike the ``*/`` detector, which was correctly
    guarded with ``and in_comment``. A dashed divider line (a common
    convention for a section header inside a block comment, e.g. a decorative
    ``-- ----------`` rule) was mistaken for the start of a *new* line
    comment, which skips to end-of-line. If the real closing ``*/`` sits on
    that same line, the scan jumped clean over it and the comment state never
    closed, leaving the whole rest of the block unterminated. ``--`` is fixed
    by ignoring it while already inside a block comment (line comments don't
    nest). ``/*`` is fixed the other way: confirmed live against DB2 12.1.5.0,
    block comments genuinely nest, so a ``/*`` seen while already inside a
    comment must open another level rather than being ignored - see
    ``comment_depth`` in ``_find_block_end``.
    """

    def test_dashes_immediately_before_closing_marker_do_not_truncate(self):
        parser = DB2RegexParser()
        sql = """CREATE PROCEDURE P1()
BEGIN
  /* --------------------------------------------------
     Procedure description
     -------------------------------------------------- */
  SELECT 1 FROM SYSIBM.SYSDUMMY1;
END"""

        assert parser.split_statements(sql) == [sql]

    def test_dashes_mid_comment_not_on_the_closing_line_do_not_truncate(self):
        """The same class of bug, without the same-line jump-over: the ``--``
        content appears well before the ``*/`` that ends the comment, on a
        line of its own with ordinary prose after it."""
        parser = DB2RegexParser()
        sql = """CREATE PROCEDURE P1()
BEGIN
  /* -- this dash marks a sub-heading, not a real line comment
     Procedure description continues here.
  */
  SELECT 1 FROM SYSIBM.SYSDUMMY1;
END"""

        assert parser.split_statements(sql) == [sql]

    def test_nested_block_comment_stays_open_until_the_balancing_close(self):
        """DB2 block comments nest - confirmed live against DB2 12.1.5.0: a
        ``CREATE PROCEDURE`` body containing ``/* outer /* inner */ garbage
        */`` compiles and runs, while the same ``garbage`` text left exposed
        by a single-level comment (no inner ``/*``) fails to compile as
        invalid SQL. So a ``/*`` written while a block comment is already
        open must start a *deeper* comment level, and only the ``*/`` that
        balances the outermost ``/*`` may close it - the first ``*/``
        encountered (which only balances the inner ``/*``) must not end the
        comment early."""
        parser = DB2RegexParser()
        sql = """CREATE PROCEDURE P1()
BEGIN
  /* outer /* inner */ garbage_that_would_be_invalid_sql_if_exposed */
  SELECT 1 FROM SYSIBM.SYSDUMMY1;
END"""

        assert parser.split_statements(sql) == [sql]

    def test_unbalanced_nested_block_comment_is_correctly_unterminated(self):
        """The flip side of nesting: a second ``/*`` without a matching
        second ``*/`` leaves the outer comment level open, so the block
        really is unterminated - matching live DB2, which refuses to
        compile this exact body (missing closing comment)."""
        sql = """CREATE PROCEDURE P1()
BEGIN
  /* looks like nesting: /* inner */ still inside the outer comment
  SELECT 1 FROM SYSIBM.SYSDUMMY1;
END"""

        from db.plugins.db2.parser.parser_config import DB2Config

        assert DB2Config()._find_block_end(sql, sql.index("BEGIN")) is None

    def test_standalone_line_comment_outside_a_block_comment_still_works(self):
        """Ordinary ``--`` line comments, entirely outside any block comment,
        must keep skipping to end-of-line as before."""
        parser = DB2RegexParser()
        sql = """CREATE PROCEDURE P1()
BEGIN
  -- plain line comment, no block comment involved
  SELECT 1 FROM SYSIBM.SYSDUMMY1;
END"""

        assert parser.split_statements(sql) == [sql]


@pytest.mark.unit
class TestDB2TriggerCaseTracking:
    """A CASE expression inside a trigger body must not truncate it.

    ``extract_trigger_blocks`` used to keep a private depth counter that
    decremented on any ``END``, with no CASE-expression awareness - unlike
    ``extract_sqlpl_blocks``, which tracked ``case_depth`` via the shared
    ``_find_block_end`` scan procedures and compound statements already used.
    A ``CASE ... END`` inside a trigger body closed the trigger's own block
    early instead of just closing the CASE expression. Both extractors now
    delegate to ``_find_block_end``, so this is confirmed live against DB2
    12.1.5.0 and is a regression lock, not a live bug.
    """

    def test_case_expression_inside_a_trigger_does_not_close_it(self):
        parser = DB2RegexParser()
        trigger = """CREATE TRIGGER trg_audit
AFTER INSERT ON employees
REFERENCING NEW AS n
FOR EACH ROW
BEGIN ATOMIC
    INSERT INTO audit_log (id, msg) VALUES (n.id, CASE WHEN n.id > 0 THEN 'pos' ELSE 'neg' END);
    UPDATE counters SET c = c + 1;
END"""

        assert parser.split_statements(trigger) == [trigger]


@pytest.mark.unit
class TestDB2TriggerPlainBeginIsExtracted:
    """A trigger body may open with plain ``BEGIN``, not just ``BEGIN ATOMIC``.

    Confirmed live against DB2 12.1.5.0: a trigger declared with a bare
    ``BEGIN ... END`` (no ``ATOMIC``) compiles and fires correctly - DB2 does
    not require a trigger's compound statement to be atomic. ``_has_trigger_
    blocks`` already accepted plain ``BEGIN`` (the gate was right), but
    ``extract_trigger_blocks`` required the literal keyword ``ATOMIC`` and
    silently skipped any trigger that lacked it, dropping the whole trigger
    to naive semicolon splitting and truncating it at its first internal
    ``;`` - even with a trailing ``;`` present, so this one was never
    delimiter-dependent.
    """

    @TERMINATORS
    def test_plain_begin_trigger_is_one_statement(self, terminator):
        parser = DB2RegexParser()
        trigger = """CREATE TRIGGER trg_audit
AFTER INSERT ON employees
REFERENCING NEW AS n
FOR EACH ROW
BEGIN
    INSERT INTO audit_log (id, msg) VALUES (n.id, 'inserted');
    UPDATE counters SET c = c + 1;
END"""

        assert parser.split_statements(f"{trigger}{terminator}") == [trigger]

    def test_plain_begin_trigger_with_control_structure_does_not_truncate(self):
        """The same control-structure lookahead already proven for
        ``BEGIN ATOMIC`` triggers must hold for plain ``BEGIN`` too, since
        both now resolve their boundary through the same ``_find_block_end``
        scan once the extractor stops requiring ``ATOMIC``."""
        parser = DB2RegexParser()
        trigger = """CREATE TRIGGER trg_audit
AFTER INSERT ON employees
REFERENCING NEW AS n
FOR EACH ROW
BEGIN
    IF n.id > 0 THEN
        INSERT INTO audit_log (id, msg) VALUES (n.id, 'inserted');
    END IF;
    UPDATE counters SET c = c + 1;
END"""

        assert parser.split_statements(trigger) == [trigger]


@pytest.mark.unit
class TestDB2TrailingCommentAfterEndDoesNotDefeatTheGate:
    """A comment after the block's closing ``END`` must not defeat detection.

    ``_has_sqlpl_blocks`` and ``_has_trigger_blocks`` anchor their closing
    ``END`` on a delimiter (``@``/``;``) or the true end of input, mirroring
    the 'terminator optional on the final statement' handling the extractors
    already give an undelimited ``END``. Trailing whitespace after that
    ``END`` was already fine, but a trailing comment is not whitespace, so
    the gate's ``$`` anchor never matched and the whole block silently fell
    back to naive semicolon splitting - cutting the body at its first
    internal ``;``. ``_find_block_end``, which the extractors delegate to for
    the actual boundary, was never the problem: it already stops right after
    ``END`` and never swallows a trailing comment into the block's content.
    """

    def test_line_comment_after_procedure_end_does_not_defeat_the_gate(self):
        parser = DB2RegexParser()
        sql = f"{PROCEDURE_BODY}\n-- done\n"

        assert parser.split_statements(sql) == [PROCEDURE_BODY]

    def test_block_comment_after_procedure_end_does_not_defeat_the_gate(self):
        parser = DB2RegexParser()
        sql = f"{PROCEDURE_BODY}\n/* done */\n"

        assert parser.split_statements(sql) == [PROCEDURE_BODY]

    def test_comment_with_no_trailing_newline_after_end_does_not_defeat_the_gate(self):
        parser = DB2RegexParser()
        sql = f"{PROCEDURE_BODY}\n-- done"

        assert parser.split_statements(sql) == [PROCEDURE_BODY]

    def test_line_comment_after_trigger_end_does_not_defeat_the_gate(self):
        parser = DB2RegexParser()
        sql = f"{TRIGGER_BODY}\n-- done\n"

        assert parser.split_statements(sql) == [TRIGGER_BODY]

    def test_trailing_comment_after_an_explicit_delimiter_still_works(self):
        """Not just an omitted delimiter followed by a comment - a real
        delimiter followed by a comment must keep working too, since the
        ``[@;]`` branch of the anchor was never the broken one."""
        parser = DB2RegexParser()
        sql = f"{PROCEDURE_BODY};\n-- done\n"

        assert parser.split_statements(sql) == [PROCEDURE_BODY]

"""What the MySQL and MariaDB quirks name as an empty statement."""

from dataclasses import replace

import pytest

from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mysql.quirks import MysqlQuirks

pytestmark = pytest.mark.unit

SERVER_BLANKS = " \t\n\r\x0b\x0c"
CONTROLS = "".join(map(chr, range(1, 32))) + "\x7f"


def test_mysql_sends_a_statement_led_by_a_control_character_and_a_comment():
    # The mysql client strips trailing controls only: the parser drops a statement made of them, and
    # `<U+001C> -- c` is sent (the server answers 1064).
    assert set(MysqlQuirks().empty_statement_blanks()) == set(SERVER_BLANKS)


def test_mariadb_reads_a_control_character_as_blank_in_a_statement_of_comments():
    # The mariadb client does not send `<U+001C> -- c`; measured on MariaDB 11.8.8.
    blanks = MariadbQuirks().empty_statement_blanks()
    assert set(blanks) == set(SERVER_BLANKS + CONTROLS)
    assert "\x00" not in blanks and "\xa0" not in blanks


def test_mysql_reads_its_own_lexical_spec():
    spec = replace(MysqlQuirks().lexical_spec(), text_blanks=" \x1d")

    class Probe(MysqlQuirks):
        def lexical_spec(self):
            return spec

    assert Probe().empty_statement_blanks() == " \x1d"


def test_mariadb_reads_its_own_lexical_spec():
    spec = replace(MariadbQuirks().lexical_spec(), trailing_blanks=" \x1d")

    class Probe(MariadbQuirks):
        def lexical_spec(self):
            return spec

    assert Probe().empty_statement_blanks() == " \x1d"

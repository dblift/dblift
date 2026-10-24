"""MariaDB lexical facts from docs/sql-parsing/mariadb.md: the mysql rules, and what differs."""

from dataclasses import replace

from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_RULES, MYSQL_SPEC

MARIADB_SPEC = replace(
    MYSQL_SPEC,
    name="mariadb",
    client_name="mariadb",
    refused_reason="the mariadb client refuses it unless --binary-mode is set",
    # the mariadb client sends no statement made only of a control character and comments
    comment_adjacent_blanks="".join(map(chr, range(1, 32))) + "\x7f",
    delimiter_script=replace(
        MYSQL_RULES, executable_openers=("/*!", "/*M!"), hint_opening_line_only=False
    ),
)

"""MariaDB statement splitter: the MySQL one, reading MariaDB's executable comment."""

from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.db.plugins.mariadb.lexical_spec import MARIADB_SPEC
from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser


class MariaDbRegexParser(MySqlRegexParser):
    """``/*M! ... */`` runs on MariaDB (it is a comment to MySQL), so the client does not skip it."""

    dialect_name = "mariadb"  # lint: allow-dialect-string: dialect dispatch
    _splitter_spec: LexicalSpec = MARIADB_SPEC

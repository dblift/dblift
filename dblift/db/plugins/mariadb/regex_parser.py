"""MariaDB statement splitter: the MySQL one, reading MariaDB's executable comment."""

from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser


class MariaDbRegexParser(MySqlRegexParser):
    """``/*M! ... */`` runs on MariaDB (it is a comment to MySQL), so the client does not skip it."""

    dialect_name = "mariadb"  # lint: allow-dialect-string: dialect dispatch
    MARIADB = True

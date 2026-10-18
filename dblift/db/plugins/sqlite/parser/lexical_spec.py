"""SQLite lexical facts from docs/sql-parsing/sqlite.md."""

from dblift.core.sql_parser.lexical_spec import LexicalSpec

# sqlite3_complete's seven token classes: ;, other, EXPLAIN, CREATE,
# TEMP/TEMPORARY, TRIGGER, END. Row zero is unused.
SQLITE_SPEC = LexicalSpec(
    name="sqlite",
    text_blanks=" \t\n\r\f",
    client_name="sqlite3 shell",
    sqlite_shell=True,
    completion_table=(
        (),
        (1, 2, 3, 4, 2, 2, 2),
        (1, 2, 2, 2, 2, 2, 2),
        (1, 3, 2, 4, 2, 2, 2),
        (1, 2, 2, 2, 4, 5, 2),
        (6, 5, 5, 5, 5, 5, 5),
        (6, 5, 5, 5, 5, 5, 7),
        (1, 5, 5, 5, 5, 5, 5),
    ),
)

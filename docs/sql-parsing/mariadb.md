# MariaDB — where the statement splitter differs from MySQL

## Status

| Item | Value |
| --- | --- |
| Covers | MariaDB 11.8.8, read through the `mariadb` command-line client 15.2 (the only version measured: other versions, 10.5 to 11.7 and later, are extrapolated) |
| Relation to [mysql.md](mysql.md) | mysql.md is normative for both engines; this file lists only what MariaDB does differently and the conformance rows for it. A script that uses none of the constructs below splits the same way on both |
| Code facts taken from | OSS `develop` `1b64d02` (2026-10-15): MariaDB has its own lexical specification, the MySQL rules with the differences below (`mariadb/lexical_spec.py`); the pieces without code and the statement records at OSS `develop` `48051ff` (2026-10-19) |
| Live verification | measured 2026-10-11 with `mariadb from 11.8.8-MariaDB, client 15.2 for debian-linux-gnu (aarch64)` against MariaDB 11.8.8-MariaDB-ubu2404, the same set of scripts as the MySQL measurements (778 scripts, run on both engines). Every "measured 2026-10-11" cell below is that pair |
| Engine subclass | none: the MySQL rules with `/*M!` read as code and a hint read as a comment across lines are data of the shared lexical tokenizer |

## 1-9. What changes with MariaDB

Everything in [mysql.md](mysql.md) §1-§9 holds, except:

| Topic | MySQL (mysql 8.0.46) | MariaDB (mariadb 11.8.8) | Splitter |
| --- | --- | --- | --- |
| `/*M!NNNNNN … */`, `/*M! … */` | a plain block comment: stripped by the client, hides a delimiter, dropped when it stands alone (mysql.md row 16) | an executable comment: kept, the delimiter splits inside it (rows M1, M2); the server runs it when the number is not above its own (`/*M!100500 …*/` runs, `/*M!999999 …*/` does not; measured 2026-10-11) | follows the engine: with the `mariadb` dialect `/*M!` is read like `/*!`; with `mysql` it is a plain comment |
| `/*+ … */` | the client keeps the hint in the statement and hides the delimiter on the line that opens the hint only (rows 39a-39c) | the client strips the hint and reads it as a comment across lines (row M7) | one rule per dialect; a backslash inside is refused |
| `"…"` under `ANSI_QUOTES` | the client reads a string with backslash escapes | the client follows `ANSI_QUOTES` (a backslash is no escape inside `"…"`) | the mysql reading; unsupported, mysql.md §11 |
| client commands | `resetconnection`, `query_attributes`, `ssl_session_data_print` and `\x` are commands | the first three are text for the server (error 1064); `\x` is an unknown command (the client prints `Unknown command '\x'.` and stops, exit code 1); `\Q` is a command (and an unknown one on mysql) | refused on both engines |
| `DELIMITER ''` and `DELIMITER '` | prints an error, keeps the old delimiter, exit code 0 | sends the line to the server as text (error 1064, exit code 1); `DELIMITER` and `DELIMITER;` print the same bare error as mysql | refused on both |
| `\N` outside a string | text; the server rejects it | text; the server reads NULL | text on both |
| several statements in one query | allowed by the client's connection | allowed by the client's connection | sent as one query (mysql.md row 27) |
| stored-program syntax | — | `CREATE OR REPLACE PROCEDURE\|FUNCTION\|TRIGGER`, `CREATE AGGREGATE FUNCTION`, `FOR i IN a..b DO … END FOR`, `BEGIN NOT ATOMIC … END` | the first three are in the §5 head and block rules (rows M3-M6); `BEGIN NOT ATOMIC` is not a stored program (mysql.md row 79) |

## 10. Conformance examples

| # | Script | Statements returned |
| --- | --- | --- |
| M1 | `/*M!100500 SELECT 1 */; SELECT 2;` | `/*M!100500 SELECT 1 */` · `SELECT 2` MariaDB runs /*M! code, the client keeps it as a statement (on mysql the same text is a plain comment, mysql.md row 16) |
| M2 | `SELECT 1 /*M! ; */ + 1; SELECT 2;` | `SELECT 1 /*M!` · `*/ + 1` · `SELECT 2` the client splits inside /*M! as it does inside /*!; the server rejects the first two statements |
| M3 | `CREATE OR REPLACE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END; SELECT 3;` | `CREATE OR REPLACE PROCEDURE p() BEGIN SELECT 1; SELECT 2; END` · `SELECT 3` extension (§5) |
| M4 | `CREATE OR REPLACE TRIGGER tr BEFORE INSERT ON t FOR EACH ROW BEGIN SET NEW.id = 1; END; SELECT 2;` | `CREATE OR REPLACE TRIGGER tr BEFORE INSERT ON t FOR EACH ROW BEGIN SET NEW.id = 1; END` · `SELECT 2` extension (§5) |
| M5 | `CREATE AGGREGATE FUNCTION agg(x INT) RETURNS INT BEGIN DECLARE total INT DEFAULT 0; DECLARE CONTINUE HANDLER FOR NOT FOUND RETURN total; LOOP FETCH GROUP NEXT ROW; SET total = total + x; END LOOP; END; SELECT 1;` | `CREATE AGGREGATE FUNCTION agg(x INT) RETURNS INT BEGIN DECLARE total INT DEFAULT 0; DECLARE CONTINUE HANDLER FOR NOT FOUND RETURN total; LOOP FETCH GROUP NEXT ROW; SET total = total + x; END LOOP; END` · `SELECT 1` extension (§5) |
| M6 | `CREATE PROCEDURE p() BEGIN FOR i IN 1..3 DO SELECT i; END FOR; END; SELECT 2;` | `CREATE PROCEDURE p() BEGIN FOR i IN 1..3 DO SELECT i; END FOR; END` · `SELECT 2` extension (§5): END FOR closes the FOR loop |
| M7 | `SELECT /*+\n NO_BKA(t1) ;\n*/ 1 AS a;\nSELECT 2 AS b;` | `SELECT /*+\n NO_BKA(t1) ;\n*/ 1 AS a` · `SELECT 2 AS b` the mariadb client reads a hint as a comment across lines and hides the delimiter everywhere in it (mysql.md row 39a has the MySQL reading) |
| M8 | `SELECT 1;\n\x1c # c\n;\nSELECT 2;` | `SELECT 1` · `SELECT 2` (the mariadb client reads a control character as a blank when it decides that a piece holds nothing but blanks and comments, so the piece is not sent, while the mysql client sends it, mysql.md rows 86f to 86j; U+001C and a hash comment; measured 2026-10-19 with the mariadb client 15.2 against MariaDB 11.8.8, the statements the server received read from the general log) |
| M9 | `SELECT 1;\n\x1c -- c\n;\nSELECT 2;` | `SELECT 1` · `SELECT 2` (the mariadb client reads a control character as a blank when it decides that a piece holds nothing but blanks and comments, so the piece is not sent, while the mysql client sends it, mysql.md rows 86f to 86j; U+001C and a dash comment; measured 2026-10-19 with the mariadb client 15.2 against MariaDB 11.8.8, the statements the server received read from the general log) |
| M10 | `SELECT 1;\n\x1c /* c */\n;\nSELECT 2;` | `SELECT 1` · `SELECT 2` (the mariadb client reads a control character as a blank when it decides that a piece holds nothing but blanks and comments, so the piece is not sent, while the mysql client sends it, mysql.md rows 86f to 86j; U+001C and a block comment; measured 2026-10-19 with the mariadb client 15.2 against MariaDB 11.8.8, the statements the server received read from the general log) |
| M11 | `SELECT 1;\n\x01 # c\n;\nSELECT 2;` | `SELECT 1` · `SELECT 2` (the mariadb client reads a control character as a blank when it decides that a piece holds nothing but blanks and comments, so the piece is not sent, while the mysql client sends it, mysql.md rows 86f to 86j; U+0001 and a hash comment; measured 2026-10-19 with the mariadb client 15.2 against MariaDB 11.8.8, the statements the server received read from the general log) |
| M12 | `SELECT 1;\n\x7f # c\n;\nSELECT 2;` | `SELECT 1` · `SELECT 2` (the mariadb client reads a control character as a blank when it decides that a piece holds nothing but blanks and comments, so the piece is not sent, while the mysql client sends it, mysql.md rows 86f to 86j; U+007F and a hash comment; measured 2026-10-19 with the mariadb client 15.2 against MariaDB 11.8.8, the statements the server received read from the general log) |
| M13 | `SELECT 1;\nSELECT /* a\x00b */ 2;` | `UnsafeStatementSplitError` the refusal applies to the whole script, including a NUL in a comment. Measured 2026-10-20: the default mariadb 15.2 client refuses NUL and drops the suffix; with `--binary-mode`, and through PyMySQL 1.2, a NUL in a literal or comment and the following statement reach MariaDB 11.8.8. A bare NUL sent through PyMySQL gets server error 1064. The splitter keeps the strict refusal independently of client mode |

## 11. Not handled

The list of mysql.md §11 applies. MariaDB's Oracle-compatibility mode (`sql_mode=ORACLE`: `/` terminators, PL/SQL-style bodies) is not modelled and not measured.

## 12. Current implementation

The MariaDB rules apply to a `mariadb+pymysql://` URL; `mysql+pymysql://` selects the MySQL rules, also against a MariaDB server. Same code as mysql.md section 12: `dblift/db/plugins/mariadb/lexical_spec.py` holds `MARIADB_SPEC`, the MySQL rules with `/*M!` as a second executable opener and a hint read as a block comment, `MariadbQuirks.lexical_spec()` returns it. Statement facts are read by the same reader as MySQL, from the `mysql` grammar, after the MariaDB rules have split the script: through the `mariadb` plugin a `/*M! … */` comment is therefore a statement of its own, reported with no objects; through the `mysql` plugin it is a plain comment and no statement at all.

Two statement forms MariaDB runs and the reader leaves without an object, by design (measured 2026-10-24 on MariaDB 11.8.8; the reasons are in mysql.md section 12): a compound statement outside a stored program (`WHILE … END WHILE`, `IF … END IF`) and dynamic SQL (`EXECUTE IMMEDIATE '…'`, whose object is inside a string). `ALTER SEQUENCE` is named, as `CREATE SEQUENCE` and `DROP SEQUENCE` are; `CREATE`, `ALTER` and `DROP TABLESPACE` are MySQL statements that MariaDB rejects with error 1064, and the shared reader still names the tablespace.


CTE-led DML shares MySQL's reading. MariaDB 11 accepted `INSERT INTO t WITH … SELECT` and `INSERT INTO t (WITH … SELECT …)` and answered 1064 to `WITH … INSERT`, `WITH … UPDATE`, `WITH … DELETE` and to a CTE whose body is a `DELETE`; the reader still reads the rejected forms from the `mysql` grammar.

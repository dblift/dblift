# Oracle SQL*Plus Directives

Oracle `.sql` migration scripts often include SQL*Plus client directives —
`SET`, `DEFINE`, `PROMPT`, `WHENEVER SQLERROR`, `@script.sql`, and similar
lines. Those commands are valid in the SQL*Plus client. They are not valid
statements for the native Oracle driver.

DBLift is **not** SQL*Plus and does not invoke the SQL*Plus binary. When the
Oracle dialect is active, it preprocesses recognized directives so native
driver execution does not choke on client-only commands.

Prefer plain SQL plus [DBLift placeholders](commands.md#using-migration-placeholders)
for new migrations. SQL*Plus support exists so existing Oracle scripts can
run without a full rewrite.

## What is filtered

Most recognized directives are **dropped** before the statement is sent to
the Oracle driver. They are not executed as SQL.

| Directive | Typical forms |
|---|---|
| `SET` | `SERVEROUTPUT`, `LINESIZE`, `PAGESIZE`, `FEEDBACK`, `ECHO`, `VERIFY`, `HEADING`, `DEFINE`, `NULL`, `TERMOUT`, `SCAN`, `SUFFIX`, `FLAGGER`, `ESCAPE`, `TIME`, `TIMING` — not bare `SET ROLE` |
| `SHOW` | `ERRORS` / `ERROR`, `ALL`, `USER`, `LINESIZE`, `PAGESIZE`, `SERVEROUTPUT` |
| `SPOOL` | `SPOOL output.log`, `SPOOL OFF` |
| `WHENEVER OSERROR` | `WHENEVER OSERROR EXIT`, `WHENEVER OSERROR CONTINUE` |
| `PROMPT` | `PROMPT Starting migration` |
| `ACCEPT` | `ACCEPT schema_name CHAR PROMPT 'Schema: '` |
| `REM` / `REMARK` | Comment lines |
| `DEFINE` / `UNDEFINE` | `DEFINE schema = APP` |
| `COLUMN` / `COL` | `COLUMN name FORMAT A30` |
| `TIMING` | `TIMING START migration` |
| `CONNECT` / `CONN` | `CONNECT user/pass@db` — not `CONNECT TO` DDL |
| `DISCONNECT` | |
| `EXIT` / `QUIT` | |
| `DESC` / `DESCRIBE` | `DESC users` |
| `HOST` / `!` | `HOST ls -l`, `! ls` |
| `@` / `@@` | `@script.sql`, `@@nested.sql` |
| `EXEC` / `EXECUTE` | `EXEC dbms_output.put_line('hi')` |
| `CLEAR` | `CLEAR SCREEN` |
| `BREAK` / `COMPUTE` | |
| `TTITLE` / `BTITLE` | |
| `REPHEADER` / `REPFOOTER` | |
| `VARIABLE` / `PRINT` | |
| `PAUSE` | |

Filtered does **not** mean emulated. `@` / `@@` script includes are not
executed as nested scripts. `HOST`, `!`, `CONNECT`, `SPOOL`, and similar
client commands do not open a shell, a new session, or a file.

## WHENEVER SQLERROR — executor policy

`WHENEVER SQLERROR CONTINUE` and `WHENEVER SQLERROR EXIT` are **not**
filtered. They reach the executor and change the failure policy for
**following** statements in that script:

- **`CONTINUE`** — a later SQL error is logged and skipped; the migration
  keeps going.
- **`EXIT`** — a later SQL error stops the migration (SQL*Plus default).

The policy is positional. A script can switch mid-file:

```sql
WHENEVER SQLERROR CONTINUE
DROP TABLE maybe_exists;

WHENEVER SQLERROR EXIT
CREATE TABLE app_users (id NUMBER PRIMARY KEY);
```

`CONTINUE` applies to database-level SQL errors. Infrastructure failures
(aborted transaction, connection loss) still stop the run.

`WHENEVER OSERROR` is a client directive and is filtered, not a policy
change. `WHENEVER NOT FOUND` is real Oracle SQL and is left alone.

## DEFINE substitution

`DEFINE name = value` records a substitution variable. When define is on
(the default), DBLift replaces `&var` and `&&var` in the script before
statements are parsed:

- `SET DEFINE OFF` disables substitution for the rest of the script.
- `SET DEFINE ON` turns it back on.
- Unknown variables are left as-is.
- A trailing dot is the SQL*Plus terminator: `&schema.table` becomes
  `<value>table`. Use a double dot to keep a literal dot:
  `&schema..table` → `<value>.table`.

```sql
DEFINE schema = APP
CREATE TABLE &schema.users (id NUMBER PRIMARY KEY);
-- becomes: CREATE TABLE APPusers ...
```

## SET SERVEROUTPUT

`SET SERVEROUTPUT ON` is filtered as a client directive, but it also
enables session output collection for that migration. DBLift turns on
Oracle `DBMS_OUTPUT` capture on the active connection and logs lines
emitted by later statements. `SET SERVEROUTPUT OFF` disables it.

This is not a full SQL*Plus `SERVEROUTPUT` implementation (no `SIZE` /
`FORMAT` compatibility). It only collects session output when the
directive is present.

## PROMPT and REMARK

- **`PROMPT`** messages are written to the DBLift log as
  `[PROMPT] …`. Empty `PROMPT` lines are ignored.
- **`REM` / `REMARK`** are silent comments (equivalent to `--`). They
  are not echoed as prompts.

## Directive termination

SQL*Plus directives are line-terminated and usually have no trailing
`;`. The Oracle tokenizer only ends a statement on `;` or `/`, so a
directive without a terminator would otherwise merge with the next
DDL/DML — either dropping both as a “directive” or sending invalid SQL
to the driver.

DBLift appends `;` to recognized directive lines (and to
`WHENEVER SQLERROR`) that are not already terminated, so they tokenize
as their own statements. Multi-line SQL is left unchanged. Lines inside
block comments are not rewritten.

## Retained as real SQL

These look similar to SQL*Plus commands but are Oracle SQL (or were
false-positive matches). They are **not** filtered:

| Text | Why it is kept |
|---|---|
| `SET ROLE …` | Oracle privilege SQL, not a SQL*Plus `SET` option |
| `WHENEVER NOT FOUND …` | PL/SQL / cursor condition, not `WHENEVER SQLERROR` |
| `START TRANSACTION` / `START WITH` | SQL / hierarchical query syntax, not `START`/`@` |
| `CONNECT TO …` | Database-link DDL (`CREATE DATABASE LINK … CONNECT TO …`) |

## Limitations

- This is preprocessing, not a SQL*Plus emulator. Unrecognized client
  syntax is not invented or translated.
- `@` / `@@` script includes are dropped (not executed as nested
  scripts). Put the included SQL in a DBLift migration file instead.
- `HOST`, `!`, `CONNECT` / `CONN`, `SPOOL`, `ACCEPT`, `PAUSE`,
  `VARIABLE` / `PRINT`, and report-formatting commands (`COLUMN`,
  `TTITLE`, `BREAK`, …) are discarded client-side.
- `EXEC` / `EXECUTE` are filtered. Call procedures with a PL/SQL block
  (`BEGIN … END;`) instead.
- Substitution is `DEFINE` / `&var` only. For values that should come
  from config or CI, use [DBLift placeholders](commands.md#using-migration-placeholders).

## Example

`migrations/V2_0_0__create_app_users.sql`:

```sql
DEFINE schema = APP

WHENEVER SQLERROR CONTINUE
PROMPT Creating users table (ignore drop if missing)

DROP TABLE &schema.users;

WHENEVER SQLERROR EXIT
PROMPT Creating table

CREATE TABLE &schema.users (
    id   NUMBER PRIMARY KEY,
    name VARCHAR2(100) NOT NULL
);
```

What DBLift does with that file:

1. Logs `[PROMPT] Creating users table (ignore drop if missing)` and
   `[PROMPT] Creating table`.
2. Substitutes `&schema.` → `APP`, so the drop/create target is
   `APPusers`.
3. Continues past a missing-table error on `DROP`, then stops on any
   error from `CREATE TABLE`.
4. Does not send `DEFINE`, `PROMPT`, or `WHENEVER SQLERROR` to the
   driver.

## See also

- [Configuration → Supported Databases](configuration.md#supported-databases) — Oracle connection URL
- [Troubleshooting](troubleshooting.md#oracle-sqlplus-directives-in-migrations)
- [Commands → Placeholders](commands.md#using-migration-placeholders)

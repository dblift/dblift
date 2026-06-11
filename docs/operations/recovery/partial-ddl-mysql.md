# Partial DDL applied (non-transactional-DDL dialects)

On MySQL / MariaDB and Oracle, each DDL statement implicitly commits.
A multi-statement migration that fails on statement N has already
committed statements 1..N−1, and there is no rollback. The schema is
half-applied; the audit table records the migration as `FAILED`.

Applies to: **MySQL, MariaDB, Oracle** (DDL autocommit — each DDL statement
is its own implicit transaction). Also applies to **Cosmos DB** which has no
transaction concept at all.

Does NOT apply to PostgreSQL, SQL Server, DB2, SQLite — those dialects
roll the whole migration back automatically when a statement fails.

## Symptoms

- `dblift_schema_history` has a row with `success = 0` for version
  V<N>.
- The on-disk migration file V<N>__*.sql contains multiple DDL
  statements (CREATE TABLE / ALTER TABLE / CREATE INDEX, etc.).
- `INFORMATION_SCHEMA.TABLES` / `INFORMATION_SCHEMA.COLUMNS` (MySQL) or
  `USER_TABLES` / `USER_TAB_COLUMNS` (Oracle) shows some but not all of
  the objects that V<N> was supposed to create.
- The pre-failure log line in `stdout` reveals which statement died:
  e.g. `Executing statement 3 of 7: ALTER TABLE orders ADD CONSTRAINT ...`
  followed by an error and no further statements.

## Immediate response

1. **Freeze further migrations against this target.** Until the
   partial state is reconciled, running `dblift migrate` again is
   unsafe: the FAILED row blocks new migrations, *and* re-running
   V<N> will hit `CREATE TABLE ... already exists` on the statements
   that already landed.
2. **Read the migration file.** Open V<N>__*.sql and read it
   end-to-end. List the statements in order; note which ones are
   idempotent (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD
   COLUMN IF NOT EXISTS` where supported) and which aren't.
3. **Identify which statements landed.** For each DDL in the file,
   query the catalog to see whether the change is present:

       -- MySQL: did CREATE TABLE land?
       SELECT 1 FROM information_schema.tables
       WHERE table_schema = '<schema>' AND table_name = '<name>';

       -- MySQL: did ALTER ADD COLUMN land?
       SELECT column_name FROM information_schema.columns
       WHERE table_schema = '<schema>' AND table_name = '<name>'
         AND column_name = '<col>';

       -- Oracle equivalents: USER_TABLES, USER_TAB_COLUMNS.

   Make a table: statement N → applied? Y/N. Capture it.

## Recovery procedure

You have three viable paths. Pick **before** doing anything
destructive.

### Path A — roll forward (preferred when feasible)

Manually finish what V<N> started. Recommended when:

- the remaining statements are idempotent or trivially editable to be
  so (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`),
- the failure was transient (lock timeout, disk full, since-fixed
  config issue) and re-running the *missing* statements is safe.

Steps:

1. Hand-execute the post-failure statements **one at a time**, in the
   original order, against the same target.
2. After each statement, re-check the catalog to confirm it landed.
3. Once every statement from V<N> is present, mark the migration as
   successful in the audit table:

       UPDATE <schema>.dblift_schema_history
       SET success = 1, execution_time = <ms>
       WHERE version = '<V>' AND success = 0;

4. Run `dblift info` and confirm V<N> shows `success`.

### Path B — roll back (when V<N> shipped a reversible undo)

If V<N> has an associated `U<N>__*.sql` undo script, use it to revert
the partial state, then re-run V<N> from a clean baseline.

Steps:

1. Read the undo script U<N>__*.sql.
2. Identify which of its statements are needed to reverse only the
   *applied* portion (don't try to drop a table the partial migration
   never got around to creating).
3. Execute the relevant undo statements manually.
4. Confirm the catalog shows the pre-V<N> state.
5. Use `dblift repair` to remove the FAILED row, then `dblift migrate`
   to re-apply V<N>.

### Path C — split the migration (when neither A nor B is clean)

If the partial state can't be cleanly rolled forward or back (e.g. a
data-migration step ran half-way), the surgical option is to:

1. Move the **applied** statements into a new V<N+0.5>__*.sql file
   (use the next available version number) and mark it `success = 1`
   in the audit table without running it. This is a manual INSERT
   captured by the script set so future redeploys are coherent.
2. Move the **un-applied** statements into V<N+1>__*.sql and let
   `dblift migrate` run it normally.
3. Delete the original V<N> row from the audit table (it's now
   represented by V<N+0.5> + V<N+1>).

This path is high-effort and requires CR-level review; reach for it
only when A and B genuinely don't fit.

## Verification

- Every DDL statement from V<N> is reflected in the catalog (or, on
  Path B, none of them are and V<N> has been removed from history).
- `SELECT COUNT(*) FROM <schema>.dblift_schema_history WHERE success = 0`
  returns `0`.
- `dblift migrate --dry-run` reports only genuinely-future migrations
  as pending.
- (Application) a smoke test against the schema confirms the table
  shape the app expects.

## Prevention

- **Keep migrations atomic** on MySQL / MariaDB / Oracle: one DDL
  per migration file. If you need 5 DDLs, ship 5 migrations
  (V101..V105) instead of one with 5 statements. Each is then
  independently retryable.
- **Pair every DDL migration with an undo script** (`U<N>__*.sql`)
  so Path B is always available. dblift supports undo via the
  `generate_undo_script` API and the `undo` command.
- **Validate before applying.** Run `dblift validate` in CI and test
  migrations against a non-prod database before they fail mid-migration.
- **Test migrations against a non-prod copy of prod.** The most
  common cause of mid-migration failure is a constraint the dev DB
  doesn't have (FK pointing at a row that doesn't exist, NOT NULL
  on a column that has nulls in prod). A staging-from-prod-snapshot
  catches it.
- **Set a per-statement timeout** (MySQL `MAX_EXECUTION_TIME`,
  Oracle `RESOURCE_LIMIT`) so a runaway ALTER TABLE doesn't tie up
  the schema lock and force a kill that lands you here.

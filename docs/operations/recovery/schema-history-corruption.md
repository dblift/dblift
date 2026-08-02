# `dblift_schema_history` corruption

The audit table (`<schema>.dblift_schema_history`, name configurable
per provider) is the source of truth for which migrations dblift has
applied. When it goes out of sync with the on-disk script set or
contains internally inconsistent rows, every subsequent migrate /
info / validate command fails or hangs.

Applies to: **all dialects**.

## Symptoms

One or more of:

- `dblift info` reports a version as both `success` and `failed`, or
  shows a `pending` version with a non-NULL `installed_on`.
- `dblift migrate` exits with `Checksum mismatch for migration V<N>__*.sql`
  (the file on disk has a different SHA-256 than the recorded checksum).
- `dblift migrate` exits with `Duplicate version V<N>` (two rows for
  the same `version`, possibly because a manual INSERT was retried).
- A `FAILED` row at version V<N> blocks every V<M> where M > N from
  applying, even after the underlying issue is fixed and the file is
  re-runnable.
- A row exists in `dblift_schema_history` with NULL `checksum` or NULL
  `success` after the row was written but before the column was set.

## Immediate response

1. **Freeze deploys.** Until the audit table is consistent, every
   migration retry can compound the damage (especially on
   non-transactional-DDL dialects).
2. **Snapshot the table.** This is the only blast-radius-zero
   investigation step and it's critical for an after-action review.

       CREATE TABLE <schema>.dblift_schema_history_snapshot_<YYYYMMDD>
       AS SELECT * FROM <schema>.dblift_schema_history;

   (On Cosmos DB: export the container to JSON via the SDK.)
3. **Inventory the inconsistency.** Run, in order:

       -- Duplicates by version
       SELECT version, COUNT(*) FROM <schema>.dblift_schema_history
       GROUP BY version HAVING COUNT(*) > 1;

       -- Rows with NULL discriminators
       SELECT * FROM <schema>.dblift_schema_history
       WHERE checksum IS NULL OR success IS NULL OR installed_on IS NULL;

       -- FAILED rows that are blocking later migrations
       SELECT * FROM <schema>.dblift_schema_history
       WHERE success = 0
       ORDER BY installed_rank ASC;

       -- Checksum drift: compare row-by-row against the on-disk file
       --   sha256 of each V<N>__*.sql, compare to recorded checksum.

   Capture the output before doing anything destructive.

## Recovery procedure

The fix depends on which category you hit. Run only the path that matches.

### Category 1 — duplicate version rows

Caused by a manual `INSERT INTO dblift_schema_history` from a previous
recovery that didn't `DELETE` the bad row first, or by a driver retry on
a SQL Server connection blip mid-INSERT.

1. Pick the **canonical row** (the one whose `success`, `checksum`,
   `execution_time` agree with reality). Usually that's the row with
   `success = 1` if any.
2. Delete the duplicate(s):

       DELETE FROM <schema>.dblift_schema_history
       WHERE version = '<V>' AND installed_rank = <duplicate-rank>;

3. Run `dblift repair` to re-verify the journal can be read end-to-end
   without the duplicate.

### Category 2 — orphan FAILED row

The migration tried, failed, and on a transactional-DDL dialect the
schema rolled back but the FAILED row remains.

1. **Confirm the schema actually rolled back.** Run the migration's
   reverse query (count rows that the migration would have created,
   look for new columns, etc.). If you find evidence of *partial*
   application, switch to the [partial DDL runbook](partial-ddl-mysql.md)
   first.
2. Run `dblift repair --config <cfg>.yml`. This is the supported path
   for removing FAILED rows when the schema is in its pre-migration
   state.
3. Re-run `dblift migrate`. The previously-failing migration re-applies.

### Category 3 — NULL discriminator columns

The row was being written when the writer crashed.

1. Pick what the row *should* have been. If the migration body never
   ran (no schema changes), set `success = 0` so `dblift repair` can
   then remove it. If the migration body ran successfully and only the
   audit update failed, set `success = 1` and recompute the checksum
   from the on-disk file.
2. UPDATE the row in place rather than DELETE+INSERT — keep
   `installed_rank` stable so other rows' ordering doesn't shift.

### Category 4 — checksum drift

Someone edited a V file that was already applied (forbidden) **or** the
recorded checksum was computed against a different normalisation
strategy in an older dblift version.

1. If the file edit was intentional (e.g. fixing a comment typo and
   you don't want to re-apply): update the recorded checksum to match
   the current file SHA-256.

       UPDATE <schema>.dblift_schema_history
       SET checksum = '<new-sha256>'
       WHERE version = '<V>';

   This is also what `dblift repair` does for checksum drift (see
   `dblift repair --help`).
2. If the file edit was unintentional / a regression: restore the
   original file from git history and don't touch the audit table.

## Verification

- All four inventory queries from the immediate-response section return
  zero rows.
- `dblift info` round-trips cleanly with all versions in either
  `success` or `pending` state.
- A `dblift migrate --dry-run` reports either `0 migrations to apply`
  or only the genuinely-pending ones.

## Prevention

- **Never `UPDATE` or `DELETE` from `dblift_schema_history` outside a
  documented runbook.** Use `dblift repair` for routine drift; reach
  for raw SQL only when the runbook tells you to.
- **Make migration files immutable post-merge.** Add a pre-commit
  hook (or CI check) that fails when a V file already present in the
  default branch is modified. The matching `dblift_schema_history`
  row makes the file de-facto immutable; the hook makes that explicit.
- **Run dblift in a single-writer configuration.** A single deploy
  pipeline, one CI job at a time. Two simultaneous `dblift migrate`
  processes against the same target are the most common cause of
  duplicate-row corruption.
- **Back up the audit table** as part of the deploy pipeline (a pre-step
  in every migration run). If a recovery goes sideways, you have a
  point-in-time copy to roll back to.

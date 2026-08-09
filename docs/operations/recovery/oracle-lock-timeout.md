# Oracle `DBMS_LOCK` timeout

dblift serialises Oracle migrations via the [`DBMS_LOCK`][1] package
(`db/plugins/oracle/provider.py`, `acquire_migration_lock`). When the lock is held
longer than the configured timeout, the new migration aborts with an
`ORA-` lock error. The schema is untouched, but the operator needs to
know whether the lock holder is alive (wait), wedged (kill), or
crashed-without-releasing (cleanup).

[1]: https://docs.oracle.com/en/database/oracle/oracle-database/19/arpls/DBMS_LOCK.html

Applies to: **Oracle** only. Other dialects use advisory locks
(PostgreSQL) or row-level locks on a coordination table.

## Symptoms

- `dblift migrate` exits non-zero with a message like:
  - `DBMS_LOCK request failed with code 1` (timeout, the most common),
  - `DBMS_LOCK request failed with code 2` (deadlock),
  - `ORA-00054: resource busy and acquire with NOWAIT specified`,
  - `Failed to acquire migration lock; falling back to table-based locking`
    (dblift's own warning when the DBMS_LOCK call returns non-zero).
- `dblift info` shows the migration as `pending` (the lock acquisition
  happened *before* any journal write).
- The Oracle session view (`v$session`) shows one or more sessions with
  `program` containing `dblift` and `status = ACTIVE` for longer than
  the migration's typical runtime.

## Immediate response

1. Identify lock holders. Run as a DBA-privileged user:

       SELECT
         s.sid, s.serial#, s.username, s.osuser, s.machine,
         s.program, s.status, s.logon_time,
         l.type, l.id1, l.id2, l.lmode, l.request, l.block
       FROM v$session s
       JOIN v$lock l ON s.sid = l.sid
       WHERE s.program LIKE '%dblift%' OR s.module LIKE '%dblift%'
       ORDER BY s.logon_time ASC;

   The oldest session is usually the one holding the migration lock.
2. Decide: **wait** (the lock holder is a healthy long-running migration)
   or **kill** (the lock holder is wedged or crashed).
   - Healthy: row counts in `v$sql_monitor` for the holder's SQL are
     advancing, `v$transaction` shows non-zero `used_ublk` growing.
   - Wedged: no progress for >5 min, holder's `event` is suspicious
     (`SQL*Net break/reset to client`, `network unavailable`).

## Recovery procedure

### Path A — lock holder is healthy

Wait for the running migration to finish, then re-run `dblift migrate`.
The lock will be released as part of the commit / rollback at end of
the holder's transaction.

If you can't wait, the only safe interruption is to let the holder
finish or fail naturally — killing a healthy migration mid-DDL is the
[partial DDL scenario](partial-ddl-mysql.md) (Oracle autocommits DDL).

### Path B — lock holder is wedged

1. Kill the wedged session:

       ALTER SYSTEM KILL SESSION '<sid>,<serial#>' IMMEDIATE;

   `IMMEDIATE` releases server resources without waiting for the
   client to ACK. Without it, killing a TCP-stuck session can take
   minutes.
2. Confirm the kill cleared. Repeat the `v$lock` query — the offending
   row should be gone. If Oracle takes a few seconds to reap the
   session, wait and re-check rather than escalating to `SHUTDOWN
   ABORT`.
3. If `v$lock` still shows the lock held by a dead session, force the
   PMON cleanup:

       ALTER SYSTEM CHECKPOINT;
       -- and/or as last resort:
       EXEC DBMS_LOCK.RELEASE('<lock-handle>');

   `DBMS_LOCK.RELEASE` requires the handle, which dblift derives from
   the schema name (see `acquire_migration_lock` in the Oracle provider);
   contact the developer
   team for the exact handle if you can't read the source.
4. Investigate why the holder wedged before retrying. The
   [network split runbook](network-split.md) often applies.
5. Re-run `dblift migrate --config <cfg>.yml`. If the wedged session
   had actually applied DDL before hanging, follow up with the [partial
   DDL runbook](partial-ddl-mysql.md).

### Path C — lock holder is a dblift process from a previous deploy

This is a process-management problem, not a database problem. The lock
will release on its own when the orchestrator (CI, k8s job) finishes
killing the previous deploy. Make sure your deploy pipeline waits for
the previous deploy's cleanup hook before launching the next one.

## Verification

- `SELECT COUNT(*) FROM v$lock WHERE id1 = <dblift-lock-id1>` returns
  `0` (no one holding the dblift lock).
- A fresh `dblift migrate --dry-run` connects, acquires the lock, and
  reports `0 migrations to apply` (or whatever the actual pending list
  is) without timing out.

## Prevention

- **Bound migration runtime.** Long-running migrations (large index
  builds, table reorgs) should run *outside* `dblift migrate` — use
  Oracle's `DBMS_REDEFINITION` or partitioned-rebuild techniques
  separately, then mark the migration applied via `repair`.
- **Tune the dblift lock timeout** via the Oracle plugin config; the
  default trades availability for visibility. Shorter timeouts surface
  hung migrations faster.
- **Monitor `v$session` for long-running `dblift` sessions** so the
  operator hears about a stuck migration before the next deploy does.
- **Use a single deploy pipeline** that waits for the previous deploy
  to finish *and* release locks before kicking off the next. Concurrent
  CI runs targeting the same Oracle schema are the most common cause
  of `DBMS_LOCK` thrash.

# Network partition / connection loss mid-migration

The database connection between dblift and the target DB drops between
statement N and N+1 of a multi-statement migration, or during an
INSERT into `dblift_schema_history`. The migration *may* have applied
on the DB but the dblift client never saw the result. Outcome depends
on dialect transactionality.

Applies to: **all dialects**, with different recovery paths depending
on whether DDL is transactional.

## Symptoms

- `dblift migrate` exits with one of:
  - `java.sql.SQLException: I/O Error: Connection reset`
  - `java.sql.SQLRecoverableException: No more data to read from socket`
  - `socket.timeout: timed out`
  - `oracle.net.ns.NetException: Got minus one from a read call`
  - `MySQLNonTransientConnectionException: Communications link failure`
- `dblift info` may show the failed version as `pending` (commit didn't
  reach the client) **or** `success` (commit landed but the client
  socket died on the way back).
- A separate session that queries the same target sees the partial DDL
  (if non-transactional) or no change (if transactional).
- Infrastructure dashboards show network-side correlation: a load
  balancer flap, a DB failover, a security-group / firewall rule
  change applied during the migration window.

## Immediate response

1. **Don't reconnect-and-retry from CI automatically.** Most CI tools
   retry failed steps; turn that off for the `dblift migrate` step
   until the recovery path is chosen. A retry on a non-transactional-DDL
   dialect re-runs statement 1 against a schema where statement 1
   already landed.
2. **Verify the connection has recovered.** A `dblift info` (which
   opens a fresh connection) should succeed. If it hangs or fails the
   same way, the network issue is still active — fix that first.
3. **Determine what the DB sees.** Run the inventory queries from the
   [schema-history-corruption runbook](schema-history-corruption.md)
   and the catalog queries from the [partial DDL runbook](partial-ddl-mysql.md).
   Capture the output.

## Recovery procedure

Three sub-scenarios. Identify which one applies, then follow its path.

### Sub-scenario 1 — transactional-DDL dialect, transaction not yet committed

PostgreSQL, SQL Server, DB2, SQLite. The connection dropped mid-transaction.
The DB rolled the open transaction back when it noticed the client gone.
The schema is in its pre-migration state; only the journal needs
reconciling.

1. `dblift info` will show the version as either `pending` (audit row
   never written) or `failed` (audit row written before the schema
   work that subsequently rolled back).
2. If `failed`: `dblift repair --config <cfg>.yml`.
3. Re-run `dblift migrate`.

### Sub-scenario 2 — transactional-DDL dialect, transaction committed, audit write failed

The commit reached the DB before the disconnect, but the INSERT into
`dblift_schema_history` did not. The schema is post-migration; the
journal still thinks the migration is pending.

1. Confirm by querying the schema for V<N>'s post-state (the new
   table / column / index should be present).
2. Manually insert the audit row to record success:

       INSERT INTO <schema>.dblift_schema_history
         (installed_rank, version, description, type,
          script, checksum, installed_on, execution_time, success)
       VALUES
         (<next-rank>, '<V>', '<desc-from-filename>', 'SQL',
          '<filename>', '<sha256-of-file>', CURRENT_TIMESTAMP, <ms>, 1);

   Fields vary by provider — copy the column list from another
   successful row in the same table to match the schema your provider
   uses.
3. Run `dblift info` to confirm the row landed and the version now
   shows `success`.

### Sub-scenario 3 — non-transactional-DDL dialect

Oracle, MySQL, MariaDB, Cosmos DB. The DDL statements that ran before
the disconnect committed; the rest didn't. Follow the [partial DDL
runbook](partial-ddl-mysql.md) end-to-end; the network split was just
the trigger.

## Verification

- `dblift info` round-trips cleanly with the failed version in
  `success` state.
- A `dblift migrate --dry-run` reports only future pending migrations.
- The application's smoke test passes against the schema.
- (Operational) the network-layer fix that triggered the split is
  confirmed: LB stable, no firewall churn, DB primary stable for
  >5 min.

## Prevention

- **Run migrations from a stable network position.** Inside the same
  VPC / subnet as the DB primary, with predictable routes. Migrations
  from a developer laptop over VPN against prod is the highest-risk
  configuration.
- **Tune native driver connection settings**:
  - `socketTimeout` / `tcpKeepAlive=true` so a half-open connection
    fails fast instead of hanging until a layer-7 timeout.
  - `loginTimeout` short enough that an unreachable DB fails before
    the migration grabs locks.
  - Disable driver-level statement retries
    (`autoReconnect=false` on MySQL, equivalent on others). dblift
    treats retries itself; double-retries are the worst case here.
- **Schedule migrations outside of maintenance windows**. DB failovers,
  LB cutovers, and firewall changes during a deploy window dramatically
  raise the chance of this scenario.
- **Use a connection pool sized 1.** dblift should run as a single
  connection against the target during migration; multiple pooled
  connections raise the chance of a transient split affecting some
  but not all of them.
- **Monitor connection-reset rates.** A baseline of zero, with alerts on
  any non-zero count from the deploy host, surfaces the underlying
  network issue before a migration trips on it.

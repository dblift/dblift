# Recovery runbooks

Step-by-step procedures for recovering from failure modes that can leave
a target database in an inconsistent state while running `dblift migrate`.

Each runbook follows the same structure:

1. **Symptoms** — observable signals (logs, exit codes, DB state) that
   identify the scenario.
2. **Immediate response** — what to do *right now* before investigating.
3. **Recovery procedure** — ordered steps to bring the schema back to a
   known-good state.
4. **Verification** — how to confirm the system is healthy again.
5. **Prevention** — configuration and process changes that reduce the
   chance of recurrence.

## Runbooks

| Scenario | Runbook | Applicable dialects |
|---|---|---|
| Oracle `DBMS_LOCK` timeout / lock holder hung | [`oracle-lock-timeout.md`](oracle-lock-timeout.md) | Oracle |
| `dblift_schema_history` corruption (orphan FAILED row, checksum drift, duplicates) | [`schema-history-corruption.md`](schema-history-corruption.md) | All |
| Partial DDL applied — multi-statement migration failed mid-way on non-transactional-DDL dialect | [`partial-ddl-mysql.md`](partial-ddl-mysql.md) | MySQL, MariaDB, Oracle, Cosmos DB |
| Network partition / database connection lost mid-migration | [`network-split.md`](network-split.md) | All |

## Before any recovery

Two reads are always safe and always useful:

```bash
# 1. Show the journal — what dblift thinks it has applied.
dblift info --config <your-config>.yml

# 2. Show the audit table directly — what the DB actually thinks it has.
SELECT version, description, success, checksum, execution_time, installed_on
FROM <schema>.dblift_schema_history
ORDER BY installed_rank DESC
LIMIT 20;
```

`dblift info` reads the journal *through* the provider connection.
Querying `dblift_schema_history` directly bypasses provider caching and
is the source of truth.

## When to call `dblift repair`

`dblift repair` is the supported tool for reconciling the journal with
the on-disk migration files. It is safe to run any time the script set
and journal are out of sync, but it does **not**:

- alter actual schema objects (tables, columns, indexes),
- delete `FAILED` rows that correspond to genuinely partial migrations
  on a non-transactional-DDL dialect — those need the [partial DDL
  runbook](partial-ddl-mysql.md) first,
- replay missing migrations (use `dblift migrate` for that).

When in doubt, run `dblift info` and the direct SELECT first, then
choose the runbook that matches what you see. Reach for `repair` only
after the matching runbook explicitly directs you to.

## Related architecture sections

- [`ARCHITECTURE.md` § 4.2 Transactionality by dialect](../../../ARCHITECTURE.md) —
  which dialects autocommit DDL (Oracle, MySQL) and therefore can leave
  partial state behind.
- [`ARCHITECTURE.md` § 4.1 Contracts the system guarantees](../../../ARCHITECTURE.md) —
  the invariants `dblift migrate` upholds when the process completes
  normally.
- [ADR-0007 Transactional DDL matrix](../../adr/0007-transactional-ddl.md)
  (if present) — the rationale for the per-dialect transactionality
  flags.

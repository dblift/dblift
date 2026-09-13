# OSS performance execution and personal review ledger

Base: origin/develop 8645f3b. Worktree: .worktrees/oss-performance.
User explicitly requested root reviews; no separate reviewer agent substitutes for root.

## Preflight consistency review

| Tasks | Shared surface | Resolution |
|---|---|---|
| 1 / 3 | script manager loading | Sequential; filename work preserves callback catalog contract. |
| 1 / 4 | BaseCommand lifecycle | Sequential; history snapshots remain separate from callback catalog. |
| 2 / 4 / 5 | validation inputs | Preserve full catalog and scoped scripts separately; scoped history is not a global cache. |
| 3 / 4 | resolved Migration metadata | Catalog reuse consumes canonical content/checksum only. |
| 1–6 / 7 | performance evidence | Functional count tests accompany implementation; timing added at the end. |
| 1 | command-scoped cache and repeated operations | Tests explicitly cover cache expiry/failure and placeholders. |
| 2 | indexing and history matching | Preserve name and latest-success semantics with regression cases. |
| 3 | metadata overrides and sorting | Preserve constructor behavior and comparator ordering. |
| 4 | read reuse and concurrency | Reuse only before writes; retain post-lock refresh. |
| 5 | shared checks and input scoping | Adapters carry full/scoped catalogs independently. |
| 6 | quote-reader deduplication | Retain dialect-local behavior and token positions. |
| 7 | fresh migration benchmark | Setup fresh database outside each timed iteration. |

## Status

- Baseline on isolated develop archive: 2325 passed, 1 skipped, 57 subtests passed. Clean environment: /tmp/dblift-oss-performance-venv/bin/python.
- Tasks 1–5 complete, including the data ownership correction; Tasks 6–7 pending.

## Task 1 — personally reviewed and accepted

- Commit: b0b0101; reviewed complete production and test diff against 6cc7670.
- Constant full-catalog loads: 3 for both 3 and 12 real SQLite migrations (before: 18 and 54).
- 525 focused tests passed; seven new regressions passed after commit; formatting clean.
- Personal review correction: test-owned SQLAlchemy engines now dispose in finally, including assertion failures.
- Verified per-execution reset in all four callback-using commands, empty-catalog reuse, fresh direct manager calls, preserved matching/order and placeholder execution.
- No open correctness findings. Next catalog/history work may reduce remaining three initial loads.

## Task 2 — personally reviewed and accepted

- Commit: 46fdef2; reviewed complete production and test diff against f1b0436.
- 2346 tests passed, one skipped; final focused suite: 258 passed. Targeted mypy and Black passed.
- Resolved checksum comparisons perform no additional decoded reads. A 600-row history requires 1800 visits; repeatable lookup visits 160 rows twice.
- Verified first-match basename selection, supplied-order successful history, separately ranked repeatable history, encoding, audit exclusions, legacy fallback and both compatibility reexports.
- Standalone change detection retains fresh reads. Ordered result lists remain public; repository callers mutate them only through the indexed addition methods.
- Deliberate limitation: existing substring-based diagnostic suppression remains quadratic when many scripts drift (7140 issue visits for 120 drifts). Changing to exact-name deduplication would change visible diagnostics. Normal checksum lookup is linear.
- No open correctness findings.

### Task 2 additional style review

- Root installed the declared style tools in the isolated environment and found F401 on the two intentional compatibility reexports.
- Personally reviewed correction 455453b: explicit import-only suppressions, no behavior changes. Flake8 and isort now pass for both modules.

## Task 3 — personally reviewed and accepted

- Commit: 58c62b7; reviewed complete production and test diff against 455453b.
- One filename parse per loaded resource (previously four for callbacks, five for other scripts); redundant version sorting removed.
- Root review caught object-type drift for malformed V__.sql/V__.py. Two failing regressions reproduced it; retaining the existing inexpensive type classifier preserves UNKNOWN while keeping the one-parse improvement.
- Verified direct constructor overrides (truthy, falsey and path precedence), baseline markers, SQL/Python format behavior, callback buckets and path identity. No persistent metadata cache.
- 2141 migration tests passed, one skipped; 15 focused regressions passed after commit. Mypy, Black, isort, flake8 and both import contracts pass.
- No open correctness findings.

## Task 4 — personally reviewed and accepted

- Commit: ae44ad3; reviewed complete production and test diff against cb52908.
- Real SQLite history SELECTs: fresh migrate 7 to 4, no-op migrate 5 to 2, info 4 to 2, validate without a before callback 3 to 2. File reads and discovery passes also reduced.
- Verified command-local history capture, empty snapshots, full versus scoped catalogs, unchanged public JSON, pending versus validation ordering, and info fallback on state failure.
- Real regressions cover callback file/history mutations, fresh footer after callback writes, a second client applying a migration before lock acquisition, reused-command read failure recovery, changed directories/placeholders and byte-identical dry runs.
- Compatibility corrections preserve old private helper call arity when snapshots are omitted and existing string-keyed state catalogs.
- 2382 migration/validator tests passed, one skipped; 21 focused regressions and 23 SQLite CLI dry-run/JSON checks passed. Black/isort/flake8, targeted mypy and import contracts pass.
- Preserved limitations: a nonempty per-directory recursion map retains separate validator discovery to avoid changing its historical scope; existing strict rules may reject applied files outside a tag filter even when the checksum checker receives the full catalog. Neither behavior is changed by this optimization.
- No open correctness findings.

## Intermediate measured evidence after Tasks 1–3

- Frozen cb52908 source and develop 8645f3b used the same isolated Python 3.12.12 environment and SQLite probe.
- Fresh 100-migration run: decoded SQL reads 40600 to 300; catalog loads 406 to 3; local elapsed time 13.4713s to 0.2061s. Both runs verified 100 actual tables.
- These intermediate timings are observations on this machine, not performance guarantees. Final evidence follows after all lots.

## Task 4 ownership follow-up — personally reviewed and accepted

- User clarified that specialized managers collect data, MigrationStateManager aggregates it, and commands consume it.
- The first Task 4 history capture mechanism is being replaced: header display must not be the upstream source of state data.
- Task 5 was paused; its small uncommitted format-guard regression and implementation are preserved in an ignored patch for later resumption.

- Correction commit: 2a030f4; personally reviewed all production and fixture changes against 0187793. This supersedes the header capture mechanism described in the initial Task 4 record.
- HistoryManager remains the history collector; ScriptManager retains script/callback discovery, classification and event matching. StateManager aggregates their data and creates bounded history/callback snapshots. Commands consume those aggregates and orchestrate execution; validation rules remain in Validator.
- Base schema-version derivation moved into StateManager without changing baseline/undo semantics. Commands no longer directly fetch script/history data, including info fallback and post-lock typed history.
- Command-driven validator inputs also go through manager-owned snapshots at their existing lazy read points. Explicit state catalogs remain preferred; standalone validator input compatibility is retained.
- Separate lazy callback scope preserves first-event discovery after lock acquisition. A real test creates a callback during lock acquisition and verifies it executes; existing callback order/failure/freshness tests remain green.
- Test collaborator updates add the required state aggregator; no direct-collector production fallback was added for outdated fixtures.
- 2392 migration/validator tests passed, one skipped; 23 SQLite CLI/JSON checks passed. All formatting, typing, import contracts and repository ratchets pass.
- Read-count gains remain unchanged; no open correctness or ownership findings.

## Task 5 — personally reviewed and accepted

- Commits: a94a07a and af40fb9; personally reviewed the full production/test diff and final fixture correction.
- Both validation adapters now share the prepared-input check sequence. Input collection remains in the adapters; the shared validator performs no discovery or history reads.
- Full/scoped script and history inputs remain separate. Root requested keyword-only arguments to prevent accidental interchange.
- Twelve public-result parity cases cover duplicates, failed history, strict drift, repeatables, filtered and missing files, empty history, and format support. The resolved entry point now performs its missing format check.
- Root rejected a permissive production attribute fallback introduced for an incomplete test fixture. The final correction restores the normal format guard and supplies the fixture's intended context explicitly.
- 2404 migration/validator tests passed, one skipped; 23 SQLite CLI/JSON checks passed. After the final correction, 17 affected tests and all 232 SQL-validator tests passed. Formatting, typing, import contracts and repository ratchets passed.
- No open correctness or ownership findings.

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
- Tasks 1–3 complete; Tasks 4–7 pending.

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

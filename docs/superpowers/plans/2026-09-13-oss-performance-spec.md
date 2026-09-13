# OSS migration performance specification

Source: the reviewed optimization recommendations and the user request to address every item in priority order using coding subagents, with personal review by the root agent, starting from develop.

## Scope and acceptance

1. Eliminate full migration reloads per callback event. Discovery and callback content may be snapshotted for one command only; a subsequent command must observe new/changed files, changed directories and placeholders, including after a failed command.
2. Make checksum validation use indexes and one canonical checksum per resolved file. Preserve signed CRC32 normalization, encoding detection, latest successful non-audit history matching, legacy qualified script names, basename ambiguity behavior, missing/deleted/reappeared files, tag/version filters, and failed history reporting.
3. Reuse already resolved catalog/history within each read phase of migrate/info/validate. Always refresh history after lock acquisition and after writes where final results need it. Never introduce a process-wide database cache. Preserve command header/result semantics and dry-run's database immutability.
4. Parse filename metadata once when loading a resource; reuse values rather than creating managers for each field. Remove the second versioned sort. Preserve direct Migration construction, SQL/Python format roles, callbacks, tags and version order.
5. Share the common validation pipeline without dropping the full catalog needed to distinguish missing files from excluded ones. Retain callable validate_resolved_migrations and compatibility imports. Deduplicate the last-successful-record helper and the identical MySQL string readers.
6. Add real SQLite end-to-end benchmarks: fresh migrate with/without callbacks, no-op migrate, validate on populated history and info. Test operation counts deterministically in unit tests; timing belongs in opt-in benchmarks, not CI timing gates. Align benchmark documentation with actual files.

## Constraints

- Python >=3.11; no new runtime dependencies, no configuration flags, no dialect registry changes.
- OSS branch names use only fix/, release/ or feature/.
- Use the machine-configured Git author and committer identity; do not add assistant/model attribution or coauthor trailers.
- PR titles, descriptions and comments contain no assistant/model attribution; all implementation and publication text stays strictly within OSS scope.
- Preserve plugin-owned dialect behavior, locking and transaction boundaries, public result payloads, callback order/failure semantics, placeholders and encoding.
- Minimum focused implementation; no adjacent cleanup or unrelated bug fixes.
- Test performance regressions with real temporary files and SQLite plus narrow read/scan spies. Assert actual outputs as well as operation counts.
- Each lot has an implementation commit, a personal root review, focused tests and corrections before dependent work proceeds.
- Work branch fix/oss-migration-hot-paths starts at origin/develop 8645f3b. Do not modify or push develop. No publication requested.

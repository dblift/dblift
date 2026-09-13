# OSS Migration Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. The user explicitly assigns every task review to the root agent personally.

**Goal:** Address all six audit recommendations, prioritizing repeated I/O and quadratic work before local deduplication.

**Architecture:** Keep catalog reuse scoped to one command and history reuse scoped to one read phase. Build local lookup indexes, preserve plugin ownership and use a shared validation core with thin input adapters. Subagents implement sequentially in the isolated worktree; root reviews every lot and the combined diff.

**Tech Stack:** Python 3.11+, pytest, sqlite3, SQLAlchemy, pytest-benchmark (development only).

**Spec:** `docs/superpowers/plans/2026-09-13-oss-performance-spec.md`

## Global Constraints

- Python >=3.11; no new runtime dependencies, no configuration flags, no dialect registry changes.
- OSS branch names use only fix/, release/ or feature/.
- Use the machine-configured Git author and committer identity; do not add assistant/model attribution or coauthor trailers.
- PR titles, descriptions and comments contain no assistant/model attribution; all implementation and publication text stays strictly within OSS scope.
- Preserve plugin-owned dialect behavior, locking and transaction boundaries, public result payloads, callback order/failure semantics, placeholders and encoding.
- Minimum focused implementation; no adjacent cleanup or unrelated bug fixes.
- Test performance regressions with real temporary files and SQLite plus narrow read/scan spies. Assert actual outputs as well as operation counts.
- Each lot has an implementation commit, a personal root review, focused tests and corrections before dependent work proceeds.
- Work branch fix/oss-migration-hot-paths starts at origin/develop 8645f3b. Do not modify or push develop. No publication requested.

## Execution and review

Coding model: GPT-5.6 Sol with high reasoning for integration lots. Root performs the specification review and code-quality review itself, as explicitly requested. No implementer may spawn another agent. Workers must work only in the isolated worktree, record their base SHA, run focused checks, write a report and commit only their assigned changes.

For each task: reproduce the undesirable operation count (or record existing behavioral coverage for pure refactoring), implement the smallest change, verify, commit, then root reads the complete diff and relevant surrounding code. Any correctness finding returns to the implementer for correction and another personal review. Status is recorded in the adjacent review ledger.

Standard isolated test command:
```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -p pytest_mock -p pytest_asyncio.plugin --import-mode=importlib -q <explicit test paths>
```
The explicit plugins avoid an unrelated globally installed pytest-dblift entry point pointing at an obsolete worktree. Do not change global packages.

### Task 1: Command-scoped callback catalog (highest priority)

**Files:** `dblift/core/migration/commands/base_command.py`, `dblift/core/migration/scripting/migration_script_manager.py`, relevant command lifecycle entry points only if needed; new `tests/unit/core/migration/commands/test_callback_catalog_performance.py`.

**Interfaces:** Keep `get_callbacks_by_event` callable with existing arguments. Use a private command-owned catalog or an explicitly bounded scope; never put an unbounded cache on the shared script manager. Existing direct callers outside a command must retain fresh discovery.

- [x] Add SQLite tests with 3 and 12 migrations and zero callbacks: the number of catalog loads must be independent of migration count, and every migration must really be applied. Add events proving beforeEach/afterEach still execute for every migration, including failure behavior.
- [x] Test two calls on the same client after adding/changing callbacks and after a failed run. Test directory/recursive settings and placeholder freshness. Record failing scan-count evidence before editing production code.
- [x] Implement one callback catalog per command and filter/sort its callbacks by event using existing matching rules. Cache empty results too. Keep callback execution uncached.
- [x] Verify callback event, each-callback, placeholder and command suites; commit `perf: reuse callback catalog within each command`.

Suggested regression structure (use existing SQLite fixture conventions):
```python
with patch.object(manager, "load_migration_scripts", wraps=manager.load_migration_scripts) as loads:
    result = client.migrate()
assert result.success
assert len(result.migrations) == migration_count
assert loads.call_count <= 3
```
Measure the real manager wired into the command, and compare small/large batches rather than only checking a mock return value.

### Task 2: Indexed checksum validation and shared history lookup

**Files:** `dblift/core/sql_validator/_checksum_validator.py`, `dblift/core/sql_validator/migration_validator.py`, `dblift/core/migration/scripting/migration_script_manager.py`; new `tests/unit/core/sql_validator/test_checksum_validation_performance.py`.

**Interfaces:** Preserve `has_script_changed(...)` for standalone callers and the historical import of `_last_successful_non_delete_record` from migration_validator. The optimized validation path may pass precomputed matches/checksums through a private helper, keeping one implementation of matching rules.

- [x] Add tests counting decoded reads on unchanged and changed files with populated history; verify the reported mismatches and missing-file messages.
- [x] Add a large-history deterministic regression for matching/index construction. Preserve repeated records, successful rows, UNDO/DELETE exclusions, signed/unsigned checksum values, qualified legacy names, encoding and filtered-out scripts.
- [x] Build `scripts_by_name`, membership sets, deleted-script sets and latest-successful-record indexes once per validation call. Reuse the resolved file checksum; do not reread the file solely to confirm a difference. Preserve fallback behavior for standalone calls and legacy objects without resolved content.
- [x] Remove the duplicate history helper implementation with a compatibility reexport. Replace quadratic checked-script deduplication if it remains on this measured path, retaining ordered public lists.
- [x] Run checksum, repeatable, strict-mode, encoding and validation-result tests; commit `perf: index checksum validation inputs`.

Index shape:
```python
scripts_by_name = {script.script_name: script for script in scripts}
full_script_names = {script.script_name for script in all_scripts}
```
Do not silently change first-match/last-match semantics for ambiguous names; establish them from existing tests before selecting dictionary construction order.

### Task 3: Reuse filename metadata and remove duplicate sort

**Files:** `dblift/core/migration/migration.py`, `dblift/core/migration/scripting/migration_script_manager.py`; new `tests/unit/core/migration/scripting/test_filename_resolution_performance.py`.

**Interfaces:** Preserve `Migration(...)` public constructor and its explicit override behavior. Keep filename metadata logic in `parse_filename`; supply or reuse that tuple internally without introducing a configurable parser/cache.

- [x] Add operation-count coverage for one file load and behavior cases for SQL/Python, repeatable, undo, baseline, callbacks, tags and semantically ordered versions.
- [x] Use a single filename parse to populate type/version/description/tags, preserving path identity, encoding and format detection. Remove repeated manager construction from that path.
- [x] Extend the already sorted versioned list directly in `get_migration_scripts`, avoiding its second `sorted(...cmp_to_key...)`.
- [x] Run migration model, filename, recursive-path and version-sort tests; commit `perf: resolve migration filename metadata once`.

Target duplicate-sort replacement:
```python
all_migrations.extend(migrations[MigrationType.SQL])
```

### Task 4: Reuse catalog and history within command read phases

**Files:** `dblift/core/migration/commands/base_command.py`, `migrate_command.py`, `info_command.py`, `validate_command.py`; `dblift/core/migration/state/migration_state_manager.py`, `migration_state.py`; `dblift/core/migration/executor/migration_helpers.py`; validator input adapter only if necessary; new `tests/unit/core/migration/commands/test_command_read_reuse.py`.

**Interfaces:** Keep public result serialization unchanged. An internal resolved catalog on the state, or optional input to state construction, must not appear as raw Migration objects in JSON. Optional preloaded history must distinguish an empty list from unavailable data. Preserve no-argument compatibility of header helpers.

- [ ] Count real file reads and history SELECTs in migrate/no-op migrate/info/validate. Verify current version, duplicate-version warnings and applied/pending lists.
- [ ] Reuse the full catalog already loaded by build_state for duplicate detection and validation. Never pass only pending scripts where full-catalog missing-file validation is required.
- [ ] Remove the obsolete debug-only history fetch, and share history with header/state/validation in the initial read phase where no callback/write intervenes. Keep post-lock and final-state reads; invalidate at callback/write boundaries.
- [ ] Add same-client repeated-operation tests and a concurrency regression proving post-lock history still prevents duplicate application. Preserve dry-run behavior.
- [ ] Run state, info, migration concurrency, preflight, dry-run and result-schema tests; commit `perf: reuse command catalog and history snapshots`.

Required empty-snapshot semantics:
```python
records = preloaded_records if preloaded_records is not None else history_manager.get_applied_migrations()
```

### Task 5: Shared validation pipeline

**Files:** `dblift/core/sql_validator/migration_validator.py`, `_migration_filter.py` and checksum module only for adapter integration; new `tests/unit/core/sql_validator/test_validation_entrypoint_parity.py`.

**Interfaces:** Retain `validate_migrations(...)` and `validate_resolved_migrations(...)`. The shared core consumes full catalog, scoped scripts and the appropriate history snapshot separately; adapters remain responsible for directory resolution and caller scope.

- [ ] Add parity tests for duplicate versions/repeatables, failed history, strict drift checks and unsupported formats. Explicitly cover filtered scripts present on disk and genuinely missing files.
- [ ] Extract the repeated check sequence into a private common method; route both entry points to it. Both run format-support checks. Preserve checked/failed lists, issue order, error strings and early-return behavior except the identified missing format check.
- [ ] Keep tests independent of method-internal call layout; assert public ValidationResult behavior.
- [ ] Run the full SQL-validator unit suite and command validation tests; commit `refactor: share migration validation pipeline`.

### Task 6: Deduplicate MySQL quoted-string readers

**Files:** `dblift/db/plugins/mysql/parser/mysql_tokenizer.py`; existing MySQL tokenizer tests.

**Interfaces:** Retain both existing reader methods if callers/tests rely on them; delegate to one implementation that reads its delimiter from input. Do not move dialect-specific escaping rules into a central registry.

- [ ] Verify existing coverage and add missing behavior examples only: doubled quotes, backslash escapes, embedded other quote, multiline positions and current unterminated-input behavior.
- [ ] Share the identical implementation with thin wrappers; preserve token text/type/position and cursor advancement.
- [ ] Run the MySQL tokenizer/parser suite; commit `refactor: share MySQL quoted string tokenization`.

Example equivalence cases:
```python
samples = ["'O''Reilly'", '\"a\"\"b\"', "'a\\'b'", '\"a\\\"b\"']
```
Use the actual tokenizer public API from existing tests to assert token values and following-token positions.

### Task 7: End-to-end benchmarks and final verification

**Files:** new `tests/benchmarks/test_bench_sqlite_commands.py`, `tests/benchmarks/README.md`; deterministic operation-count tests from Tasks 1/2/4.

**Interfaces:** pytest-benchmark remains opt-in, no runtime dependency or CI timing threshold. Fresh migration databases must be reset outside the timed function each round; never accidentally benchmark a no-op after the first round.

- [ ] Add fresh migrate benchmarks for 10/100 scripts with/without callbacks, plus populated-history no-op migrate, validate and info. Assert real database/result outcomes.
- [ ] Use `benchmark.pedantic(..., setup=..., iterations=1)` or equivalent isolation so each timed fresh-migrate invocation has a fresh database. Dispose connections and remove temporary artifacts safely.
- [ ] Correct README coverage and commands to actual test names; do not overwrite a historical timing baseline with unrelated hardware measurements.
- [ ] Run benchmark smoke with explicit pytest-benchmark plugin, unit suites covering all changed areas, formatting/type checks on changed production modules, and personal root review of the whole branch.
- [ ] Compare operation counts and a local 100-migration timing against develop; document hardware/profiling limitations and final review results. Commit `test: benchmark SQLite migration command workloads`.

## Personal review checklist for every lot

- [ ] Every changed production line maps to this task and spec.
- [ ] No global caches, hidden dialect coupling or unrelated refactors.
- [ ] Freshness, error paths, ordering, filters and public payloads preserved.
- [ ] Tests exercise real outcomes and demonstrate the relevant regression.
- [ ] Focused test outputs read; complete diff personally reviewed; findings fixed.

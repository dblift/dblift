# OSS Core Read Efficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development task-by-task. The controller personally performs specification and code-quality reviews, as explicitly requested.

**Goal:** Address all five audited optimization opportunities and publish a verified PR to develop.

**Architecture:** Keep collection with specialized managers and aggregation with StateManager. Use ephemeral indexes and discovery metadata, simplify version-only work and retire unused private code without adding new layers.

**Tech Stack:** Python >=3.11, pytest, SQLite, SQLAlchemy, existing quality tools.

**Spec:** `docs/superpowers/plans/2026-09-13-oss-core-read-efficiency-spec.md`

## Global Constraints

- Python >=3.11; no new runtime dependencies, flags or global caches.
- Specialized managers collect their data. ScriptManager discovers scripts/callbacks and matches events; HistoryManager collects history; StateManager aggregates; commands consume. Validator retains validation rules and engines retain execution.
- Do not bypass StateManager from commands or move dialect rules out of plugins.
- OSS branches use only fix/, release/ or feature/. Use machine-configured Git author/committer, no attribution trailers or attribution in PR text. Publication stays strictly within OSS scope.
- Preserve user-visible payloads, errors, filtering, order and freshness except the explicitly documented removal of unused private APIs.
- Keep edits surgical. Preserve public filters and current-version contracts. Tests cover real outcomes and deterministic operation counts, not only internal call layouts.
- The user authorized implementation, fresh agents, personal review and a PR to develop. Do not merge the PR.

## Execution and verification

Worktree `.worktrees/oss-core-read-efficiency`, branch `fix/oss-core-read-efficiency`, base `8f8e2a3`. Fresh implementer per task; one implementation at a time. Read-only preparation may run alongside independent controller work. Each implementer reads its extracted brief and the spec, records its base, reproduces the issue, implements, tests, commits assigned files and writes its report. The controller reads every complete diff and returns findings for correction.

Use a task-specific environment installed from `constraints-ci.txt` with the same extras as unit CI. Quality uses Python 3.11 with requirements-dev.txt and [dev,mcp], including flake8-tidy-imports. Do not silently reduce verification to selected tests or omit lint plugins. Models: Sol high for focused indexing/removal; Astra high for filesystem, history and repair semantics. Controller performs all final reviews.

### Task 1: Index StateManager repeatable fallbacks

**Files:** `dblift/core/migration/state/migration_state_manager.py`; new `tests/unit/core/migration/state/test_repeatable_lookup_performance.py`.

**Interfaces:** Keep `_lookup_checksum(checksums, script_name)` and `_is_repeatable_pending(script_name, migration, executed_scripts, repeatable_checksums)` callable. Optional keyword-only precomputed indexes may extend them. Build indexes in aggregation callers, never as persistent manager attributes. `_compute_pending_migrations` and `_determine_checksum_changes` consume them.

- [x] Add red regressions for 500 new repeatables versus 500 executed names and 500 bare names versus qualified checksum keys. Count input visits; verify returned pending/checksum results.
- [x] Cover direct full-key priority, direct basename priority, first qualified match on collisions, missing names, unchanged/changed repeatables and subsequent calls with changed inputs.
- [x] Build basename membership once and a first-match checksum map with setdefault; pass them into loops while retaining direct-call behavior:
```python
executed_basenames = {Path(name).name for name in executed_scripts}
basename_checksums = {}
for name, checksum in repeatable_checksums.items():
    basename_checksums.setdefault(Path(name).name, checksum)
```
- [x] Verify linear input visits and real SQLite repeatable state/reapply outcomes; run state, repeatable and command read-reuse tests, formatting, lint and targeted typing. Commit `perf: index repeatable state lookups`.

### Task 2: Reuse ScriptManager discovery metadata

**Files:** `dblift/core/migration/scripting/migration_script_manager.py`; new `tests/unit/core/migration/scripting/test_discovery_metadata_reuse.py`; existing filename/discovery fixtures only as necessary.

**Interfaces:** Public `get_all_scripts(...) -> List[str]` and `load_migration_scripts(...) -> Dict[MigrationType, List[Migration]]` remain callable. Carry path, resolved path and filename metadata from discovery to loading in one private per-call record/map; use a small internal tuple/dataclass only if it reduces repeated reconstruction. The existing Migration `_filename_metadata` constructor input remains unchanged. No cache survives one load.

- [x] Add red tests proving a 10/100-file normal load currently calls each filesystem predicate/resolution twice; assert all actual migrations are returned.
- [x] Verify nonrecursive/recursive/additional/overlapping directories, relative roots, symlink exclusion, out-of-root resolution, missing/unreadable files, encoding failures and unchanged filename parse counts.
- [x] Remove the immediately repeated is_file/is_symlink checks and reuse the already guarded resolved path for deduplication. Retain path references, ordering and the traversal guard:
```python
resolved_script_path = script_path.resolve()
resolved_script_path.relative_to(resolved_dir_path)
# Carry this value with the original path and parsed filename for this load.
```
- [x] Preserve standalone get_all_scripts behavior and justified legacy input paths; update incomplete test collaborators rather than weakening production guards. Run scripting/filename/path-security/encoding suites plus lint/type checks. Commit `perf: reuse script discovery filesystem metadata`.

### Task 3: Calculate schema version without display analysis

**Files:** `dblift/core/migration/state/migration_state_manager.py`; new `tests/unit/core/migration/state/test_schema_version_read_efficiency.py`; existing command header tests as needed.

**Interfaces:** `resolve_current_schema_version(snapshot=None)` retains its signature, return values, exception behavior and fresh/snapshot read ownership. Leave `MigrationState.current_version` and display-state computation unchanged. Keep rank rules in existing migration helpers.

- [ ] Add red test: a real populated SQLite info/no-op migrate currently builds/sorts display analysis three times; the optimized path should do it only for build_state.
- [ ] Compare old and proposed results for baseline-only, undo/reapply chains, repeated/tied ranks, successful/failed/None/string-success records, out-of-order and alphanumeric versions. Preserve both header and footer results.
- [ ] Derive the same effective undone/reapplied sets from history without constructing unused display context, repeatable indexes or grouping/sorting versioned history for header/footer:
```python
ranks = latest_successful_ranks(applied_migrations)
# Preserve the existing undo-presence and reapplied predicates, including ties.
# Filter effective undone versioned rows, then reuse get_current_version.
```
- [ ] Confirm history read counts remain unchanged, fresh post-write/footer and post-lock behavior remain covered, and public state payloads are unchanged. Run state/commands/CLI JSON suites and static checks. Commit `perf: avoid display analysis for schema version headers`.

### Task 4: Reuse repair's pre-write catalog through StateManager

**Files:** `dblift/core/migration/state/migration_state.py`, `migration_state_manager.py`, `dblift/core/migration/commands/repair_command.py`; new `tests/unit/core/migration/commands/test_repair_catalog_reuse.py`; affected repair fixtures including `tests/unit/test_v110_regressions.py`.

**Interfaces:** Built state must expose the original grouped full catalog internally (repr=False, excluded from to_dict, copied correctly) or an equivalent StateManager-owned accessor with the same grouped traversal order. A missing catalog is None; an empty loaded catalog is valid. Existing `get_grouped_migrations` remains fresh when no built catalog is supplied. Repair rules and writes stay in RepairCommand/history/engine.

- [ ] Add red real SQLite no-op/preview tests: three current loads should become one; verify result and unchanged database bytes for preview.
- [ ] Preserve grouped-order last-wins duplicate-basename behavior; do not flatten via resolved_objects if that changes ordering. Reuse the same initial catalog for missing-script and drift detection:
```python
catalog = migration_state.grouped_objects
if catalog is None:
    catalog = self.state_manager.get_grouped_migrations(scripts_dir, ...)
# Use an explicit None check; an empty dictionary is authoritative.
```
- [ ] Preserve failed build fallback, empty-directory refusal, missing-scan error propagation and drift-warning behavior for direct helper calls. Do not silently turn errors into an empty catalog. Refresh post-write state and on a subsequent command.
- [ ] Verify real checksum repair then validate, failed-row deletion, missing/delete/baseline markers, SQL/Python scripts, recursion maps and dry-run purity. Run all repair tests including v110, state serialization/copy tests and static checks. Commit `perf: reuse repair catalog before history writes`.

### Task 5: Remove retired private validation and data-service code

**Files:** delete `dblift/core/sql_validator/_sql_syntax_validator.py`; edit `migration_validator.py`, `dblift/core/migration/state/migration_data_service.py`; affected tests in validator/data-service suites.

**Interfaces:** Keep public validate_migrations/validate_resolved_migrations, format support checks, placeholders constructor parameter/attribute, compatibility history imports and executor SqlAnalyzer. Remove only production-unreferenced private `_validate_sql_syntax`, `_replace_placeholders` if still exclusively used by the removed path, validator's unused analyzer setup, MigrationDataService.state_service, `_is_version_reapplied`, `_get_undo_rank`. Do not remove live filter helpers.

- [ ] Verify repository/package/doc references again and identify tests exercising only retired internals. Keep behavior tests; remove obsolete implementation-only tests and unused fixture setup.
- [ ] Add or retain meaningful regression proving migration metadata validation performs no SQL syntax parsing while format validation and active SQL execution/lint still work.
- [ ] Remove the unused module/adapter/analyzer allocation; retain dialect derivation for quirks:
```python
dblift_config = getattr(self.history_manager.provider, "config", None)
dialect = dblift_config.database.type if dblift_config else ""
self._quirks = ProviderRegistry.get_quirks(dialect)
```
- [ ] Remove the unreferenced data-service allocation/two helpers; retain rank aggregation methods. Run complete validator/state/SQL-parser and active CLI SQL-lint tests, inspect public imports, and run static checks. Commit `refactor: remove retired migration validation helpers`.

### Task 6: Final review, changelog and PR (controller)

**Files:** `CHANGELOG.md`, this plan and adjacent review ledger. No unrelated runtime edits.

- [ ] Update Unreleased with performance changes and removed private helpers; retain released entries and version number.
- [ ] Personally review the combined branch diff, all manager boundaries and all task corrections. Resolve findings through their implementers before publication.
- [ ] Run complete unit suite with CI extras/constraints on Python 3.12, then pytest-dblift package tests; run complete quality workflow on Python 3.11, all existing benchmarks and focused operation-count probes.
- [ ] Compare baseline/final counts and local timings on identical workloads; report scope and avoid timing guarantees. Verify git identity, branch prefix, clean state and no forbidden publication text.
- [ ] Push fix/oss-core-read-efficiency and create a PR to develop with concise scope, validation and compatibility notes. Wait for CI and correct any failures. Do not merge.

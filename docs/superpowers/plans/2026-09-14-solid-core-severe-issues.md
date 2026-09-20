# OSS Core Severe SOLID Issues Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the highest-risk SOLID violations in SQL callback execution, provider transaction capabilities, validation data flow, and migration resolution without changing public command results.

**Architecture:** Specialized managers keep their current responsibilities: ScriptManager discovers, reads, classifies, and matches scripts and callbacks; HistoryManager reads and writes history; StateManager aggregates command-scoped data; Validator applies validation rules; ExecutionEngine executes prepared work; commands orchestrate and consume StateManager outputs. Deliver the work as four serial, independently reviewable fixes so each behavioral change can be verified and reverted on its own.

**Tech Stack:** Python 3.11+, pytest, mypy, Black, isort, Flake8, import-linter, repository lint scripts, existing SQLite integration fixtures, existing provider plugins.

**Spec:** `docs/superpowers/plans/2026-09-13-oss-performance-spec.md`

## Global Constraints

- Start every implementation branch from the latest `origin/develop`; use only `fix/`, `release/`, or `feature/` branch prefixes.
- Use the machine-configured Git author and committer identity. Add no assistant/model attribution, coauthor trailer, or attribution in PR text or comments.
- Keep publication text within OSS scope.
- ScriptManager owns filesystem discovery, script reading, filename classification, callback discovery, and callback event matching.
- HistoryManager owns migration-history reads and writes.
- StateManager aggregates ScriptManager and HistoryManager data into bounded command-scoped snapshots; commands consume those snapshots.
- Validator owns validation rules, ExecutionEngine owns execution, and commands own orchestration.
- Preserve public command signatures, result payloads, callback ordering, callback failure semantics, placeholders, encoding, lock boundaries, history atomicity, and dialect-owned behavior.
- Add no runtime dependency, configuration flag, process-wide cache, or central per-dialect registry entry.
- Use tests that assert observable behavior. Do not preserve a misleading interface solely because an existing implementation-detail test expects it.
- Each branch receives focused tests, the full unit suite, static checks, a personal diff review, and its own PR to `develop`. Merge order is the order below.

## Delivery Order

| Order | Branch | Outcome |
|---|---|---|
| 1 | `fix/callback-sql-transaction-policy` | SQL callbacks use the same parsing and transaction decision as SQL migrations. |
| 2 | `fix/provider-transaction-capability` | Only providers that can transact implement `TransactionalProvider`. |
| 3 | `fix/state-managed-validation-inputs` | Validator receives script/history inputs exclusively through StateManager. |
| 4 | `fix/migration-resolution-boundary` | ScriptManager resolves resources; the migration model stops constructing managers and parsing files itself on normal paths. |

---

### Task 1: Pin SQL callback transaction-policy behavior

**Files:**
- Create: `tests/unit/core/migration/executor/test_callback_transaction_policy.py`
- Read: `dblift/core/migration/executor/execution_engine.py`
- Read: `dblift/core/migration/executor/transaction_policy.py`

**Interfaces:**
- Consumes: `TransactionPolicy.decide(statements, provider) -> TransactionPolicyDecision`.
- Produces: failing behavioral tests defining callback transaction semantics for Tasks 2 and 3.

- [ ] **Step 1: Add an autocommit-only callback regression**

Create a SQL callback fixture with one statement. Stub `_classify_execution_statements` and `transaction_policy.decide` so the decision is `transactional=False, autocommit_required=True`. Assert that `SqlExecutionService.execute_statement` receives `autocommit=True` and that `provider.begin_transaction()` and `provider.commit_transaction()` are not called.

```python
decision = TransactionPolicyDecision(
    transactional=False,
    autocommit_required=True,
    reason="statement requires autocommit",
)
engine.transaction_policy.decide.return_value = decision

engine.execute_callback(callback)

engine.sql_execution_service.execute_statement.assert_called_once_with(
    "CREATE INDEX CONCURRENTLY idx_t_id ON t(id)",
    autocommit=True,
)
engine.provider.begin_transaction.assert_not_called()
engine.provider.commit_transaction.assert_not_called()
```

- [ ] **Step 2: Add transactional, non-transactional, and mixed-mode regressions**

Cover these outcomes:

Add `test_callback_uses_explicit_transaction_when_policy_is_transactional`,
`test_callback_skips_explicit_transaction_for_non_transactional_provider`, and
`test_callback_rejects_mixed_transaction_modes_before_execution`. The mixed-mode
test must assert the error includes the policy reason and that no statement, begin,
commit, or rollback call occurs.

- [ ] **Step 3: Verify the new tests fail for the intended reason**

Run:

```bash
.venv/bin/python -m pytest tests/unit/core/migration/executor/test_callback_transaction_policy.py -q
```

Expected: failures show that `execute_callback()` begins transactions unconditionally and does not pass `autocommit=True`.

- [ ] **Step 4: Commit the red tests**

```bash
git add tests/unit/core/migration/executor/test_callback_transaction_policy.py
git commit -m "test: define callback transaction policy"
```

### Task 2: Share transaction planning between migrations and callbacks

**Files:**
- Modify: `dblift/core/migration/executor/execution_engine.py:132`
- Modify: `dblift/core/migration/executor/execution_engine.py:1060`
- Test: `tests/unit/core/migration/executor/test_callback_transaction_policy.py`
- Test: `tests/unit/core/migration/executor/test_transaction_policy.py`

**Interfaces:**
- Consumes: `TransactionPolicyDecision` and `_classify_execution_statements(statements)`.
- Produces: `_plan_sql_execution(statements: List[str]) -> TransactionPolicyDecision`, used by both SQL migrations and SQL callbacks.

- [ ] **Step 1: Extract the shared planning helper**

Add the smallest shared method to `ExecutionEngine`:

```python
def _plan_sql_execution(self, statements: List[str]) -> TransactionPolicyDecision:
    execution_statements = self._classify_execution_statements(statements)
    return self.transaction_policy.decide(execution_statements, self.provider)
```

Replace the inline migration decision with this helper. Preserve the current migration error text and early return for mixed mode.

- [ ] **Step 2: Apply the same decision in `execute_callback()`**

Before executing callback statements:

```python
policy = self._plan_sql_execution(sql_statements)
if policy.unsupported_mixed_mode:
    raise CallbackExecutionError(
        f"Callback {callback.script_name} mixes transactional and "
        f"autocommit-only statements: {policy.reason}"
    )

transaction_started = False
if policy.transactional:
    self.provider.begin_transaction()
    transaction_started = True
```

When `sql_execution_service` is present, pass `autocommit=policy.autocommit_required`. On the provider fallback, call `execute_autocommit_statement()` only when the provider implements `TransactionalProvider`; otherwise use `execute_statement()` because the provider already operates without an explicit transaction.

- [ ] **Step 3: Gate commit and rollback on the actual decision**

Commit only when `transaction_started` is true. Retain best-effort rollback of the original callback failure and retain BaseCommand's distinction between ordinary callback failures and error-callback failures.

- [ ] **Step 4: Run focused execution tests**

```bash
.venv/bin/python -m pytest \
  tests/unit/core/migration/executor/test_callback_transaction_policy.py \
  tests/unit/core/migration/executor/test_transaction_policy.py \
  tests/unit/core/migration/executor/test_execution_engine_extended.py \
  tests/unit/core/migration/commands/test_callback_result_recording.py -q
```

Expected: all pass; callback ordering and result-set capture remain unchanged.

- [ ] **Step 5: Commit the behavior fix**

```bash
git add dblift/core/migration/executor/execution_engine.py tests/unit/core/migration/executor/test_callback_transaction_policy.py
git commit -m "fix: apply transaction policy to callbacks"
```

### Task 3: Reuse migration SQL preprocessing for callbacks

**Files:**
- Modify: `dblift/core/migration/executor/execution_engine.py:291`
- Modify: `dblift/core/migration/executor/execution_engine.py:1060`
- Create: `tests/unit/core/migration/executor/test_callback_sql_preparation.py`
- Test: `tests/unit/core/migration/executor/test_execution_engine_sqlplus.py`
- Test: `tests/unit/core/migration/test_callback_placeholder_parse_order.py`

**Interfaces:**
- Consumes: the current placeholder and dialect-quirks behavior in `_parse_sql_statements`.
- Produces: `_prepare_sql_statements(migration: Migration) -> List[str]`; the existing `_parse_sql_statements(...) -> Optional[List[str]]` remains a result-updating compatibility wrapper.

- [ ] **Step 1: Add failing preparation-parity tests**

Assert that migration and callback preparation both:

- substitute placeholders before tokenization;
- invoke dialect-owned script preprocessing;
- discard dialect client directives through the existing execution checks;
- leave canonical migration content and cached statements unchanged.

```python
migration_statements = engine._prepare_sql_statements(migration)
callback_statements = engine._prepare_sql_statements(callback)
assert callback_statements == migration_statements
assert callback.content == original_content
```

- [ ] **Step 2: Extract the raising preparation core**

Move only the successful body of `_parse_sql_statements` into `_prepare_sql_statements`. It raises the original parsing exception and performs no result mutation. Keep the existing wrapper:

```python
def _parse_sql_statements(self, migration, result, placeholder_service=None):
    try:
        return self._prepare_sql_statements(
            migration,
            placeholder_service=placeholder_service,
        )
    except Exception as exc:
        message = f"Failed to parse SQL for {migration.script_name}: {to_python_string(exc)}"
        self.log.error(message)
        result.set_error(message)
        return None
```

- [ ] **Step 3: Route callbacks through `_prepare_sql_statements`**

Remove callback-local placeholder replacement and direct `callback.parse_sql_statements(...)`. Keep callback-specific exception logging and re-raise behavior around the shared helper.

- [ ] **Step 4: Verify focused and complete branch checks**

```bash
.venv/bin/python -m pytest tests/unit/core/migration/executor tests/unit/core/migration/commands tests/unit/core/migration/test_callback_placeholder_parse_order.py -q
.venv/bin/python -m mypy dblift/core/migration/executor/execution_engine.py --config-file pyproject.toml --show-error-codes
isort --check --diff dblift/core/migration/executor tests/unit/core/migration/executor
flake8 --config=.flake8 dblift/core/migration/executor
black --check dblift/core/migration/executor tests/unit/core/migration/executor
lint-imports --config .importlinter
```

- [ ] **Step 5: Commit and review PR 1**

```bash
git add dblift/core/migration/executor/execution_engine.py tests/unit/core/migration/executor/test_callback_sql_preparation.py
git commit -m "refactor: share SQL preparation for callbacks"
```

Review the complete branch against `origin/develop`. Verify that callback discovery remains in ScriptManager, StateManager remains the callback catalog source, and only execution behavior changed. Run the full unit suite before opening the PR.

---

### Task 4: Make transaction capability truthful

**Files:**
- Modify: `dblift/db/base_provider.py:32`
- Modify: `dblift/db/sqlalchemy_provider.py:95`
- Modify: `dblift/db/plugins/sqlite/provider.py:24`
- Modify: `dblift/db/plugins/cosmosdb/provider.py:156`
- Modify: `dblift/db/plugins/mongodb/provider.py:80`
- Modify: `dblift/core/migration/executor/transaction_policy.py:25`
- Audit and modify guards in: `dblift/api/client.py`, `dblift/db/plugins/base_snapshot_manager.py`, `dblift/core/migration/commands/baseline_command.py`, `clean_command.py`, `migrate_command.py`, `repair_command.py`, `dblift/core/migration/history/migration_history_manager.py`, and `dblift/core/migration/executor/execution_engine.py`
- Modify: `tests/unit/db/test_provider_interfaces.py`
- Modify: `tests/integration/matrix/test_dialect_capability_matrix.py`
- Create: `tests/unit/db/test_transaction_capability_substitution.py`

**Interfaces:**
- Consumes: `TransactionalProvider` ABC and plugin-owned `quirks_class.supports_transactions` metadata.
- Produces: `isinstance(provider, TransactionalProvider)` is true exactly for providers that implement usable begin/commit/rollback behavior.

- [ ] **Step 1: Replace inheritance-shape tests with behavioral conformance tests**

Add assertions that relational providers are transactional and document-store providers are not:

```python
assert isinstance(sqlite_provider, TransactionalProvider)
assert not isinstance(cosmos_provider, TransactionalProvider)
assert not isinstance(mongodb_provider, TransactionalProvider)
```

For every registered plugin, assert agreement between the interface and the plugin-owned capability without constructing a provider or opening a connection:

```python
for plugin in ProviderRegistry.list_plugins():
    quirks_class = plugin.quirks_class or BaseQuirks
    assert issubclass(plugin.provider_class, TransactionalProvider) is bool(
        quirks_class.supports_transactions
    )
```

- [ ] **Step 2: Verify the conformance test fails**

```bash
.venv/bin/python -m pytest \
  tests/unit/db/test_provider_interfaces.py \
  tests/unit/db/test_transaction_capability_substitution.py \
  tests/integration/matrix/test_dialect_capability_matrix.py -q
```

Expected: document providers currently appear transactional because `BaseProvider` inherits `TransactionalProvider`.

- [ ] **Step 3: Segregate the inheritance hierarchy**

Remove `TransactionalProvider` from `BaseProvider`'s bases. Add it explicitly to the two transaction-owning roots:

```python
class SqlAlchemyProvider(NativeProvider, TransactionalProvider):
    """SQLAlchemy-backed provider with explicit transaction control."""


class SQLiteProvider(NativeProvider, TransactionalProvider):
    """SQLite provider with explicit transaction control."""
```

All SQLAlchemy-backed provider subclasses inherit the truthful capability automatically. Remove the no-op begin/commit/rollback implementations from CosmosDB and MongoDB.

- [ ] **Step 4: Make `TransactionPolicy` use the segregated interface**

Replace the current inverted fallback, which treats a provider outside the interface as transactional, with the truthful interface test:

```python
provider_supports_transactions = isinstance(provider, TransactionalProvider)
```

Remove the `supports_transactions()` overrides from CosmosDB and MongoDB together with their no-op transaction methods. Keep `TransactionalProvider.supports_transactions()` temporarily for source compatibility on transactional providers, but do not use it for runtime dispatch. Use `provider.quirks.supports_transactions` only for declarative/offline capability reporting. Treat disagreement between the runtime interface and quirks as a provider contract error in conformance tests rather than silently choosing one.

- [ ] **Step 5: Guard every generic transaction caller**

Replace `hasattr(self, "commit_transaction")` in `_create_data_table_if_not_exists` with an explicit interface check:

```python
if isinstance(self, TransactionalProvider):
    self.commit_transaction()
```

Do not add transaction methods back to the universal base.

For each file listed in **Files**, classify every begin/commit/rollback call as one of:

- the receiver is statically a `TransactionalProvider`;
- the call is inside `isinstance(provider, TransactionalProvider)`;
- the command rejects a provider without that capability before reaching the call.

Add focused tests for the generic command paths that document providers can reach. The tests must fail if a missing transaction method is called.

- [ ] **Step 6: Run provider and migration execution verification**

```bash
.venv/bin/python -m pytest tests/unit/db tests/unit/core/migration/executor tests/integration/matrix -q
.venv/bin/python -m mypy dblift/db/base_provider.py dblift/db/sqlalchemy_provider.py dblift/db/plugins/sqlite/provider.py dblift/db/plugins/cosmosdb/provider.py dblift/db/plugins/mongodb/provider.py dblift/core/migration/executor/transaction_policy.py --config-file pyproject.toml --show-error-codes
isort --check --diff dblift/db dblift/core/migration/executor/transaction_policy.py tests/unit/db
flake8 --config=.flake8 dblift/db dblift/core/migration/executor/transaction_policy.py
black --check dblift/db tests/unit/db
lint-imports --config .importlinter
```

- [ ] **Step 7: Commit and review PR 2**

Use focused commits:

```bash
git commit -m "test: define truthful transaction capabilities"
git commit -m "refactor: segregate transactional providers"
```

Review every direct begin/commit/rollback call and confirm it is either guarded by `TransactionalProvider` or confined to a class that implements that interface. Run the complete unit suite before opening the PR.

---

### Task 5: Define a StateManager-owned validation snapshot

**Files:**
- Modify: `dblift/core/migration/state/migration_state.py`
- Modify: `dblift/core/migration/state/migration_state_manager.py:55`
- Modify: `dblift/core/migration/scripting/migration_script_manager.py:279`
- Modify: `dblift/core/migration/executor/migration_executor.py:100`
- Create: `tests/unit/core/migration/state/test_validation_snapshot.py`

**Interfaces:**
- Consumes: ScriptManager discovery and HistoryManager history reads.
- Produces: immutable `MigrationValidationSnapshot` values through `MigrationStateManager.build_validation_snapshot`.

- [ ] **Step 1: Add snapshot tests with real temporary scripts and SQLite history**

Verify one call returns the full resolved catalog, the filtered catalog, complete history, version-scoped history, history-table existence, directory existence, and the supplied strict-mode flag. Count one ScriptManager load and one HistoryManager read per read phase. Verify that passing the migrate command's already-resolved catalog and preloaded history performs no second read. Verify a new snapshot after a callback or write sees changed data.

- [ ] **Step 2: Add the immutable input type**

```python
@dataclass(frozen=True)
class MigrationValidationSnapshot:
    resolved_migrations: tuple[Migration, ...]
    selected_migrations: tuple[Migration, ...]
    all_applied_migrations: tuple[Migration, ...]
    scoped_applied_migrations: tuple[Migration, ...]
    history_table_exists: bool
    scripts_directory_exists: bool
    strict_mode: bool
```

This type carries data only. It contains no validation verdicts and performs no discovery.

- [ ] **Step 3: Build it in StateManager**

`build_validation_snapshot` accepts `scripts_dir`, `command`, recursive-directory options, all five version/tag filters, `strict_mode`, and an optional `MigrationReadSnapshot`. It also accepts optional `resolved_migrations` and `applied_migrations`; when supplied by migrate after its lock/read phase, those values must win and no manager read may occur.

Add `MigrationScriptManager.migration_directory_exists(path) -> bool` so filesystem status remains a ScriptManager collection concern. StateManager asks ScriptManager and HistoryManager for their respective data, prunes scripts below the highest baseline, applies one canonical selector, and scopes history by version filters. It does not perform duplicate, checksum, strict-order, failed-row, reappeared-script, format, or Flyway-compatibility validation.

- [ ] **Step 4: Construct StateManager before Validator**

In `MigrationExecutor.__init__`, create `MigrationRules`, then StateManager, then Validator. This establishes the data direction before Task 6 changes command call sites. Preserve the existing shared instances of ScriptManager and HistoryManager.

- [ ] **Step 5: Run focused state tests and commit**

```bash
.venv/bin/python -m pytest tests/unit/core/migration/state/test_validation_snapshot.py tests/unit/core/migration/test_migration_model_boundaries.py -q
git add dblift/core/migration/state tests/unit/core/migration/state/test_validation_snapshot.py
git commit -m "feat: add state-managed validation snapshots"
```

### Task 6: Remove duplicate filtering and direct validator collection

**Files:**
- Create: `dblift/core/migration/state/migration_selector.py`
- Modify: `dblift/core/migration/state/migration_state_manager.py:544`
- Modify: `dblift/core/sql_validator/migration_validator.py:98`
- Delete: `dblift/core/sql_validator/_migration_filter.py`
- Modify: `dblift/core/migration/executor/migration_executor.py:100`
- Modify: `dblift/core/migration/executor/migration_helpers.py:90`
- Modify: `dblift/core/migration/history/migration_history_manager.py`
- Modify: `dblift/core/sql_validator/_flyway_compatibility.py`
- Modify: `dblift/core/migration/commands/validate_command.py:89`
- Modify: `dblift/core/migration/commands/migrate_command.py`
- Modify: `tests/unit/core/sql_validator/test_validation_entrypoint_parity.py`
- Modify: `tests/unit/core/sql_validator/test_strict_validate_command.py`
- Modify: `tests/unit/core/sql_validator/test_flyway_compatibility.py`
- Modify: `tests/unit/core/migration/commands/test_command_read_reuse.py`
- Modify: `tests/unit/core/migration/commands/test_migrate_command_catalog_filters.py`
- Modify: `tests/unit/core/migration/commands/test_baseline_validate_commands.py`

**Interfaces:**
- Consumes: `MigrationValidationSnapshot` from Task 5.
- Produces: `select_migrations(...) -> List[Migration]` and `MigrationValidator.validate_snapshot(snapshot, command) -> ValidationResult`.

- [ ] **Step 1: Pin the normalization discrepancy**

Add a failing test proving string and sequence filters normalize identically:

```python
assert select_migrations(migrations, tags=" alpha, beta ") == select_migrations(
    migrations,
    tags=[" alpha", "beta "],
)
```

- [ ] **Step 2: Extract one pure selector**

Move normalization and filter predicates into `migration_selector.py`. Use the shared `compare_versions` utility directly; do not pass a manager instance into pure functions.

```python
def normalize_filter(value: Optional[Sequence[str]]) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.split(",")
    return [str(item).strip() for item in value if str(item).strip()]
```

- [ ] **Step 3: Inject StateManager and quirks into Validator**

Add keyword-only `state_manager` and `quirks` dependencies to the existing 4.x constructor. `MigrationExecutor` passes its single StateManager and the already-resolved `provider.quirks`. Retain the current positional ScriptManager and HistoryManager arguments for 4.x source compatibility, but stop using or exposing them for collection inside validation rules. When external code omits `state_manager`, build the compatibility StateManager once in the constructor from those existing collaborators and `MigrationRules(log)`. Validator must not import `ProviderRegistry` or recover configuration through HistoryManager. Update validator fixtures to inject StateManager and a quirks instance explicitly.

- [ ] **Step 4: Make validation pure over the snapshot**

Add `validate_snapshot` and move the validation pipeline to it. It may call validator rule helpers, but it must not call ScriptManager, HistoryManager, ProviderRegistry, or StateManager.

```python
def validate_snapshot(
    self,
    snapshot: MigrationValidationSnapshot,
    command: str = "migrate",
) -> ValidationResult:
    validation_result = ValidationResult()
    issues: List[str] = []
    return self._validate_prepared_migrations(
        valid_scripts=list(snapshot.selected_migrations),
        all_valid_scripts=list(snapshot.resolved_migrations),
        applied_migrations=list(snapshot.scoped_applied_migrations),
        repeatable_history=list(snapshot.all_applied_migrations),
        validation_result=validation_result,
        issues=issues,
        history_table_exists=snapshot.history_table_exists,
        command=command,
        strict_mode=snapshot.strict_mode,
    )
```

Handle a missing scripts directory and the strict-mode empty-catalog case exclusively from snapshot fields. Change `_validate_prepared_migrations` to accept `strict_mode` explicitly. Replace `self.script_manager.compare_versions` with the shared `compare_versions` function.

- [ ] **Step 5: Route commands through StateManager**

`ValidateCommand` and `MigrateCommand` ask StateManager for the snapshot and pass it to `validate_snapshot`. `MigrationHelpers.validate_migrations_for_migrate` accepts a snapshot rather than directory/managers/preloaded-data arguments. Refresh snapshots only at existing callback, lock, and write boundaries.

- [ ] **Step 6: Retain the 4.x entry points as StateManager adapters**

`MigrationValidator` is exported by `dblift.core.sql_validator`, and the 4.5.0 performance spec requires both entry points. Keep `validate_migrations` and `validate_resolved_migrations` as thin adapters that call `self.state_manager.build_validation_snapshot(...)` and then `validate_snapshot`. They contain no discovery, filtering, history reads, or validation rules. Update command tests to prove commands call StateManager directly; add adapter parity tests to prove external 4.x callers receive unchanged results.

- [ ] **Step 7: Delete the duplicate module and verify ownership**

Delete `_migration_filter.py` after all callers use `migration_selector.py`. Assert by source scan that command and validator modules contain no direct script/history collection calls:

```python
for path in command_and_validator_paths:
    source = path.read_text()
    assert ".get_migration_scripts(" not in source
    assert ".load_migration_scripts(" not in source
    assert ".get_applied_migrations(" not in source
```

- [ ] **Step 8: Route Flyway compatibility data through StateManager**

The existing `_flyway_compatibility.py` reads provider tables through Validator. Move its table reads into a HistoryManager method returning an immutable `FlywayCompatibilitySnapshot`; expose that snapshot through StateManager; make the compatibility comparison a pure function over the snapshot. Keep the three 4.x Validator wrappers, but make them obtain data only from StateManager and delegate every rule to the pure comparison function. Cache the immutable snapshot in StateManager's read phase rather than on Validator. Add parity tests for missing tables, row-count mismatch, type mapping, checksum mismatch, and successful comparison.

- [ ] **Step 9: Run branch verification and review PR 3**

```bash
.venv/bin/python -m pytest tests/unit/core/sql_validator tests/unit/core/migration/state tests/unit/core/migration/commands -q
.venv/bin/python -m mypy dblift/core/sql_validator dblift/core/migration/state dblift/core/migration/commands --config-file pyproject.toml --show-error-codes
isort --check --diff dblift/core/sql_validator dblift/core/migration/state dblift/core/migration/commands tests/unit/core/sql_validator tests/unit/core/migration/state
flake8 --config=.flake8 dblift/core/sql_validator dblift/core/migration/state dblift/core/migration/commands
black --check dblift/core/sql_validator dblift/core/migration/state dblift/core/migration/commands
lint-imports --config .importlinter
.venv/bin/python -m pytest tests/unit -q
```

Review specifically that StateManager aggregates data without absorbing validation rules and that ScriptManager remains the only callback discovery/event-matching owner.

---

### Task 7: Move filename resolution out of the mutable migration entity

**Files:**
- Create: `dblift/core/migration/migration_types.py`
- Create: `dblift/core/migration/scripting/filename_parser.py`
- Modify: `dblift/core/migration/scripting/migration_script_manager.py:1`
- Modify: `dblift/core/migration/migration.py:46`
- Modify: `dblift/core/migration/migration.py:363`
- Modify: `dblift/core/migration/migration.py:733`
- Modify: `dblift/core/migration/__init__.py`
- Create: `tests/unit/core/migration/scripting/test_filename_parser_contract.py`
- Modify: `tests/unit/core/migration/scripting/test_filename_resolution_performance.py`
- Modify: `tests/unit/core/migration/scripting/test_migration_script_manager_callback_events.py`
- Modify: `tests/unit/core/migration/test_migration_format_detection.py`
- Modify: `tests/unit/core/migration/test_migration_immutability.py`
- Modify: `tests/unit/core/migration/test_migration_model_boundaries.py`

**Interfaces:**
- Consumes: current callback prefixes, tag grammar, version grammar, and `MigrationFormatDetector`.
- Produces: `parse_migration_filename(filename: str) -> FilenameMetadata` owned by the scripting package.

- [ ] **Step 1: Add characterization tests for every filename role**

Cover versioned SQL/Python, repeatable, undo, callback, malformed near-miss, unknown extension, tags, alphanumeric versions, and case handling. Verify callback event matching uses the same parsed metadata.

- [ ] **Step 2: Break the type cycle before extracting the parser**

Move `MigrationType` and `VERSIONED_SCRIPT_TYPES` to `migration_types.py`. Re-export both from `migration.py` and `dblift.core.migration` so existing imports continue to work. Update `_type_match.py` and the new parser to import from `migration_types.py`; this keeps the parser independent from the mutable `Migration` class.

- [ ] **Step 3: Define one immutable filename result**

```python
@dataclass(frozen=True)
class FilenameMetadata:
    migration_type: MigrationType
    version: Optional[str]
    description: str
    tags: tuple[str, ...]
    callback_event: Optional[str] = None
```

`filename_parser.py` owns callback event names and their delimiter-aware matching. ScriptManager re-exports compatibility helpers only where an existing import requires them.

- [ ] **Step 4: Make ScriptManager the production caller**

`MigrationScriptManager.parse_filename` delegates to `parse_migration_filename` and converts the immutable result to its existing tuple return value. Normal discovery passes the parsed metadata into migration construction exactly once.

- [ ] **Step 5: Remove the model-to-manager dependency**

Replace `Migration._parse_filename()` constructing `MigrationScriptManager` with a direct call to the pure parser during the compatibility construction path. Delete duplicated `_determine_type` regex logic after characterization tests show the canonical parser covers it.

- [ ] **Step 6: Run focused tests and commit**

```bash
.venv/bin/python -m pytest \
  tests/unit/core/migration/scripting/test_filename_parser_contract.py \
  tests/unit/core/migration/scripting \
  tests/unit/core/migration/test_migration_format_detection.py \
  tests/unit/core/migration/test_migration_immutability.py -q
git commit -m "refactor: centralize migration filename resolution"
```

### Task 8: Move SQL parsing off the normal migration data path

**Files:**
- Create: `dblift/core/migration/sql/migration_sql_parser.py`
- Modify: `dblift/core/migration/migration.py:621`
- Modify: `dblift/core/migration/executor/execution_engine.py:291`
- Modify: `dblift/core/migration/scripting/undo_script_generator/_generator.py:196`
- Create: `tests/unit/core/migration/sql/test_migration_sql_parser.py`
- Modify: `tests/unit/core/migration/test_migration_config_injection.py`
- Modify: `tests/unit/core/migration/test_migration_immutability.py`
- Modify: `tests/unit/core/migration/test_parse_sql_fallback.py`
- Modify: `tests/unit/core/migration/scripting/test_undo_script_generator.py`

**Interfaces:**
- Consumes: `_prepare_sql_statements` introduced in Task 3 and `SqlAnalyzer`.
- Produces: ExecutionEngine/parser services own SQL parsing; `Migration` remains a data carrier on all production paths.

- [ ] **Step 1: Inventory production callers and pin outputs**

Confirm the only production callers of `Migration.parse_sql_statements` are ExecutionEngine and undo generation. Add outcome tests for both before moving them.

- [ ] **Step 2: Give the SQL layer the canonical parse function**

Add a stateless helper in `migration_sql_parser.py`. Pass the existing analyzer and the exact source text explicitly:

```python
def parse_migration_sql(
    analyzer: SqlAnalyzer,
    content: str,
    log: Log,
) -> List[str]:
    try:
        statements = analyzer.split_statements(content)
        return [statement for statement in statements if statement.strip()]
    except Exception as exc:
        log.warning(f"Error using SqlAnalyzer: {exc}. Falling back to simple parser.")
        return [statement.strip() for statement in content.split(";") if statement.strip()]
```

Retain dialect-owned preprocessing in ExecutionEngine before this call.

- [ ] **Step 3: Keep one release-line compatibility shim**

Keep `Migration.parse_sql_statements` as a deprecated wrapper for the 4.x release line. It resolves the analyzer exactly as today, delegates to `parse_migration_sql`, and preserves canonical-only cache behavior. ExecutionEngine and undo generation must call the helper directly, so production parsing no longer lives on the entity. Record removal of the shim as a future major-version item rather than widening this fix.

- [ ] **Step 4: Verify model construction performs no manager creation**

Add a test that patches `MigrationScriptManager.__init__` to fail and confirms direct data construction still works. Add an AST/source assertion preventing imports from `migration.py` to `scripting.migration_script_manager`.

- [ ] **Step 5: Run branch verification and review PR 4**

```bash
.venv/bin/python -m pytest tests/unit/core/migration tests/unit/core/sql_parser -q
.venv/bin/python -m mypy dblift/core/migration --config-file pyproject.toml --show-error-codes
isort --check --diff dblift/core/migration tests/unit/core/migration
flake8 --config=.flake8 dblift/core/migration
black --check dblift/core/migration tests/unit/core/migration
lint-imports --config .importlinter
.venv/bin/python -m pytest tests/unit -q
```

Review that ScriptManager still owns all discovery and callback matching, StateManager still aggregates, and neither the model nor commands read the filesystem directly.

---

### Task 9: Final compatibility and publication gate for each branch

**Files:**
- Modify: `CHANGELOG.md`
- Modify: public API documentation only when a public compatibility shim changes.

**Interfaces:**
- Consumes: one completed branch at a time.
- Produces: a focused PR to `develop` with current behavior and verification documented.

- [ ] **Step 1: Run the complete required checks**

Use the repository's CI-equivalent Python versions and constraints. At minimum run:

```bash
.venv/bin/python -m pytest tests/unit -q
lint-imports --config .importlinter
.venv/bin/python -m mypy dblift/ --config-file pyproject.toml --show-error-codes
isort --check --diff dblift/ tests/ scripts/
flake8 --config=.flake8 dblift/
black --check --diff dblift/ tests/ scripts/
.venv/bin/python scripts/lint_patterns.py
.venv/bin/python scripts/check_api_docstrings.py --paths dblift/api dblift/cli dblift/core dblift/db --ratchet .docstring-ratchet.json
.venv/bin/python scripts/check_line_length.py
git diff --check origin/develop...HEAD
```

Run the relevant SQLite integration subset for execution and state branches. Run live database integration only where the repository's normal CI matrix provides credentials/containers; report unavailable infrastructure explicitly.

- [ ] **Step 2: Review observable compatibility**

Compare before/after command results for migrate, validate, info, undo, repair, baseline, and callback failures. Confirm no branch changes callback discovery order, state freshness, history rank semantics, transaction atomicity, or serialized result fields beyond the explicit transaction correction.

- [ ] **Step 3: Update the changelog**

Add one concise Unreleased entry describing the branch's user-visible correction. Do not combine all four branches into one changelog entry before they are merged.

- [ ] **Step 4: Verify repository identity and publication constraints**

```bash
git config user.name
git config user.email
git branch --show-current
git log --format='%an <%ae>%n%B' origin/develop..HEAD
git status --short
```

Confirm the branch begins with `fix/`, commits use the machine identity, no attribution trailer exists, and the worktree is clean.

- [ ] **Step 5: Open the PR and follow CI**

Open a PR to `develop` containing the concrete problem, resulting behavior, focused tests, full verification, and any unavailable integration infrastructure. Do not merge it. Follow all CI and coverage checks to completion and correct failures on the same branch.

## Deferred Lower-Severity Work

The following findings are intentionally excluded because they have a larger review surface and no equally direct correctness failure:

- split BaseCommand reporting from command orchestration and replace the 13-dependency context with command-specific dependencies;
- decompose BaseQuirks internally by concern while retaining its compatibility facade;
- replace UndoCommand's 480-line workflow with a StateManager-produced undo plan and smaller execution phases.

Re-audit these after the four fixes merge. The validation snapshot and truthful transaction interface should reduce the cost and risk of those later changes.

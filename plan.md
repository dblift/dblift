# Codebase Improvement Plan — Post Code-Review Evolutions

> Following up on the completed CODE_REVIEW.md (24/24 items addressed) and fresh sweep findings.

---

## Story 1: Decompose `export_schema()` god function (937 lines)

**File:** `core/migration/commands/export_schema_command.py`
**Effort:** Large | **Risk:** Medium

The `export_schema()` function handles 5+ responsibilities in a single 937-line function.
Three helper functions are also oversized: `_exclude_internal_objects()` (252 lines),
`_filter_objects()` (157 lines), `_get_managed_objects()` (314 lines).

### Approach: Extract Class — `SchemaExporter`

Create a `SchemaExporter` class that breaks the monolith into focused private methods:

1. **`_resolve_source()`** — Determine schema source (live DB, file model, database model)
2. **`_introspect_schema()`** — Run introspection pipeline for all object types
3. **`_apply_filters()`** — Orchestrate type/table/managed-object filtering
4. **`_exclude_internal_objects()`** — Filter out dblift system objects (exists, just move into class)
5. **`_resolve_managed_objects()`** — Determine managed vs unmanaged objects from migration history
6. **`_generate_files()`** — Write migration output files (single or split-by-type)
7. **`_build_result()`** — Assemble and return the export result summary

Keep `export_schema()` as a thin public entry point that instantiates `SchemaExporter` and
calls `exporter.run()`.

### Files to create/modify
- **Modify:** `core/migration/commands/export_schema_command.py` — extract class, keep public function as facade
- **No new files** — class lives in same module to avoid import changes

### Acceptance criteria
- `export_schema()` public function < 30 lines
- No method in `SchemaExporter` > 150 lines
- All existing tests pass unchanged (function signature preserved)

---

## Story 2: Decompose `_execute_on_test()` (707 lines) in round-trip tester

**File:** `core/validation/round_trip_tester.py`
**Effort:** Large | **Risk:** Medium

The `_execute_on_test()` method handles schema creation, cleanup, DDL execution,
transaction management, and result tracking in a single 707-line method, with
heavily interleaved database-specific logic.

### Approach: Extract Private Methods

Break into 5 focused methods within the existing `RoundTripTester` class:

1. **`_create_test_schema()`** — Schema creation with autocommit/transaction handling
2. **`_clean_test_schema()`** — Clean all existing objects before test
3. **`_execute_ddl_statements()`** — Execute CREATE statements with per-dialect error handling
4. **`_commit_test_transaction()`** — Commit/rollback with dialect-specific logic (Oracle autocommit, DB2 quirks)
5. **`_collect_execution_results()`** — Track and return execution results for comparison

`_execute_on_test()` becomes a coordinator calling these 5 methods in sequence.

Also decompose `_generate_create_statements()` (219 lines):
- **`_order_tables_by_dependency()`** — Dependency ordering logic
- **`_replace_schema_references()`** — Source-to-test schema name substitution

### Files to modify
- **Modify:** `core/validation/round_trip_tester.py`

### Acceptance criteria
- `_execute_on_test()` < 80 lines (coordinator only)
- No extracted method > 150 lines
- All validation tests pass unchanged

---

## Story 3: Decompose `_generate_basic_create_statement()` (633 lines) via dialect strategy

**File:** `core/sql_model/table.py`
**Effort:** Large | **Risk:** High (core DDL generation)

This single method generates CREATE TABLE DDL for all 6 SQL dialects with deeply
interleaved if/elif chains. The dialect-specific logic is tangled with shared logic.

### Approach: Extract Method per concern

Rather than a full strategy pattern (too much blast radius), extract dialect-specific
sections into private methods within `SqlTable`:

1. **`_format_table_header()`** — Table name with schema, TEMPORARY syntax by dialect
2. **`_resolve_primary_key()`** — Resolve multiple PK constraints, prefer composite PKs
3. **`_generate_column_definition()`** — Single column DDL with type normalization, identity, collation
4. **`_generate_column_definitions()`** — Loop over columns, delegate to above
5. **`_generate_inline_constraints()`** — Non-inline constraints (FK, CHECK, UNIQUE)
6. **`_generate_table_suffix()`** — Partitioning, storage params, engine, INHERITS

`_generate_basic_create_statement()` becomes a coordinator assembling these pieces.

### Files to modify
- **Modify:** `core/sql_model/table.py`

### Acceptance criteria
- `_generate_basic_create_statement()` < 80 lines
- No extracted method > 120 lines
- All SQL generation and parser tests pass unchanged

---

## Story 4: Add exception context to bare `raise` in snapshot repository

**File:** `core/migration/snapshots/schema_snapshot_repository.py`
**Effort:** Small | **Risk:** Low

Three bare `raise` statements at lines 146, 311, 350 re-raise exceptions after
rollback attempts without adding context about which operation failed.

### Approach

Wrap each in a contextual log message before the bare `raise`:

```python
# Before:
except Exception as e:
    try:
        connection.rollback()
    except Exception:
        pass
    raise

# After:
except Exception as e:
    self.log.error(f"Failed to save snapshot for schema '{schema}': {e}")
    try:
        connection.rollback()
    except Exception as rollback_err:
        self.log.debug(f"Rollback also failed: {rollback_err}")
    raise
```

Keep the bare `raise` (preserves original traceback) but add logging for diagnostics.

### Files to modify
- **Modify:** `core/migration/snapshots/schema_snapshot_repository.py`

### Acceptance criteria
- All 3 bare `raise` sites have contextual error logging before re-raise
- Rollback failure handlers log at debug level
- All snapshot tests pass unchanged

---

## Story 5: Standardize auto-commit behavior across DB plugins

**File:** All `connection_manager.py` files in `db/plugins/`
**Effort:** Medium | **Risk:** Medium (transaction semantics)

Current state:
| Plugin | Auto-commit |
|--------|-------------|
| Oracle | `setAutoCommit(False)` — explicit |
| PostgreSQL | `setAutoCommit(False)` — explicit |
| MySQL | `setAutoCommit(False)` — explicit |
| DB2 | Not set — driver default |
| SQL Server | Not set — driver default |

DB2 and SQL Server rely on driver defaults, which may differ by driver version.

### Approach

1. Add explicit `setAutoCommit(False)` to DB2 and SQL Server connection managers
   after connection creation
2. Add a comment in each connection manager explaining the auto-commit choice
3. Document in `BaseConnectionManager` (if it exists) or in code comments that
   all JDBC providers should explicitly set auto-commit to False

### Files to modify
- **Modify:** `db/plugins/db2/db2/connection_manager.py`
- **Modify:** `db/plugins/sqlserver/sqlserver/connection_manager.py`

### Acceptance criteria
- All JDBC-based plugins explicitly call `setAutoCommit(False)` after connection creation
- Integration tests pass (if available)

---

## Story 6: Standardize lock table schema across plugins

**File:** All `locking_manager.py` files in `db/plugins/`
**Effort:** Medium | **Risk:** Low

Lock table column names and types differ across plugins. The `BaseLockingManager`
abstract class was already created but doesn't enforce column schema.

### Approach

1. Define standard column names in `BaseLockingManager`:
   - `lock_key VARCHAR` — lock identifier
   - `locked_by VARCHAR` — hostname/process holding lock
   - `locked_at TIMESTAMP` — when lock was acquired
2. Add a class-level `DEFAULT_LOCK_TABLE` constant to each locking manager
   (matching the pattern from Story in previous commit for history tables)
3. Use native case per database (UPPERCASE for Oracle/DB2, lowercase for others)

### Files to modify
- **Modify:** `db/plugins/base_locking_manager.py` — add column name constants
- **Modify:** Each plugin's `locking_manager.py` — use constants, add `DEFAULT_LOCK_TABLE`

### Acceptance criteria
- All locking managers use consistent column naming from base class constants
- Lock table name uses native case per database dialect
- All locking tests pass unchanged

---

## Execution Order

| Priority | Story | Effort | Dependencies |
|----------|-------|--------|-------------|
| 1 | Story 4: Snapshot repository exception context | Small | None |
| 2 | Story 5: Auto-commit standardization | Medium | None |
| 3 | Story 6: Lock table schema standardization | Medium | None |
| 4 | Story 1: Decompose `export_schema()` | Large | None |
| 5 | Story 2: Decompose `_execute_on_test()` | Large | None |
| 6 | Story 3: Decompose `_generate_basic_create_statement()` | Large | None |

Stories 1-3 (the large decompositions) are independent but should be done one at a time
to keep PRs reviewable. Stories 4-6 can be done in parallel as they touch different files.

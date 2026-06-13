# dblift — Architecture Overview

**Reading time: ~30 minutes.** This document is the canonical
DD-facing entry point. It maps the system end-to-end and links to
operational detail where appropriate. For per-component deep dives,
see [`docs/architecture/detailed-architecture.md`](docs/architecture/detailed-architecture.md).

## 1. What dblift is

A Python library + CLI that applies versioned SQL migrations to seven
relational / NoSQL engines through a single surface. Positioned
alongside Flyway: users author `V<version>__<desc>.sql` scripts,
dblift runs them in order, tracks execution in a schema history table,
and supports undo, repair, baseline, and drift detection.

### 1.1 Users

| User | Primary interface |
|---|---|
| Application developer | `dblift migrate` in CI/CD pipelines |
| DBA | `dblift clean`, `baseline`, `repair`, `export-schema` |
| IDE / tooling integrator | `from api import DBLiftClient` programmatically |
| SRE | `--log-format json`, `info --format json` for aggregation |

### 1.2 Supported dialects

PostgreSQL, Oracle, MySQL, SQL Server, DB2, SQLite, Cosmos DB.

Per-dialect capabilities (transactions, transactional DDL, schema
requirement, identifier casing, clean strategy) are declared in one
authoritative table — [ADR-0007](docs/adr/0007-dialect-capabilities-matrix.md).

### 1.3 Runtime

Python 3.11+ ([ADR-0004](docs/adr/0004-bump-minimum-python-to-3-11.md)).
Relational providers use native Python database drivers through SQLAlchemy;
Cosmos DB uses `azure-cosmos`; SQLite uses stdlib.

### 1.4 Licensing

Proprietary. JWT-signed license token required for all non-`license`
subcommands; `core/licensing/`. See
[`docs/architecture/licensing.md`](docs/architecture/licensing.md).

## 2. Containers (C4 level 2)

```
┌──────────────────────────────────────────────────────────────────────┐
│                            dblift (Python)                           │
│                                                                      │
│  ┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐   │
│  │    cli/      │────▶│     api/         │────▶│     core/       │   │
│  │  argparse    │     │  DBLiftClient    │     │   business      │   │
│  │  entry point │     │  public surface  │     │   logic +       │   │
│  └──────────────┘     └──────────────────┘     │  orchestration  │   │
│                                                 └────────┬────────┘   │
│                                              ┌───────────▼────────┐   │
│                                              │       db/          │   │
│                                              │  provider plugins  │   │
│                                              └─────┬────┬────┬────┘   │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ External: native DB drivers, Azure Cosmos SDK, sqlite3 stdlib│    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

| Container | Responsibility | Entry point |
|---|---|---|
| `cli/` | argparse tree, command dispatch, output routing, license gate | `cli/main.py::main` |
| `api/` | Programmatic surface: `DBLiftClient`, events | `api/__init__.py` |
| `core/` | Business logic: migrations, parsers, generators, validators | mostly internal; selected `core.migration` and `core.logger` exports are public per `docs/semver-policy.md` |
| `db/` | Provider plugins per dialect (native SQLAlchemy, SDK, or stdlib) | `db/provider_registry.py` |
| `config/` | `DbliftConfig` loading + validation | `config/__init__.py` |

## 3. Key components

### 3.1 `cli/`

| Module | Role |
|---|---|
| `main.py` | Entry point; parses argv, gates license, dispatches. |
| `_parser_setup.py` | Builds the argparse tree with `parents=[]` shared flag clusters ([ADR-0009](docs/adr/0009-argparse-parents-parents-parents.md)). |
| `_command_handlers.py` | One `_handle_<cmd>` per subcommand. |
| `_output.py` | `CommandOutput` routes stdout (machine payload) vs stderr (status) ([ADR-0008](docs/adr/0008-command-output-abstraction.md)). |
| `_constants.py` | `MACHINE_READABLE_FORMATS`, `VALIDATE_SQL_FORMATS` single source of truth. |

### 3.2 `api/`

Sole public class is `DBLiftClient`. 14 user-facing operations:
`migrate`, `info`, `validate`, `diff`, `generate_sql_from_diff`,
`undo`, `generate_undo_script`, `generate_undo_scripts`, `clean`,
`baseline`, `repair`, `import_flyway`, `export_schema`, `snapshot`.

Three construction helpers: `from_config`, `from_config_file`,
`from_sqlalchemy`. Plus `EventEmitter` / `EventType` for pub/sub.

### 3.3 `core/migration/`

Where orchestration lives.

| Submodule | Role |
|---|---|
| `migration.py` | `Migration` model (file parsing, checksum, SQL extraction). Cache is canonical-only ([ADR-0010](docs/adr/0010-migration-sql-statements-cache-immutability.md)). |
| `_type_match.py` | `MigrationType` helpers: `is_versioned`, `is_migration_type`, `migration_type_name` ([ADR-0006](docs/adr/0006-migration-type-match-helpers.md)). |
| `commands/` | One file per CLI command. All inherit `BaseCommand` which provides `_run_preflight()` ([ADR-0011](docs/adr/0011-command-preflight-helper.md)). |
| `executor/` | `MigrationExecutor` (command-facing) + `ExecutionEngine` (per-migration). |
| `executors/` | Per-format (SQL, Python) via `MigrationExecutorFactory`. |
| `history/` | `MigrationHistoryManager` — reads/writes `dblift_schema_history`. |
| `placeholders/` | `${variable}` substitution (pre-tokeniser). |
| `scripting/` | Filename parsing; undo-script generator. |
| `snapshots/` | JSON schema model for diff / export-schema. |
| `sql/` | Statement classifier (DDL/DML/QUERY); execution service. |
| `state/` | Display-state classifiers (`SUCCESS`, `PENDING`, `OUT_OF_ORDER`, …). |

### 3.4 `core/sql_model/` and `core/sql_parser/`

- `sql_model/` — domain model (Table, Column, Constraint, Index,
  View, Trigger, …). `dialect.py` holds `DialectEnum`, the capability
  matrix, and identifier quoting.
- `sql_parser/` — dialect-specific tokeniser + statement splitter +
  object extractor. One subpackage per dialect.

`core/sql_parser/oracle/oracle_parser.py` is 1 402 lines and accounts
for 16 of 41 fixes since v1.1.0. Splitting it is tracked as **Phase
Oracle** in the [stabilization plan](docs/stabilization-plan.md), with
the target structure and migration order in
[ADR-0012](docs/adr/0012-oracle-parser-split.md). The
conformance-first harness lives at
`tests/unit/core/sql_parser/oracle/test_oracle_parser_conformance.py`.
See [`docs/architecture/sql-parsing.md`](docs/architecture/sql-parsing.md)
for current detail.

### 3.5 `db/`

| Module | Role |
|---|---|
| `provider_interfaces.py` | Abstract capability mixins: `ConnectionProvider`, `QueryProvider`, `SchemaProvider`, `TransactionalProvider`, `MigrationProvider`. |
| `base_provider.py` | Common lifecycle. |
| `provider_registry.py` | Auto-discovery of `db/plugins/`. |
| `plugins/<dialect>/` | Per-dialect implementation; 5 components (connection, query, history, locking, schema_operations). |

See [`docs/architecture/database-providers.md`](docs/architecture/database-providers.md).

## 4. Data flow — `dblift migrate`

```
shell
  │
  ▼
cli/main.py::main()
  │  parse argv; validate license
  ▼
cli._command_handlers._handle_migrate(ctx)
  │  extract filters, dry_run
  ▼
api.DBLiftClient.migrate(...)
  │  construct MigrationExecutor(provider, config, log)
  ▼
core.migration.executor.MigrationExecutor.execute()
  │
  │  1. _run_preflight()  ─── ADR-0011 canonical order
  │        ├─ _ensure_connected()
  │        ├─ create_schema_and_history_table()  (skipped in --dry-run)
  │        └─ _populate_database_info(result)
  │  2. scan scripts_dir → pending migrations
  │  3. acquire_migration_lock()
  │  4. for each pending migration:
  │       ├─ ExecutionEngine.execute_migration()
  │       │    ├─ parse_sql_statements(content_override=substituted)  ← ADR-0010
  │       │    ├─ begin_transaction() (if dialect supports ── ADR-0007)
  │       │    ├─ SqlExecutionService.execute_statement() × N
  │       │    ├─ history_manager.record_migration()
  │       │    └─ commit / rollback
  │       └─ journal flushed to log report
  │  5. release_migration_lock()
  │  6. return MigrateResult
  ▼
formatter → CommandOutput.machine() or ctx.log  ← ADR-0008
```

### 4.1 Contracts the system guarantees

| Contract | Guarded by |
|---|---|
| `migrate --dry-run` = zero DB writes (byte-identical) | `tests/integration/matrix/test_dry_run_purity.py` (SHA-256 invariant) |
| `--format json` stdout is parseable JSON only | `tests/integration/matrix/test_json_output_contract.py` (subprocess) |
| Top-level flags (`--config`, `--dry-run`, `--scripts`) preserved across all subcommands | `tests/unit/cli/test_parser_invariants.py` (210 parametrised cases) |
| `DialectCapabilities` matrix matches provider runtime behaviour | `tests/unit/core/sql_model/test_dialect_capabilities.py` (conformance tests) |
| Command preflight order is connect → history → populate | `tests/unit/core/migration/commands/test_preflight_ordering.py` |

### 4.2 Transactionality by dialect

Per ADR-0007 matrix:

| Dialect | `supports_transactions` | `supports_transactional_ddl` |
|---|---|---|
| PostgreSQL | ✓ | ✓ |
| SQL Server | ✓ | ✓ |
| DB2 | ✓ | ✓ |
| SQLite | ✓ | ✓ |
| Oracle | ✓ | ✗ (DDL auto-commits) |
| MySQL | ✓ | ✗ (DDL auto-commits) |
| Cosmos DB | ✗ (NoSQL, optimistic concurrency) | ✗ |

## 5. Public API surface

`api/__init__.py` exports exactly three symbols:

```python
from api import DBLiftClient, EventEmitter, EventType
```

Everything else (`core/`, `cli/`, `db/`, `config/` internals) is
private and NOT a stable import surface. The `api` package ships a
PEP 561 `py.typed` marker; the stability policy is documented in
[`docs/semver-policy.md`](docs/semver-policy.md) and pinned in
`tests/unit/api/test_public_api_surface.py`.

### 5.1 Stability policy

- `DBLiftClient` methods keep backwards-compatible signatures within
  a minor version.
- Adding a method or optional keyword argument is MINOR.
- Removing a method / keyword / changing semantics is MAJOR —
  requires an ADR superseding.
- `MigrationType` enum is public: adding a member is MINOR; removing
  or renaming is MAJOR.

## 6. Configuration

`DbliftConfig` (`config/dblift_config.py`) is the single runtime
configuration object. Sources merged in order (later wins):

1. YAML config file via `--config` or `DBLIFT_CONFIG`.
2. Environment variables (`DBLIFT_DB_URL`, `DBLIFT_DB_USERNAME`, …).
3. CLI overrides (`--db-url`, `--db-username`, `--scripts`, …).

Nested sections: `database`, `migrations`, `logging`, `validation`.
See [`docs/architecture/configuration.md`](docs/architecture/configuration.md).

### 6.1 Operations and recovery

Failure modes that can leave a target DB in an inconsistent state
(Oracle `DBMS_LOCK` timeout, schema-history corruption, partial DDL on
non-transactional-DDL dialects, network partition) are covered by step-by-step runbooks in
[`docs/operations/recovery/`](docs/operations/recovery/index.md). Each
runbook documents symptoms, immediate response, recovery procedure,
verification, and prevention.

## 7. Testing strategy

Three tiers, each bounded by scope and runtime:

| Tier | Location | Runtime | Triggers on PR |
|---|---|---|---|
| **Unit** | `tests/unit/` | < 5 min. No DB. | `unit-tests.yml` (manual dispatch) |
| **Matrix regression** | `tests/integration/matrix/` | < 1 min. SQLite only, no Docker. Subprocess CLI + in-process parsers. | `matrix-tests.yml` on every PR |
| **Full integration** | `tests/integration/` (excl. matrix) | ~20 min. Docker PG/MySQL/SQL Server/DB2/Oracle/Cosmos Emulator. | `integration-tests-new.yml` (manual dispatch, respects GH Actions budget) |

The **matrix suite** is the contract layer — each test file guards
one invariant surfaced by the stabilization program (see
[`docs/stabilization-plan.md`](docs/stabilization-plan.md)):

| File | Invariant |
|---|---|
| `test_cli_contract.py` | Missing config / bad license / help handling. |
| `test_dialect_capability_matrix.py` | Provider runtime ≡ matrix declaration. |
| `test_dry_run_completeness.py` | `clean --dry-run` lists every droppable object type. |
| `test_dry_run_purity.py` | `migrate --dry-run` / `clean --dry-run` = zero writes. |
| `test_json_output_contract.py` | `--format json` stdout is parseable; banner on stderr. |
| `test_parent_flag_behaviour.py` | `--config` / `--dry-run` / `--scripts` preserved by every subcommand. |
| `test_url_type_inference.py` | `--db-url <scheme>://…` infers `config.database.type`. |

## 8. Quality gates in CI

Every PR runs:

| Gate | Blocks on |
|---|---|
| `code-quality.yml` / `black --check` | Any format divergence (target py311/py312) |
| `code-quality.yml` / `isort --check` | Import ordering |
| `code-quality.yml` / `flake8` | 8 rules still ignored (shrinking) |
| `code-quality.yml` / `mypy` | Source directories |
| `code-quality.yml` / `scripts/lint_patterns.py` | AST rules: `cli-print-stdout`, `enum-str-conversion` |
| `security.yml` / `bandit --severity-level high` | Any HIGH finding (zero today) |
| `security.yml` / `pip-audit` | Any runtime dependency CVE |
| `security.yml` / `gitleaks` | Secret detection with documented allowlist |
| `complexity.yml` / `xenon` | Cyclomatic complexity ratchet (current `F/F/F`, tightening tracked) |
| `matrix-tests.yml` | The matrix regression suite |

Quality baselines and targets are recorded in `docs/stabilization-plan.md`
§"Metrics and targets".

### 8.1 Performance benchmarks

`pytest-benchmark` baselines for the CPU-bound hot paths live in
`tests/benchmarks/`. They **do not** run on every PR — shared GitHub
Actions runners produce ±30% variance between runs on identical code,
which is not a useful signal. Instead:

- `tests/benchmarks/baseline.json` is committed as an audit artefact
  (expected numbers on reference hardware).
- `.github/workflows/benchmarks.yml` runs the suite on manual dispatch
  and uploads a JSON artefact for offline comparison with
  `pytest-benchmark compare`.
- Maintainers run the suite locally before any PR that touches a hot
  path (parser, placeholder service, type-match helpers).

Rationale and the updating procedure are in
[`tests/benchmarks/README.md`](tests/benchmarks/README.md).

## 9. Stability mechanisms (stabilization program)

The project is running a declared stabilization program (v1.3.x →
v2.0) in response to a measured ~44% fix ratio in the window
v1.1.0–v1.3.1. The program's principle: encode invariants in CI, not
in prose.

| Concern | Mechanism |
|---|---|
| stdout machine contract | `CommandOutput` + matrix `test_json_output_contract` |
| `--dry-run` purity | SHA-256 DB fingerprint invariant |
| argparse flag preservation | 210 parametrised cases + meta-property "every top-level flag must be covered or exempted" |
| `MigrationType` enum/string comparison | single `_type_match.py` + lint `enum-str-conversion` |
| dialect capability drift | conformance test (provider runtime ≡ declared matrix) |
| `Migration` cache canonicality | ordering tests on `parse_sql_statements(content_override=…)` |
| command lifecycle ordering | `test_preflight_ordering` |
| secrets in history | `.gitleaks.toml` + `docs/security-incidents.md` append-only log |

Every structural decision is an ADR under `docs/adr/` (0001-0011
shipped). Superseded ADRs remain with a `Superseded by <N>` header.

## 10. Build and release

| Artefact | Source | Command |
|---|---|---|
| Wheel / sdist | `pyproject.toml` | `python -m build` |
| Cython-accelerated modules | `setup_cython.py` | Optional, for CPU-critical paths |
| Docker image | `Dockerfile` | `docker build` |
| MkDocs site | `mkdocs.yml`, `docs/` | `mkdocs build` |

Releases follow [Keep a Changelog](https://keepachangelog.com/) and
Semantic Versioning. `CHANGELOG.md` holds the history. Pre-release
CVE triage is mandatory (`pip-audit` clean).

## 11. Known-deferred work

Honest ledger of items out of scope for the current program but
tracked for later:

| Item | Tracked in |
|---|---|
| Oracle parser split (1402 → modules ≤ 300 lines) | Phase Oracle, stabilization plan |
| Full `CommandLifecycle` with hooks | ADR-0011 §Follow-ups |
| Full `Migration` immutability (frozen dataclass) | ADR-0010 §Follow-ups |
| Declarative argparse spec | ADR-0009 §Follow-ups |
| Mypy strict mode across all modules | Phase 0 deferred PR-0D |
| Coverage floor as blocking gate | Phase 0 deferred PR-0B |

## 12. Where to go next

| Audience | Start here |
|---|---|
| DD reviewer | This document (you're here) + [`docs/stabilization-plan.md`](docs/stabilization-plan.md) + [`docs/adr/README.md`](docs/adr/README.md) |
| New contributor | [`CONTRIBUTING.md`](CONTRIBUTING.md), then [`docs/architecture/detailed-architecture.md`](docs/architecture/detailed-architecture.md) |
| Integrator (API user) | [`docs/api-reference/`](docs/api-reference/), `api/client.py` |
| Database engineer adding a dialect | [`docs/architecture/database-providers.md`](docs/architecture/database-providers.md), then [`docs/architecture/detailed-architecture.md#adding-new-database-support`](docs/architecture/detailed-architecture.md) |
| SRE / log consumer | [`docs/api-reference/`](docs/api-reference/) + `--log-format json` output samples |

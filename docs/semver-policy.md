# Semantic versioning policy

dblift follows [Semantic Versioning 2.0.0](https://semver.org/) with
the public-surface contract defined below. The single source of truth
for what is public is the `api` package exports plus the symbols
re-exported via each module's `__all__`.

## 1. The public surface

### 1.1 What IS public

Importing from the following locations constitutes a stable contract:

```python
from api import DBLiftClient, EventEmitter, EventType
from config import DbliftConfig, DatabaseConfig, load_config
from core.migration import (
    AppliedMigration,
    Migration,
    MigrationResource,
    MigrationType,
    ResolvedMigration,
    VERSIONED_SCRIPT_TYPES,
    is_migration_type,
    is_versioned,
    migration_type_name,
)
from core.logger import (
    AbstractLog,
    BaselineResult,
    CleanResult,
    ConsoleLog,
    DbliftLogger,
    FileLog,
    HtmlFormatter,
    InfoResult,
    JsonFormatter,
    Log,
    LogFactory,
    LogFormat,
    LogLevel,
    MigrateResult,
    MigrationInfo,
    MultiLog,
    NullLog,
    OperationResult,
    OutputFormatter,
    OutputFormatterFactory,
    RepairResult,
    ValidateResult,
)
```

These names are enumerated in each module's `__all__`, and the `api`
package ships a PEP 561 `py.typed` marker so downstream type checkers
pick up annotations.

### 1.2 What is NOT public

Everything else — any module path with a leading underscore
(`api/_client_factory.py`, `cli/_command_handlers.py`, etc.) AND any
module under `cli/`, `db/`, `core/*` not listed above — is internal.
Import paths are not stable and may change without notice, even in
a patch release.

Concrete examples of internal APIs:

- `cli/main.py::main` — CLI entry point; stable as a CLI, not as a
  Python call.
- `core/migration/executor/migration_executor.py::MigrationExecutor` —
  constructed by `DBLiftClient` internally.
- `db/plugins/**` — providers are swapped via `provider_registry`; the
  class layout is an implementation detail.
- `core/sql_parser/**` — parser internals; the stable surface for SQL
  validation is `DBLiftClient.validate_sql`.

## 2. What triggers each version bump

| Change | Bump | Example |
|---|---|---|
| Add a new public symbol (class, function, enum member, module) | **MINOR** | New `DBLiftClient.rollback_to(version)` method |
| Add an optional keyword argument with a safe default | **MINOR** | `DBLiftClient.migrate(..., stop_on_error=False)` |
| Add a new dialect | **MINOR** | Cosmos DB was added in 1.2.0 |
| Add a new event type to `EventType` | **MINOR** | Subscribers of existing types are unaffected |
| Fix a bug without surface change | **PATCH** | Oracle LONG column double-read fix in 1.1.0 |
| Change the CLI help text of a command | **PATCH** | Cosmetic; machine consumers use `--format json` |
| Rename or remove a public symbol | **MAJOR** | Would require a superseding ADR |
| Remove or rename a keyword argument | **MAJOR** | Same |
| Change the semantic of a public method | **MAJOR** | e.g. `migrate()` no longer acquires a lock by default |
| Raise the minimum Python version | **MAJOR** | 3.8 → 3.11 was v1.4.0 |
| Add a new required field to `DbliftConfig` | **MAJOR** | Existing config files would fail to load |
| Change the schema of `dblift_schema_history` | **MAJOR** | Existing databases need migration |
| Remove a supported dialect | **MAJOR** | |
| Drop a previously-shipped CLI subcommand | **MAJOR** | |

### Notable non-triggers

- **Internal refactors** that don't change the public surface — PATCH.
  (Phase 2 refactors PR-06 through PR-11 all landed as `refactor:` /
  `fix:` commits, not features.)
- **Adding a lint rule, test, or CI gate** — PATCH, unless it changes
  a public behaviour.
- **Documentation-only changes** — PATCH.
- **Deprecation of a public symbol** — MINOR when the symbol is
  deprecated; MAJOR when it is later removed (minimum one minor
  release of overlap).

## 3. Deprecation process

When a public symbol must be removed or renamed, the process is:

1. **Deprecate in a MINOR release.** Add a `DeprecationWarning` at the
   call site and a "Deprecated since vX.Y" note in the docstring and
   the changelog. Do not break behaviour yet.
2. **Keep the symbol working** for at least one full minor release
   (typically two).
3. **Remove in a MAJOR release.** The ADR recording the removal
   explicitly cites the minor release that introduced the deprecation.

Fast-path: symbols that were never part of `__all__` / the documented
surface may be removed without deprecation — they are internal, users
who imported them accepted the risk.

## 4. What about pre-1.0 / 0.x releases?

dblift shipped its first 1.0 in [redacted]. Versions `0.x` that
preceded it were development previews with no stability guarantee.
Any project still pinning `dblift <1.0` should upgrade before relying
on this policy.

## 5. Enforcement

A changelog `Unreleased` section is maintained on every PR. At
release time:

1. The maintainer moves entries from `Unreleased` into a new versioned
   heading.
2. The version bump is validated against this policy — BREAKING
   entries force a MAJOR; new-feature entries force at least a MINOR.
3. `pyproject.toml::version` is bumped in the same commit.
4. Tag is created with `git tag -s vX.Y.Z -m "vX.Y.Z"`.
5. `pip-audit` must pass on the pinned deps before tag.

Automated SemVer checks against the public surface are a future
enhancement; today the policy is enforced by human review at release
time.

## 6. Historical breaking changes

Reference list of MAJOR-triggering changes shipped to date. Future
entries appended here, linked from the matching ADR.

| Version | Change | ADR |
|---|---|---|
| 1.4.0 (planned) | Minimum Python raised to 3.11 | 0004 |
| 1.4.0 (planned) | `cryptography>=46.0.6` and other dep floors | 0004 |

Earlier releases predate this policy and are not retroactively
catalogued here. Earlier release notes remain the authoritative history.

## 7. Links

- [PEP 440 — Python version specifiers](https://peps.python.org/pep-0440/)
- [PEP 561 — Distributing and packaging type information](https://peps.python.org/pep-0561/)
- [Semantic Versioning 2.0.0](https://semver.org/)
- `ARCHITECTURE.md`
- `CHANGELOG.md`
- ADRs

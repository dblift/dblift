# OSS core read efficiency review ledger

Base: develop 8f8e2a3. Branch: fix/oss-core-read-efficiency.

## Preflight review

| Tasks | Shared surface or requirement | Resolution |
|---|---|---|
| 1 / 3 / 4 | StateManager | Implement sequentially; preserve private direct-call contracts and public state semantics. |
| 2 / 4 | Full grouped catalog | ScriptManager retains original grouping; repair consumes it through StateManager. |
| 3 / 5 | MigrationDataService | Version calculation simplified first; remove only helpers still unreferenced afterward. |
| 1 | Index precedence | Exact key, bare key, then first qualified match; no global cache. |
| 2 | Filesystem guards versus metadata reuse | Keep the existing containment/symlink guards and single-load lifetime; no new trust bypass. |
| 3 | Header version versus public current_version | Distinct semantics preserved; no substitution of display current_version. |
| 4 | Repair safety and freshness | None differs from an empty catalog; preserve direct helper error behavior and post-write refresh. |
| 5 | Removal compatibility | Remove undocumented private paths only, keep supported entry points and disclose removals. |
| 6 | Quality and publication | Full CI extras and tidy-imports required; changelog and PR are explicit deliverables. |

Task acceptance and verification are recorded below. Publication to develop is authorized; the PR must not be merged.

## Baseline verification

Develop 8f8e2a3, isolated audit worktree, task-specific environments:
- Python 3.12 with CI constraints and all CI extras: 11,712 unit tests passed, 35 skipped.
- Python 3.11 quality workflow: formatting, imports, flake8, mypy, layering and all ratchets passed; 23 public-surface/smoke tests passed.
- All 31 existing benchmarks passed.
- Real SQLite, 500 applied files: info/no-op migrate/no-op repair each build and sort full analysis three times. Catalog loads are respectively 1/1/3.
- Separate local timing probe, seven warm samples: median info 203.4 ms, no-op migrate 200.6 ms, no-op repair 520.2 ms. These are local observations, not performance guarantees.

## Review refinements

- Task 1: require lazy index construction so versioned-only catalogs do not gain repeatable-history scans.
- Task 2: retain cheap lexical path reconstruction and reuse guarded discovery metadata only when the reconstructed path matches. This preserves existing ambiguous primary/additional reference routing without changing which files load.
- Task 3: preserve valid history and read-error contracts. Do not emulate incidental sort TypeError on malformed multi-row nullable installed ranks: normal stored ranks are non-null integers, and the shared rank helper intentionally treats missing/None ranks as zero.

## Task 1 — accepted

Reviewed complete 7d67440..195c222 diff. Exact/bare/first-qualified checksum precedence and direct-call fallback are preserved. Indexes live only in each aggregation and are lazy, including the correction identified during review. Independent run: all 8 new regressions passed. Counting inputs drop from 250,000 membership visits and 125,250 checksum visits to 500 each; versioned-only paths visit neither input.

## Task 2 — accepted

Reviewed complete 993e64b..0fd266f production and test changes. The containment guard remains in discovery; only the redundant predicates and second normal-path resolution disappear. Per-load records preserve filename metadata precedence, ambiguous reference routing and metadata-free override fallback. Independent run: 16 new regressions passed. Focused discovery/encoding/command suites: 431 passed, 1 existing platform skip; formatting, lint and targeted typing passed. Normal 10/100-file loads now perform one of each filesystem check per file.

## Task 3 — accepted

Reviewed complete 7edc508..8bd7cb9 changes. Header/footer aggregation preserves undo presence, shared rank predicates, baseline contribution, type/success normalization and fresh/snapshot read ownership. Public state calculation is untouched. Independent new-state plus complete command-read-reuse run: 70 passed. Broader state/commands/CLI suite: 1,454 passed, 18 skipped; static checks passed. The real populated command regressions reduce display sorting/analysis from three calls to one while retaining two history reads and one catalog read.

## Task 4 — accepted

Reviewed complete 01a9511..b401442 changes, including explicit missing-catalog fields in the two affected test fixtures. StateManager retains the original grouping; repair consumes it with an explicit None fallback. No execute-path fallback or error handling changed. Copy clones the grouped mapping/lists, and public JSON/repr remain unchanged. Independent focused run: 32 passed. Broader repair/commands/state/v110/provider conformance: 704 passed, 38 subtests passed; static checks passed. Normal no-op/preview catalog loads drop 3 to 1; writes retain a second fresh load. Docker integration setup could not run because no Docker socket was available; real SQLite regressions and unit CI coverage passed.

## Task 5 — accepted

Reviewed complete a0891ea..c245cb8 changes. Only the retired validator path, its unused analyzer/placeholder adapter and unused data-service members are removed. Retained dialect quirks, format checks, public validation entry points, compatibility imports, active analyzer/execution paths and live filters. Review preserved the live failed-reapply regression and excluded an unrelated integration-test assertion change. Independent validation/data-service run: 38 passed. Broader focused suite: 1,140 passed, 19 skipped, 41 subtests passed. Full static quality script passed with Python 3.11.8 and flake8-tidy-imports 4.12.0. This task removes 242 net core source lines; the combined branch removes 165.

## Final combined verification

- Full Python 3.12 unit suite with CI constraints/extras: 11,768 passed, 35 skipped.
- Python 3.11 public-surface and standalone/MCP smoke checks: 23 passed.
- Full quality workflow static checks passed on the final code, including all formatting, lint, typing, layering and ratchets. Unchanged ratchet limits retained.
- Every implementation diff was personally reviewed; all returned findings were corrected and reviewed again. Collection remains with specialized managers and commands consume StateManager data.
- pytest-dblift package suite: 12 passed, 1 skipped. All 31 existing benchmarks passed; existing baseline artifacts were not overwritten.

### Final operation counts and local timings

Identical real SQLite workload with 500 applied migrations, baseline 8f8e2a3 versus final code c245cb8:

| Operation | Full display analyses before/after | Catalog loads before/after | Each file predicate/resolve before/after | History reads before/after | Warm median before/after |
|---|---|---|---|---|---|
| info | 3 / 1 | 1 / 1 | 1,000 / 500 | 2 / 2 | 203.4 / 175.2 ms |
| no-op migrate | 3 / 1 | 1 / 1 | 1,000 / 500 | 2 / 2 | 200.6 / 169.8 ms |
| no-op repair | 3 / 1 | 3 / 1 | 3,000 / 500 | 3 / 3 | 520.2 / 175.4 ms |

Each timing is the median of seven warm local samples, measured separately from instrumentation and other test runs. These are observations on this machine, not general speed guarantees. Operation-count probes also asserted successful results and unchanged history-read counts. The complete branch changes seven core files with 167 inserted and 332 deleted lines: 165 fewer core source lines.

Local unit/quality/package/benchmark verification is complete. Published as [PR #303](https://github.com/dblift/dblift/pull/303) from fix/oss-core-read-efficiency to develop. Remote CI results are recorded in the PR checks. The PR remains open; no merge is authorized.

## Codecov follow-up — 2026-09-14

The coverage comment reported 69/71 changed executable lines covered (97.18%), even though the GitHub check passed its configured threshold. Both misses were the exception handler around the resolved-directory Path comparison. Python 3.11 and 3.12 implement that comparison using normalized path components, without filesystem I/O; the filesystem-error fallback was unreachable. Removed only that handler, retaining the actual resolve/containment error handling and all directory-routing behavior.

Verification after the develop merge: 11,825 unit tests passed, 35 skipped. CI-matching coverage covers 69/69 changed executable lines (100%); the separately installed pytest-dblift plugin was disabled for this unit run to match CI's install order. Formatting, import order, flake8 and targeted typing passed. The combined core reduction is now 168 source lines. No coverage exclusions or threshold changes were added.

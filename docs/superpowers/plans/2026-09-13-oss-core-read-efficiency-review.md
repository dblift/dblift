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

All tasks pending. User explicitly requested personal controller review and publication; no additional publication approval is needed.

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

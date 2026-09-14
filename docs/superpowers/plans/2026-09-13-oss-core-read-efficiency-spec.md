# OSS core read efficiency and surface reduction specification

Implement the five verified follow-ups on develop 8f8e2a3, review every change, and publish a PR to develop.

## Required outcomes

1. StateManager repeatable basename membership and legacy checksum matching use indexes built once per aggregation, not one scan per script. Preserve exact-key, bare-key, then first matching qualified-key precedence.
2. ScriptManager reuses per-discovery filesystem metadata during loading. A regular supported file needs one is_file, one is_symlink and one resolve call in a normal single-directory load. Preserve standalone discovery outputs, directory deduplication, recursion maps, additional directories, path traversal and symlink exclusion, encoding/errors, ordering and filename classification.
3. Header/footer schema-version calculation does not build/sort full display analysis. Preserve effective undo/reapply, baseline and highest-version semantics, nullable/failed/audit history handling and fresh reads at existing boundaries. The public MigrationState.current_version keeps its existing distinct semantics.
4. Repair reuses its initial full catalog for pre-write missing/drift checks through StateManager. Normal no-op repair performs one catalog load, while post-write validation refreshes. Preserve empty-directory safety refusal, failure propagation, grouped-order duplicate resolution, all-history integrity checks and dry-run behavior.
5. Remove retired private migration SQL-syntax validation plumbing and unused MigrationDataService members, including unnecessary analyzer/service construction. Preserve active SQL lint/execution, public validation entry points, format support checks, placeholder configuration and compatibility exports. Repository references and supported API documentation determine the removal boundary; document removed private APIs in the changelog.

## Global constraints

- Python >=3.11; no new runtime dependencies, flags or global caches.
- Specialized managers collect their data. ScriptManager discovers scripts/callbacks and matches events; HistoryManager collects history; StateManager aggregates; commands consume. Validator retains validation rules and engines retain execution.
- Do not bypass StateManager from commands or move dialect rules out of plugins.
- OSS branches use only fix/, release/ or feature/. Use machine-configured Git author/committer, no attribution trailers or attribution in PR text. Publication stays strictly within OSS scope.
- Preserve user-visible payloads, errors, filtering, order and freshness except the explicitly documented removal of unused private APIs.
- Keep edits surgical. Preserve public filters and current-version contracts. Tests cover real outcomes and deterministic operation counts, not only internal call layouts.
- The user authorized implementation, fresh agents, personal review and a PR to develop. Do not merge the PR.

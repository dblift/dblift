# Security policy

## 1. Reporting a vulnerability

**Do not open a public issue or PR for security-relevant findings.**

Private disclosure:

1. Email the maintainers at the address listed in `pyproject.toml`
   (`[project.authors]`).
2. Include:
   - A brief description of the issue and its potential impact.
   - Reproduction steps or a proof-of-concept, if available.
   - Your preferred contact for follow-up.
3. You will receive an acknowledgement within **5 business days**.
4. We aim to publish a patched version within **30 days** for HIGH
   severity findings, **90 days** for MEDIUM/LOW.

Credit is offered in the release notes of the fix (opt-in). We do not
currently operate a bug bounty programme.

## 2. Supported versions

Security fixes are applied to the latest minor release line. Older
lines receive backports only for HIGH-severity issues and only if the
customer depends on them contractually.

| Version line | Status |
|---|---|
| 1.3.x | **Supported** (current) |
| 1.2.x | Security fixes only, HIGH severity |
| ≤ 1.1.x | End of life — upgrade to 1.3.x |

Python runtime: 3.11+ (ADR-0004).
Older Python versions are not supported; supporting an end-of-life
runtime is itself a security finding.

## 3. Threat model

### 3.1 Assets

Listed in order of sensitivity, highest first.

| Asset | Location | Exposure |
|---|---|---|
| Customer database credentials | ``DbliftConfig.database.{username,password}`` loaded from YAML / env / CLI | In-memory for the duration of the process; never persisted by dblift |
| Customer database contents | Remote DB accessed via native Python drivers, Azure SDK, or sqlite3 | dblift reads schema metadata; writes only what user migrations request |
| License private key | `~/.dblift_private_key.pem` (maintainer-side) | Out-of-band; **never ships** in the package. Embedded public key only |
| License JWT tokens | `~/.dblift/license.key`, `DBLIFT_LICENSE_KEY`, `--license-key` | Per-user, RS256-signed; forgery requires the private key |
| Migration scripts | User-supplied SQL on disk | Executed verbatim against the target DB — dblift explicitly trusts them |
| Local dblift history table | `dblift_schema_history` in target DB | Stored in the DB the user already controls |

### 3.2 Adversaries

| Adversary | Capability | Relevant mitigations |
|---|---|---|
| External network attacker | Can reach the target DB host but not the dblift runner | Driver TLS is user-configured; dblift does not add new listeners or ports |
| Malicious migration author | Writes hostile SQL into a migration file | **Out of scope.** dblift trusts migration content by design (it is a migration runner, not a safety sandbox). Review process is the user's responsibility. |
| Malicious Python dependency | Pushes compromised version to PyPI | `pip-audit` in CI, pinned version floors, `setuptools` CVEs tracked |
| Compromised CI runner | Could exfiltrate config or credentials used for integration tests | DB credentials stored as GitHub secrets; gitleaks gates PRs |
| Insider committing a secret to history | Accidentally commits `.env`, private key, or test credentials | `gitleaks` on every PR (`.gitleaks.toml`) + `.gitignore` blanket-excludes `*.log`, `*.pem`, `.env`, `custom_logs/` |

### 3.3 Attack surface inventory

| Surface | Risk | Mitigation |
|---|---|---|
| `cli` argparse | Malformed argv → crash / info leak | Structural + behavioural invariants pinned by `test_parser_invariants.py` (210 cases) |
| `--format json` stdout | Log contamination → downstream parser crash on user data | `CommandOutput` abstraction + matrix `test_json_output_contract.py` |
| SQL generation (`core/sql_generator/`) | SQL injection in generated DDL | Identifiers quoted via `DialectEnum.quote_identifier` (one policy per dialect); schema / table names restricted to ASCII regex; bandit flags 96 MEDIUM-severity `B608` for intentional SQL-as-string patterns (each reviewed) |
| Placeholder substitution (`${var}`) | Injection via placeholder values | Substitution runs **before** tokenisation so values cannot smuggle DDL across statement boundaries. Values are still interpreted as literal text; users who place `${var}` inside identifier positions accept the substitution semantics |
| Native database drivers | Malicious data in DB metadata responses | Metadata is normalized before diffing; driver exceptions are surfaced through dblift error handling |
| History table writes | History table corruption | `acquire_migration_lock()` / `release_migration_lock()` per dialect, plus transactions where the dialect supports them (ADR-0007) |
| License JWT validation | Forged license | RS256 with embedded public key; any token whose signature does not verify is rejected before any DB operation |

## 4. Secrets handling

| Policy | Enforcement |
|---|---|
| Never commit secrets to git | `.gitleaks.toml` + CI gate on every PR |
| Never log secrets | URL masking in `core/utils/url_masking.py`; `--log-format json` sanitises `DBLIFT_DB_PASSWORD` and tokens |
| Never echo secrets to stdout | `CommandOutput` machine-format contract: stdout carries only the requested payload; banner / license info / status all go to stderr (ADR-0008) |
| Credential sources (merge order) | YAML config < env vars < CLI flags |
| Credential lifetime | In-memory for the process lifetime; no persistence beyond `~/.dblift/license.key` (license only) |

Historical secret incidents are logged in
the security policy, coordinated through GitHub Security Advisories.
Open items follow internal remediation workflows; specifics of
unresolved incidents are not summarised here.

## 5. Supply chain

| Layer | Control |
|---|---|
| Python runtime deps | Pinned floors in `pyproject.toml`; `pip-audit` on every PR |
| Build system | `setuptools>=78.1.1`, `wheel>=0.46.2` floored post CVE triage |
| Docker image | Built from `Dockerfile`; pinned base image; no privilege escalation needed at runtime |
| Source distribution | Signed git tags; squash-merge only ([CONTRIBUTING.md](CONTRIBUTING.md)) |

## 6. Known limitations

### 6.1 Migration content is trusted by design

dblift is a migration *runner*, not a sandbox. Any SQL the user
authors in a migration file executes with the connection's full
privileges. Reviewing migration scripts before applying them to
production is the user's responsibility, not dblift's.

### 6.2 Cosmos DB Emulator master key in test fixtures

Test fixtures under `tests/` contain the **public** Azure Cosmos DB
Emulator master key (a fixed constant Microsoft publishes for local
testing: `C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw==`).
This is not a secret; it grants access only to a local emulator
instance. Documented allowlist in `.gitleaks.toml`.

## 7. Defensive architecture summary

The stabilisation program encodes security-relevant invariants as
tests rather than prose, so regressions fail CI rather than ship:

| Invariant | Encoded by |
|---|---|
| No secret leaks into git | `gitleaks` on every PR |
| No known-CVE runtime dependency | `pip-audit` on every PR |
| No HIGH-severity static finding | `bandit` on every PR |
| No secret printed on stdout (machine mode) | matrix `test_json_output_contract.py` |
| No placeholder injection across statement boundaries | `execution_engine` places substitution pre-tokeniser; cache isolated (ADR-0010) |
| Dialect capabilities match provider runtime | `test_dialect_capabilities.py` (prevents a provider silently dropping a transaction guarantee) |

See [Architecture overview](docs/architecture/overview.md) for more details.

## 8. Audit trail

| Artefact | Location |
|---|---|
| Architecture decisions | `docs/architecture/` |
| Security policy | `SECURITY.md` (this file) |

| CI quality gates | `.github/workflows/{code-quality,security,complexity,matrix-tests}.yml` |
| Source licence | [`LICENSE`](LICENSE) — MIT |

## 9. Contact

For security issues, use the email address in `pyproject.toml`
`[project.authors]`. Please use PGP if available; our public key is
published on the project's website (see `README.md`).

For non-security issues: [GitHub issues](https://github.com/cmodiano/dblift/issues).

# CLI matrix tests

These tests are a direct translation of the **dblift-dev-test** skill matrix
into executable pytest.

## Why this directory exists

For most of 2026 the release cycle looked like: ship → run dev-test skill → find
5-10 bugs → fix → ship → run dev-test → find 5-10 new bugs. Every pass uncovered
fresh issues because nothing persisted between passes — the skill is a manual
checklist, not a regression suite.

This directory is the regression suite. Every cell in the dev-test matrix
becomes a test here. Once a bug is found, the scenario that found it becomes a
permanent test; the same bug cannot ship twice.

## Doctrine

1. **Tests are written from the spec**, not from the code. The spec is the
   skill matrix and the CLI `--help` output. If the code changes shape but the
   observable behavior stays the same, the test should keep passing. If the
   observable behavior changes, the test should fail — even when the
   implementation "looks right" to the person writing it.

2. **No mocks of the CLI or config layer.** Tests run `python -m cli.main` as
   a subprocess (via `DBLiftCLI` helper) or call `DBLiftClient` with a real
   config. The whole point is to exercise argparse → config merge → command
   dispatch → provider, which is where the bugs live.

3. **No DB for contract tests; real DB for behaviour tests.** Tests that
   assert CLI surface properties (argparse, error messages, JSON output shape,
   exit codes for bad inputs) do not need a container. Tests that assert
   database-observable outcomes parametrize over the `db_container` fixture.

4. **SQLite is the default dialect for new tests** unless the bug is
   dialect-specific. SQLite runs everywhere, needs no container, and catches
   most CLI/config/command-dispatch bugs.

5. **One test = one scenario = one bug class.** Don't bundle. A test that
   asserts 12 things fails opaquely; a focused test names the bug it is
   guarding against in its docstring.

## File layout

- `test_cli_contract.py` — CLI surface properties that need no DB (bad args,
  error messages, JSON output shape, exit codes, `--help` discoverability).
  Maps to dev-test §5.2 items that are not DB-dependent.
- `test_parent_flag_behaviour.py` — behavioural pair to the unit property test
  in `tests/unit/cli/test_parser_invariants.py`. Verifies that parent-level
  flags (`--config`, `--db-url`, `--scripts`, `--dry-run`, etc.) actually reach
  the command handler across every subcommand. Maps to dev-test §5.2.1.
- `test_<command>_matrix.py` — one file per top-level command, parametrized
  over `db_container` with the scenarios enumerated in dev-test §5.1.

## How to add a test

1. Find the dev-test skill section that specifies the behaviour.
2. Write a pytest that asserts that behaviour using `DBLiftCLI` or
   `DBLiftClient`.
3. If it was triggered by a bug report, the test docstring must reference the
   bug ID and the dev-test section number.

## Running

```bash
# All matrix tests (needs Docker for DB-dependent ones):
pytest tests/integration/matrix/

# Contract tests only (no Docker):
pytest tests/integration/matrix/test_cli_contract.py tests/integration/matrix/test_parent_flag_behaviour.py

# One dialect only:
DBLIFT_CORE_TEST_DB=sqlite pytest tests/integration/matrix/
```

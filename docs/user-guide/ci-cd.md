# Running dblift in CI/CD

dblift is a pip package with no system dependencies, so CI is just
`pip install` + a dblift command. These recipes use OSS commands only
(`validate`, `info`).

All commands need a reachable database. Below, the DB connection is supplied
via the `DBLIFT_DB_URL` environment variable (overrides `dblift.yaml`).

## GitHub Actions

```yaml
name: dblift
on:
  pull_request:
    paths: ["migrations/**"]

jobs:
  validate:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: dblift
          POSTGRES_PASSWORD: dblift
          POSTGRES_DB: dblift
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DBLIFT_DB_URL: postgresql+psycopg://dblift:dblift@localhost:5432/dblift
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install "dblift[postgresql]"
      - run: dblift migrate   # apply to the ephemeral CI database
      - run: dblift validate  # checksums / order / applied-state integrity
      - run: dblift info      # report pending migrations
```

## GitLab CI

```yaml
stages: [validate]

validate-migrations:
  stage: validate
  image: python:3.11
  services:
    - name: postgres:16
      alias: postgres
  variables:
    POSTGRES_USER: dblift
    POSTGRES_PASSWORD: dblift
    POSTGRES_DB: dblift
    DBLIFT_DB_URL: "postgresql+psycopg://dblift:dblift@postgres:5432/dblift"
  rules:
    - changes: [migrations/**/*]
  script:
    - pip install "dblift[postgresql]"
    - dblift migrate
    - dblift validate
    - dblift info
```

## Pre-commit (local)

```yaml
repos:
  - repo: https://github.com/cmodiano/dblift-oss
    rev: v1.8.0   # pin to a released tag
    hooks:
      - id: dblift-validate
      - id: dblift-info
```

The hooks need a configured `dblift.yaml` (or `DBLIFT_DB_URL`) and a reachable
database — typically the local dev DB from your `docker-compose.yml`. dblift has
no offline (database-free) lint in OSS.

**Important:** Because the hooks use `language: python`, pre-commit creates an
isolated environment containing only the base `dblift` package (no database
driver extras). For PostgreSQL (or other DBs) you must explicitly request the
driver in the *consuming* repository's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/cmodiano/dblift-oss
    rev: v1.8.0
    hooks:
      - id: dblift-validate
        additional_dependencies: ["dblift[postgresql]"]
      - id: dblift-info
        additional_dependencies: ["dblift[postgresql]"]
```

Use the appropriate extra(s) for the database(s) you connect to. The same
applies when using `pre-commit try-repo` locally or in CI.

## Optional: Guard the pre-commit hook contract in your own CI

If you publish migrations and consume the `dblift-validate` / `dblift-info`
pre-commit hooks from `https://github.com/cmodiano/dblift-oss`, you may want
a CI job in *your own repository* that proves the hooks still work end-to-end
(positive on a clean DB history, negative on checksum drift).

Here is a complete example you can copy into your own `.github/workflows/`
(adjust the `DBLIFT_DB_URL` and image as needed). It uses `pre-commit try-repo`
pointed at the official hook repository (not your workspace) and passes the
required DB driver via `--additional-deps`:

```yaml
name: Pre-commit hooks (dblift example)
on:
  pull_request:
    paths: ["migrations/**"]
  push:
    branches: [main]

jobs:
  hook-contract:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: dblift
          POSTGRES_PASSWORD: dblift
          POSTGRES_DB: dblift
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DBLIFT_DB_URL: postgresql+psycopg://dblift:dblift@localhost:5432/dblift
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install pre-commit

      - name: Build fixture project
        run: |
          set -euo pipefail
          rm -rf /tmp/fixture && mkdir -p /tmp/fixture/migrations
          git -C /tmp/fixture init -q
          printf 'CREATE TABLE widgets (id INT PRIMARY KEY);\n' \
            > /tmp/fixture/migrations/V1_0_0__init.sql
          git -C /tmp/fixture add -A

      - name: Apply migrations (populate history)
        working-directory: /tmp/fixture
        run: dblift migrate

      - name: Positive — hooks pass on a current DB
        working-directory: /tmp/fixture
        run: |
          set -euo pipefail
          pre-commit try-repo https://github.com/cmodiano/dblift-oss dblift-validate \
            --rev v1.8.0 \
            --additional-deps "dblift[postgresql]" \
            --files migrations/V1_0_0__init.sql
          pre-commit try-repo https://github.com/cmodiano/dblift-oss dblift-info \
            --rev v1.8.0 \
            --additional-deps "dblift[postgresql]" \
            --files migrations/V1_0_0__init.sql

      - name: Negative — validate fails on checksum drift
        working-directory: /tmp/fixture
        run: |
          set -euo pipefail
          printf '\n-- drift\nALTER TABLE widgets ADD COLUMN name TEXT;\n' \
            >> migrations/V1_0_0__init.sql
          if pre-commit try-repo https://github.com/cmodiano/dblift-oss dblift-validate \
               --rev v1.8.0 \
               --additional-deps "dblift[postgresql]" \
               --files migrations/V1_0_0__init.sql; then
            echo "ERROR: dblift-validate should have failed on checksum drift" >&2
            exit 1
          fi
          echo "OK: checksum drift correctly rejected"
```

**Notes for consumers:**
- Point `try-repo` at the `dblift-oss` repository (with `--rev`) so you are testing the published hooks, not a local copy.
- Use `--additional-deps "dblift[postgresql]"` (or the relevant extra) because `language: python` hooks only get the base package by default.
- This is provided purely as a copy-paste example. The dblift repositories themselves do not run or ship this as an active workflow.

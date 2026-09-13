# Benchmark suite

These opt-in `pytest-benchmark` tests cover CPU hot paths and real SQLite
commands. They are intended for local investigation; timing is not a CI gate.

## What's covered

| File | Coverage |
|---|---|
| `test_bench_cpu_hot_paths.py` | Checksums, filename parsing, placeholder substitution, migration-type helpers, dialect capabilities, and PostgreSQL statement splitting. |
| `test_bench_sqlite_commands.py` | Fresh SQLite migration of 10 and 100 scripts with and without callbacks, plus no-op migrate, validate, and info against 100 applied migrations. |

## Running locally

```shell
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
    -p pytest_benchmark.plugin \
    tests/benchmarks/ --benchmark-only
```

Write a result file for later inspection:

```shell
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
    -p pytest_benchmark.plugin \
    tests/benchmarks/ --benchmark-only \
    --benchmark-json=benchmarks.json
```

The benchmark conftest skips this directory unless `--benchmark-only` is set,
so the suite does not add timing work to a normal test run.

## Historical baseline

`baseline.json` contains historical measurements for
`test_bench_cpu_hot_paths.py`. Compare those test identifiers without turning
the comparison into a pass/fail threshold:

```shell
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
    -p pytest_benchmark.plugin \
    tests/benchmarks/test_bench_cpu_hot_paths.py --benchmark-only \
    --benchmark-compare=tests/benchmarks/baseline.json
```

The file records only CPython 3.11.15 on Linux; it does not identify the CPU or
kernel. Keep results from other environments in a separate JSON file instead of
overwriting this historical baseline.

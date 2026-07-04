# dblift OSS Scripts

This directory intentionally contains only the scripts used by the public
repository workflow.

## Local Quality Gate

```bash
./scripts/check_code_quality.sh
```

This runs the same formatting, import ordering, flake8, mypy, AST-pattern,
docstring, and line-length checks used by CI.

## Release Build Helper

`build_distributions.py` is used by `.github/workflows/build.yaml` to create
release archives and standalone executables.

## Cutting a Release

```bash
python scripts/create_release.py --dry-run X.Y.Z
python scripts/create_release.py --push X.Y.Z
```

Rolls `## [Unreleased]` in `CHANGELOG.md` into a dated `## [X.Y.Z]` section,
bumps the version in `pyproject.toml`/`__init__.py`, commits, and tags
`vX.Y.Z`. See `docs/release/oss-enterprise-release.md` in the enterprise
repository for the full release runbook.

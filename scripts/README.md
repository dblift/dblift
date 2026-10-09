# dblift OSS Scripts

This directory intentionally contains only the scripts used by the public
repository workflow.

## Local Quality Gate

```bash
./scripts/check_code_quality.sh
```

This runs the same formatting, import ordering, flake8, mypy, AST-pattern,
docstring, and line-length checks used by CI, and the structural-debt ratchet.

## Cutting a Release

```bash
python scripts/create_release.py --dry-run X.Y.Z
python scripts/create_release.py --push X.Y.Z
```

Rolls `## [Unreleased]` in `CHANGELOG.md` into a dated `## [X.Y.Z]` section,
bumps the version in `pyproject.toml`/`__init__.py`, commits, and tags
`vX.Y.Z`.

## Checking the Upgrade Path

```bash
scripts/check_upgrade_path.sh '<pip requirement for the old version>'
```

`check_upgrade_path.sh` — migrates a SQLite database with a published
release, continues with this tree, and checks the published release still
reads the history; run by `.github/workflows/upgrade-path.yml`.

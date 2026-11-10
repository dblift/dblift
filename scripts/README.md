# dblift OSS Scripts

This directory intentionally contains only the scripts used by the public
repository workflow.

## Local Quality Gate

```bash
./scripts/check_code_quality.sh
```

This runs the same formatting, import ordering, flake8 (line length and import
position included), mypy, AST-pattern and public-docstring checks used by CI,
plus the structural-debt ratchet. All but the last scan every file under
`dblift/` at zero tolerance. Run it from the repository root: a script whose
default root is missing exits non-zero instead of passing on an empty scan.

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

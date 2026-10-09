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
bumps the version in both distribution projects, their exact dependency pins,
and `dblift/__init__.py`, commits, and tags
`vX.Y.Z`.

The release workflow currently builds and retains the core, bundle, and
`pytest-dblift` artifacts for qualification. Publishing remains a separate
release decision because the previous `dblift` wheel owned files now owned by
`dblift-core`. For a local unpublished candidate pair, run
`python scripts/build_core_candidate.py --revision "$(git rev-parse HEAD)" --output /tmp/dblift-candidate`.
Its manifest records the three version-site transforms and artifact hashes.

## Checking the Upgrade Path

```bash
scripts/check_upgrade_path.sh '<pip requirement for the old version>'
```

`check_upgrade_path.sh` — migrates a SQLite database with a published
release, continues with this tree, and checks the published release still
reads the history; run by `.github/workflows/upgrade-path.yml`.

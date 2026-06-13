# DBLift OSS Export

Open-source tree generated from the enterprise monorepo.

## Boundaries

See `docs/architecture/oss-enterprise-boundaries.md` in the enterprise
repository (internal docs are not exported to this tree).

## Regenerate (initial)

```bash
python3 scripts/export_oss_repo.py /path/to/empty/dblift-oss
```

## Sync (existing checkout)

```bash
python3 scripts/export_oss_repo.py /path/to/dblift-oss --update --no-git-init
cd /path/to/dblift-oss
python3 -m pytest tests/unit/ -n auto --dist=loadscope -q --no-header
git status
```

See `docs/architecture/oss-export-reconciliation.md` before the first incremental sync.

## Tests

```bash
python3 -m pytest tests/unit/ -n auto --dist=loadscope -q --no-header
```

# dblift Scripts

Utility scripts for development, testing, and code quality.

## Setup

| Script | Purpose |
|---|---|
| `setup.sh` | Set up the development environment (Linux/macOS) |
| `setup.bat` | Set up the development environment (Windows) |
| `install_dblift_dev.sh` | Install dblift in editable mode with dev extras |
| `setup_documentation.sh` | Install MkDocs and documentation dependencies |

## Code Quality

| Script | Purpose |
|---|---|
| `check_code_quality.sh` | Run the full quality gate: black, isort, flake8, mypy |
| `run_mypy.sh` | Run mypy on core source packages |
| `run_code_quality_hook.sh` | Pre-commit hook wrapper (resolves project venv automatically) |
| `check_api_docstrings.py` | Enforce docstring coverage on all public `api/` symbols |
| `check_line_length.py` | Ratchet-based E501 line-length gate (per-root caps) |
| `lint_patterns.py` | AST-based lint rules for recurring bug patterns |
| `mypy_packages.txt` | Package list passed to mypy |

## Testing

| Script | Purpose |
|---|---|
| `run_integration_local.sh` | Reproduce CI integration runs locally against Docker containers |

## Docker

| Script | Purpose |
|---|---|
| `build_docker.sh` | Build and smoke-test the Docker image locally |
| `docker/run_validation.py` | Validation entrypoint used inside the CI validation image |

## Typical workflow

```bash
# First-time setup
./scripts/setup.sh
source venv/bin/activate

# Before every commit
./scripts/check_code_quality.sh

# Run unit tests in parallel
python -m pytest tests/unit/ -n auto --dist=loadscope -q --no-header

# Run integration tests locally (requires Docker)
./scripts/run_integration_local.sh postgresql
./scripts/run_integration_local.sh mysql
```

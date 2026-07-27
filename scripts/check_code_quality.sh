#!/bin/bash
# Script to run all code quality checks locally

echo "Running code quality checks..."

# We'll collect the exit code from each step to report at the end
exit_code=0

# Determine Python interpreter (prefer python, fallback to python3)
PYTHON_BIN="$(command -v python)"
if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3)"
fi

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Python interpreter not found. Please install Python 3."
    exit 1
fi

echo -e "\n===== Checking formatting with black ====="
# Use line length specified in pyproject.toml (100) - check only, don't fix
# Check all Python source directories
black --check --diff api/ cli/ config/ core/ db/ tests/ scripts/ || { echo "❌ Formatting issues found. Run 'black .' to fix them."; exit_code=1; }

echo -e "\n===== Checking imports with isort ====="
# Check import order without fixing automatically (like GitHub workflow)
# Check all Python source directories
isort --check --diff api/ cli/ config/ core/ db/ tests/ scripts/ || { echo "❌ Import order issues found. Run 'isort .' to fix them."; exit_code=1; }

echo -e "\n===== Checking style with flake8 ====="
# Use the .flake8 file from the project root.
# tests/ and scripts/ are deliberately NOT passed here: .flake8 excludes them
# (728 legacy violations, see the note in that file), so listing them would
# claim coverage the run does not have. black and isort below still cover
# them. To re-enable, drop the exclude in .flake8 and add them back here.
FLAKE8_CONFIG=".flake8"
if [ ! -f "$FLAKE8_CONFIG" ]; then
    # Fallback to setup.cfg or default
    FLAKE8_CONFIG="setup.cfg"
fi
if [ -f "$FLAKE8_CONFIG" ]; then
    flake8 --config="$FLAKE8_CONFIG" api/ cli/ config/ core/ db/
else
    flake8 api/ cli/ config/ core/ db/
fi
if [ $? -ne 0 ]; then
    exit_code=1
fi

echo -e "\n===== Type checking with mypy ====="
# Check for missing type stubs
required_stubs=()
if ! "$PYTHON_BIN" -m pip show types-PyYAML >/dev/null 2>&1; then
    required_stubs+=("types-PyYAML")
fi

if [ ${#required_stubs[@]} -gt 0 ]; then
    echo "Missing type stubs detected. You may want to install:"
    for stub in "${required_stubs[@]}"; do
        echo "  - $stub"
    done
    echo "Install with: pip install ${required_stubs[*]}"
fi

# Run mypy with error reporting
# Check all Python source directories
mypy_exit_code=0
if [ -d "api" ] || [ -d "cli" ] || [ -d "config" ] || [ -d "core" ] || [ -d "db" ]; then
    echo "Type checking source directories..."
    "$PYTHON_BIN" -m mypy api/ cli/ config/ core/ db/ --config-file pyproject.toml --show-error-codes || mypy_exit_code=$?
else
    echo "⚠️  Source directories not found, skipping mypy..."
fi

# Exit with failure if mypy found errors
if [ $mypy_exit_code -ne 0 ]; then
    echo -e "\n❌ Type checking failed. Please fix the issues above."
    exit_code=1
else
    echo -e "✅ Type checking passed."
fi

echo -e "\n===== import-linter (internal layering) ====="
# Local-only gate — .github/workflows/code-quality.yml does NOT run this.
# Enforces the intra-tree layering contracts in .importlinter: cli must
# reach the database layer through api/ rather than importing db directly,
# and no library layer (api/config/core/db) may import cli. This replaced
# the tier-boundary contracts (OSS/pro/enterprise), which named packages
# that do not exist in this repository. Static analysis only — nothing is
# imported at runtime.
lint-imports --config .importlinter || { echo "❌ Import-linter: layering contract broken."; exit_code=1; }

echo -e "\n===== AST lint patterns (ratchet) ====="
# Mirrors .github/workflows/code-quality.yml step. Fails only on NEW
# entries vs .lint-patterns-baseline.txt — pre-existing legacy hits
# are baseline-listed; new ones must either gain a `# lint: allow-*`
# annotation or be added to the baseline with a justifying PR.
"$PYTHON_BIN" scripts/lint_patterns.py || { echo "❌ AST lint patterns: new violation(s) detected."; exit_code=1; }

echo -e "\n===== Public-API docstring linter (ratchet) ====="
# Local-only gate — CI does not run this. api/, cli/ and core/ are
# all pinned at zero in .docstring-ratchet.json; db/ is capped at its
# measured count. New missing-docstring sites push a count above its
# cap and fail.
"$PYTHON_BIN" scripts/check_api_docstrings.py \
    --paths api cli core db \
    --ratchet .docstring-ratchet.json \
    || { echo "❌ Public-API docstrings: ratchet exceeded."; exit_code=1; }

echo -e "\n===== Line-length ratchet (flake8 E501) ====="
# E501 is globally ignored in .flake8 (legacy debt). This per-root
# count-based ratchet from .flake8-e501-ratchet.json runs the check
# in isolation and fails only on NET growth. When a refactor lowers a
# count, the script prints the new cap to commit in the same PR.
"$PYTHON_BIN" scripts/check_line_length.py || { echo "❌ Line-length ratchet exceeded."; exit_code=1; }


if [ $exit_code -eq 0 ]; then
    echo -e "\n✅ All code quality checks passed!"
else
    echo -e "\n❌ Some code quality checks failed. Please fix the issues above."
fi

exit $exit_code

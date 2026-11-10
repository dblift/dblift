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
black --check --diff dblift/ tests/ scripts/ packages/ || { echo "❌ Formatting issues found. Run 'black .' to fix them."; exit_code=1; }

echo -e "\n===== Checking imports with isort ====="
# Check import order without fixing automatically (like GitHub workflow)
# Check all Python source directories
isort --check --diff dblift/ tests/ scripts/ packages/ || { echo "❌ Import order issues found. Run 'isort .' to fix them."; exit_code=1; }

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
    flake8 --config="$FLAKE8_CONFIG" dblift/
else
    flake8 dblift/
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
if [ -d "dblift" ]; then
    echo "Type checking source directories..."
    "$PYTHON_BIN" -m mypy dblift/ tests/typing/lightweight_extension.py \
        --config-file pyproject.toml --show-error-codes || mypy_exit_code=$?
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
# Also enforced by .github/workflows/code-quality.yml.
# Enforces the intra-tree layering contracts in .importlinter: cli must
# reach the database layer through api/ rather than importing db directly,
# and no library layer (api/config/core/db) may import cli. This replaced
# the tier-boundary contracts (OSS/pro/enterprise), which named packages
# that do not exist in this repository. Static analysis only — nothing is
# imported at runtime.
lint-imports --config .importlinter || { echo "❌ Import-linter: layering contract broken."; exit_code=1; }

echo -e "\n===== AST lint patterns (zero tolerance, all of dblift/) ====="
# Also enforced by .github/workflows/code-quality.yml. Any unannotated
# violation fails; a deliberate use needs an inline `# lint: allow-*` comment.
"$PYTHON_BIN" scripts/lint_patterns.py || { echo "❌ AST lint patterns: violation(s) detected."; exit_code=1; }

echo -e "\n===== Public-API docstrings (zero tolerance, all of dblift/) ====="
# Also enforced by .github/workflows/code-quality.yml. Every public module,
# class, function and method in dblift/ needs a docstring; there are no caps.
"$PYTHON_BIN" scripts/check_api_docstrings.py \
    || { echo "❌ Public-API docstrings: missing docstring(s)."; exit_code=1; }

echo -e "\n===== Structural-debt ratchet ====="
"$PYTHON_BIN" scripts/check_debt_ratchet.py || { echo "❌ Structural-debt ratchet exceeded."; exit_code=1; }


if [ $exit_code -eq 0 ]; then
    echo -e "\n✅ All code quality checks passed!"
else
    echo -e "\n❌ Some code quality checks failed. Please fix the issues above."
fi

exit $exit_code

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
# Use the .flake8 file from the project root
FLAKE8_CONFIG=".flake8"
if [ ! -f "$FLAKE8_CONFIG" ]; then
    # Fallback to setup.cfg or default
    FLAKE8_CONFIG="setup.cfg"
fi
if [ -f "$FLAKE8_CONFIG" ]; then
    flake8 --config="$FLAKE8_CONFIG" api/ cli/ config/ core/ db/ tests/ scripts/
else
    flake8 api/ cli/ config/ core/ db/ tests/ scripts/
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

echo -e "\n===== AST lint patterns (ratchet) ====="
# Mirrors .github/workflows/code-quality.yml step. Fails only on NEW
# entries vs .lint-patterns-baseline.txt — pre-existing legacy hits
# are baseline-listed; new ones must either gain a `# lint: allow-*`
# annotation or be added to the baseline with a justifying PR.
"$PYTHON_BIN" scripts/lint_patterns.py || { echo "❌ AST lint patterns: new violation(s) detected."; exit_code=1; }

echo -e "\n===== Public-API docstring linter (ratchet) ====="
# Same gate as CI: api/ + cli/ stay at zero; core/ and db/ are
# capped by .docstring-ratchet.json. New missing-docstring sites
# push the count above the cap and fail.
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

# Optional unused code check
if [ "$1" = "--check-unused" ] || [ "$1" = "-u" ]; then
    echo -e "\n===== Checking for unused code ====="
    echo "Running unused code analysis..."
    if "$PYTHON_BIN" dblift_package/scripts/find_unused_code.py --output reports/unused_code_report.txt; then
        echo "✅ Unused code analysis completed. Report saved to reports/unused_code_report.txt"
        echo "Review the report and remove confirmed unused code."
    else
        echo "❌ Unused code analysis failed."
        exit_code=1
    fi
fi

if [ $exit_code -eq 0 ]; then
    echo -e "\n✅ All code quality checks passed!"
else
    echo -e "\n❌ Some code quality checks failed. Please fix the issues above."
fi

# Usage information
echo -e "\n💡 TIP: Run './scripts/check_code_quality.sh --check-unused' to include unused code analysis"

exit $exit_code
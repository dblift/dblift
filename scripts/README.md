# dblift Scripts

This directory contains utility scripts for the dblift project.

## Code Quality Tools

The `check_code_quality.sh` script runs various code quality tools to ensure consistent style and detect potential issues in the codebase.

### How to use

```bash
./scripts/check_code_quality.sh
```

### Tools included

The script runs the following tools in sequence:

1. **Black**: Code formatter that automatically formats Python code to a consistent style
   - Configuration in `pyproject.toml`
   - Line length: 100 characters

2. **isort**: Import formatter that sorts and groups imports
   - Configuration in `pyproject.toml`

3. **Flake8**: Style and quality checker
   - Configuration in `.flake8`
   - Ignores specific error codes that conflict with Black or are not relevant to this project

4. **mypy**: Static type checker
   - Configuration in `pyproject.toml`
   - Currently in report-only mode (doesn't fail the build)
   - Helps identify type-related issues for gradual typing adoption

### Special considerations

- The script is designed to fix what it can (Black and isort) and report what needs manual fixing (Flake8 and mypy)
- Type annotations can be added gradually without breaking the build

### Adding type annotations

To fix type annotation issues:

1. Review mypy error messages
2. Add type annotations to function parameters and return values
3. Add variable annotations where required
4. Install missing type stubs with `mypy --install-types`

The script is configured to allow gradual typing adoption while still providing useful feedback about what needs to be fixed.

# Build and Development Scripts

This directory contains various scripts for building, testing, and maintaining the dblift project.

## Scripts Overview

### Code Quality
- `check_code_quality.sh` - Runs all code quality checks (black, isort, flake8, mypy)
  - Add `--check-unused` or `-u` flag to include unused code analysis
- `find_unused_code.py` - Comprehensive unused code analysis tool

### Build Scripts
- `build_distributions.py` - Builds Python distributions
- `create_release.py` - Automated release creation

### Development Tools
- `update_changelog.py` - Updates CHANGELOG.md with new entries
- `mypy_packages.txt` - List of packages for mypy type checking

## Unused Code Analysis

### Quick Analysis
```bash
# Run vulture directly (requires: pip install vulture)
vulture . --exclude venv,htmlcov,.mypy_cache,__pycache__,.git --min-confidence 80

# Run comprehensive analysis
python scripts/find_unused_code.py

# Include in code quality checks
scripts/check_code_quality.sh --check-unused
```

### Detailed Analysis
```bash
# Save report to file
python scripts/find_unused_code.py --output unused_report.txt

# JSON format for tool integration
python scripts/find_unused_code.py --format json --output unused_report.json
```

### Other Tools for Finding Unused Code

1. **IDE Features**
   - **PyCharm**: Code → Inspect Code → Unused symbols
   - **VS Code**: With Python extension, look for grayed-out functions
   - **Cursor**: Right-click → Find All References

2. **Static Analysis Tools**
   ```bash
   # Install and run unimport
   pip install unimport
   unimport --check --diff

   # Install and run dead (more aggressive)
   pip install dead
   dead

   # Use pylint for unused imports
   pylint --disable=all --enable=unused-import .
   ```

3. **Coverage-Based Analysis**
   ```bash
   # Run tests with coverage to find untested code
   pytest --cov=. --cov-report=html
   # Check htmlcov/index.html for uncovered functions
   ```

4. **Manual Review Techniques**
   - Search for functions that are only defined but never called
   - Use grep to find function definitions vs. usages:
     ```bash
     grep -r "def function_name" .
     grep -r "function_name(" . --exclude-dir=".git"
     ```

### What to Do with Unused Code

1. **Immediate Actions** (Low Risk)
   - Remove unused imports
   - Remove unused variables in function parameters
   - Remove clearly unused utility functions

2. **Review Required** (Medium Risk)
   - Public API functions (might be used by external code)
   - CLI command functions (might be entry points)
   - Test fixtures and utilities

3. **Consider Carefully** (High Risk)
   - Functions used via reflection or dynamic calls
   - Plugin interfaces
   - Functions called from configuration files

### Integration with CI/CD

Add unused code checks to your workflow:
```bash
# In your CI script
python scripts/find_unused_code.py --format json > unused_code.json
# Parse JSON and fail if critical unused code is found
```

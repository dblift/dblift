#!/usr/bin/env python3
"""
Script to run tests locally with coverage and generate combined coverage reports.

This script allows you to:
1. Run unit tests with coverage
2. Run integration tests with coverage (selectively by database)
3. Combine all coverage reports
4. Generate HTML and XML reports
5. Optionally upload to Codecov

Usage:
    # Run unit tests only
    python scripts/run_tests_with_coverage.py --unit-only

    # Run unit + integration tests for specific database
    python scripts/run_tests_with_coverage.py --unit --integration --database postgresql

    # Run all tests (unit + all integration databases)
    python scripts/run_tests_with_coverage.py --all

    # Generate coverage report without running tests
    python scripts/run_tests_with_coverage.py --combine-only

    # Upload to Codecov after generating report
    python scripts/run_tests_with_coverage.py --all --upload-codecov
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# Coverage file names
COVERAGE_UNIT = "coverage-unit.xml"
COVERAGE_INTEGRATION = "coverage-integration.xml"
COVERAGE_COMBINED = "coverage.xml"
HTML_REPORT_DIR = "htmlcov"


def run_command(cmd: List[str], description: str) -> bool:
    """Run a command and return True if successful."""
    print(f"\n{'='*60}")
    print(f"📋 {description}")
    print(f"{'='*60}")
    print(f"Running: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"\n❌ {description} failed with exit code {result.returncode}")
        return False

    print(f"\n✅ {description} completed successfully")
    return True


def run_unit_tests(workers: str = "auto") -> bool:
    """Run unit tests with coverage."""
    # Clean up old coverage data
    coverage_file = Path(".coverage")
    if coverage_file.exists():
        coverage_file.unlink()

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/unit/",
        "-n",
        workers,
        "--dist=loadscope",
        "-p",
        "no:benchmark",
        "-v",
        "--cov=.",
        "--cov-report=xml:coverage-unit.xml",
        "--cov-report=html:htmlcov-unit",
        "--cov-report=term-missing",
    ]
    return run_command(cmd, "Running unit tests with coverage")


def run_integration_tests(database: Optional[str] = None) -> bool:
    """Run integration tests with coverage for specified database(s)."""
    if database:
        # Run tests for specific database
        databases = [database]
    else:
        # Run tests for all databases (in sequence)
        databases = ["postgresql", "mysql", "sqlserver", "db2", "oracle", "cosmosdb"]

    all_success = True
    coverage_files = []

    for db in databases:
        print(f"\n{'='*60}")
        print(f"🗄️  Running integration tests for {db}")
        print(f"{'='*60}")

        # Set database environment variable
        env = {**os.environ, "DBLIFT_CORE_TEST_DB": db}

        # Run all integration test categories
        test_categories = [
            "tests/integration/commands/",
            "tests/integration/parsers/",
            "tests/integration/features/",
            "tests/integration/scenarios/",
            "tests/integration/concurrency/",
            "tests/integration/introspection/",
        ]

        for category in test_categories:
            coverage_file = f"coverage-integration-{db}-{Path(category).name}.xml"
            cmd = [
                sys.executable,
                "-m",
                "pytest",
                category,
                "-v",
                "--cov=.",
                f"--cov-report=xml:{coverage_file}",
                "--cov-append",  # Append to existing coverage
                "--cov-report=term-missing",
                "-k",
                db,  # Only run tests for this database
            ]

            # Run command with environment variable
            result = subprocess.run(cmd, env=env, capture_output=False)
            if result.returncode != 0:
                print(f"⚠️  Warning: {category} for {db} had some failures")
                all_success = False
            else:
                coverage_files.append(coverage_file)

    # Combine all integration coverage files into one
    if coverage_files:
        print(f"\n📊 Combining {len(coverage_files)} integration coverage files...")
        # Use coverage combine to merge all integration coverage files
        cmd = (
            [
                sys.executable,
                "-m",
                "coverage",
                "combine",
            ]
            + coverage_files
            + ["-o", COVERAGE_INTEGRATION]
        )
        result = subprocess.run(cmd)
        if result.returncode == 0:
            print(f"✅ Integration coverage files combined into {COVERAGE_INTEGRATION}")
        else:
            print("⚠️  Warning: Could not combine integration coverage files")

    return all_success


def combine_coverage_reports() -> bool:
    """Combine unit and integration coverage reports."""
    print(f"\n{'='*60}")
    print("📊 Combining coverage reports")
    print(f"{'='*60}")

    # Check if .coverage file exists (contains all coverage data)
    coverage_data_file = Path(".coverage")
    if not coverage_data_file.exists():
        print("⚠️  No .coverage file found")
        print("   This means no tests were run with --cov-append")
        print("   Trying to use existing XML files...")

        # Try to use existing XML files if available
        unit_file = Path(COVERAGE_UNIT)
        if unit_file.exists():
            print(f"✅ Found unit coverage: {COVERAGE_UNIT}")
            # Copy unit coverage as combined (better than nothing)
            import shutil

            shutil.copy(unit_file, COVERAGE_COMBINED)
            print(f"✅ Created {COVERAGE_COMBINED} from unit tests only")
            return True
        else:
            print(f"❌ No coverage data found")
            return False

    # Generate combined reports from .coverage file
    print("\n📈 Generating combined coverage reports from .coverage...")
    cmd = [
        sys.executable,
        "-m",
        "coverage",
        "xml",
        "-o",
        COVERAGE_COMBINED,
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("❌ Failed to generate XML report")
        return False

    cmd = [
        sys.executable,
        "-m",
        "coverage",
        "html",
        "-d",
        HTML_REPORT_DIR,
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("❌ Failed to generate HTML report")
        return False

    # Show coverage summary
    print("\n📊 Coverage Summary:")
    cmd = [sys.executable, "-m", "coverage", "report", "--show-missing"]
    subprocess.run(cmd)

    print(f"\n✅ Combined coverage report generated:")
    print(f"   - XML: {COVERAGE_COMBINED}")
    print(f"   - HTML: {HTML_REPORT_DIR}/index.html")
    print(f"   - Data: .coverage")

    return True


def upload_to_codecov() -> bool:
    """Upload coverage report to Codecov."""
    print(f"\n{'='*60}")
    print("☁️  Uploading to Codecov")
    print(f"{'='*60}")

    if not Path(COVERAGE_COMBINED).exists():
        print(f"❌ Coverage file not found: {COVERAGE_COMBINED}")
        print("   Run tests first to generate coverage report")
        return False

    # Check if codecov is installed
    try:
        import codecov
    except ImportError:
        print("📦 Installing codecov package...")
        subprocess.run([sys.executable, "-m", "pip", "install", "codecov"], check=True)

    # Upload to Codecov
    cmd = [
        sys.executable,
        "-m",
        "codecov",
        "--file",
        COVERAGE_COMBINED,
        "--token",
        os.environ.get("CODECOV_TOKEN", ""),
    ]

    if not os.environ.get("CODECOV_TOKEN"):
        print("⚠️  Warning: CODECOV_TOKEN not set, attempting tokenless upload")
        print("   (This may fail for protected branches)")

    result = subprocess.run(cmd)
    if result.returncode == 0:
        print("✅ Coverage uploaded to Codecov successfully")
        return True
    else:
        print("❌ Failed to upload to Codecov")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run tests with coverage and generate combined reports"
    )
    parser.add_argument(
        "--unit-only",
        action="store_true",
        help="Run only unit tests",
    )
    parser.add_argument(
        "--unit",
        action="store_true",
        help="Run unit tests (can be combined with --integration)",
    )
    parser.add_argument(
        "--integration",
        action="store_true",
        help="Run integration tests",
    )
    parser.add_argument(
        "--database",
        type=str,
        help="Run integration tests for specific database (postgresql, mysql, sqlserver, db2, oracle, cosmosdb)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all tests (unit + all integration databases)",
    )
    parser.add_argument(
        "--combine-only",
        action="store_true",
        help="Only combine existing coverage reports (don't run tests)",
    )
    parser.add_argument(
        "--upload-codecov",
        action="store_true",
        help="Upload coverage report to Codecov after generation",
    )
    parser.add_argument(
        "--unit-workers",
        default="auto",
        help=(
            "Worker count for unit tests via pytest-xdist. Defaults to 'auto'; "
            "use '0' to disable parallelism while debugging."
        ),
    )

    args = parser.parse_args()

    # If no arguments, show help
    if len(sys.argv) == 1:
        parser.print_help()
        return

    success = True

    if args.combine_only:
        # Just combine existing reports
        success = combine_coverage_reports()
    else:
        # Run tests
        if args.unit_only or args.unit or args.all:
            success = run_unit_tests(args.unit_workers) and success

        if args.integration or args.all:
            success = run_integration_tests(args.database) and success

        # Combine coverage reports
        if success or args.all:
            success = combine_coverage_reports() and success

    # Upload to Codecov if requested
    if args.upload_codecov and success:
        upload_to_codecov()

    if success:
        print(f"\n{'='*60}")
        print("✅ All operations completed successfully!")
        print(f"{'='*60}")
        sys.exit(0)
    else:
        print(f"\n{'='*60}")
        print("❌ Some operations failed")
        print(f"{'='*60}")
        sys.exit(1)


if __name__ == "__main__":
    main()

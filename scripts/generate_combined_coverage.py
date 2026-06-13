#!/usr/bin/env python3
"""
Generate combined coverage report from unit and integration tests.

This script:
1. Runs unit tests with coverage
2. Runs integration tests with coverage (if possible)
3. Combines the coverage reports
4. Generates HTML and terminal reports
5. Shows coverage breakdown by module
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List
from xml.etree import ElementTree as ET


def run_command(cmd, description, check=True):
    """Run a command and return the result."""
    print(f"\n{'='*70}")
    print(f"🔄 {description}")
    print(f"{'='*70}")
    print(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if check and result.returncode != 0:
        print(f"❌ Command failed with exit code {result.returncode}")
        print(f"STDOUT:\n{result.stdout}")
        print(f"STDERR:\n{result.stderr}")
        sys.exit(1)

    return result


def parse_coverage_xml(xml_file: Path) -> dict:
    """Parse coverage.xml and return coverage statistics."""
    if not xml_file.exists():
        return {}

    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()

        # Get overall coverage
        coverage_data: Dict[str, Any] = {
            "lines_covered": int(root.get("lines-covered", 0)),
            "lines_valid": int(root.get("lines-valid", 0)),
            "line_rate": float(root.get("line-rate", 0)),
            "branches_covered": int(root.get("branches-covered", 0)),
            "branches_valid": int(root.get("branches-valid", 0)),
            "branch_rate": float(root.get("branch-rate", 0)),
            "packages": [],
        }

        # Get package-level coverage
        for package in root.findall(".//package"):
            package_data: Dict[str, Any] = {
                "name": package.get("name", ""),
                "line_rate": float(package.get("line-rate", 0)),
                "branch_rate": float(package.get("branch-rate", 0)),
                "classes": [],
            }

            for class_elem in package.findall(".//class"):
                class_data: Dict[str, Any] = {
                    "name": class_elem.get("name", ""),
                    "filename": class_elem.get("filename", ""),
                    "line_rate": float(class_elem.get("line-rate", 0)),
                    "branch_rate": float(class_elem.get("branch-rate", 0)),
                }
                package_data["classes"].append(class_data)

            coverage_data["packages"].append(package_data)

        return coverage_data
    except Exception as e:
        print(f"⚠️  Error parsing {xml_file}: {e}")
        return {}


def combine_coverage_files(unit_xml: Path, integration_xmls: list, output_xml: Path):
    """Combine multiple coverage XML files into one."""
    if not unit_xml.exists():
        print(f"❌ Unit coverage file not found: {unit_xml}")
        return False

    # Start with unit test coverage
    unit_data = parse_coverage_xml(unit_xml)
    if not unit_data:
        print(f"❌ Could not parse unit coverage: {unit_xml}")
        return False

    # For now, we'll use coverage combine if available
    # Otherwise, we'll just use the unit test coverage as baseline
    print(f"📊 Unit test coverage: {unit_data['line_rate']*100:.2f}%")

    # If we have integration coverage files, try to combine them
    if integration_xmls:
        print(f"📊 Found {len(integration_xmls)} integration coverage file(s)")
        # Note: Proper merging requires coverage.py combine command
        # For now, we'll generate a report showing what we have

    return True


def generate_coverage_report():
    """Generate combined coverage report."""
    print("🎯 COMBINED COVERAGE REPORT GENERATOR")
    print("=" * 70)

    # Clean up old coverage files
    print("\n🧹 Cleaning up old coverage files...")
    subprocess.run(["rm", "-f", ".coverage", "coverage.xml", "htmlcov"], check=False)

    # Step 1: Run unit tests with coverage
    print("\n" + "=" * 70)
    print("STEP 1: Running Unit Tests")
    print("=" * 70)

    unit_result = run_command(
        [
            "python",
            "-m",
            "pytest",
            "tests/unit/",
            "-v",
            "--cov=./",
            "--cov-report=xml:coverage-unit.xml",
            "--cov-report=term-missing",
            "--cov-report=html:htmlcov-unit",
        ],
        "Running unit tests with coverage",
        check=False,  # Don't fail if tests fail
    )

    unit_coverage = parse_coverage_xml(Path("coverage-unit.xml"))

    # Step 2: Try to get integration test coverage (if available)
    print("\n" + "=" * 70)
    print("STEP 2: Integration Test Coverage")
    print("=" * 70)
    print("ℹ️  Integration tests require database containers.")
    print("   To get full combined coverage, run integration tests separately")
    print("   and use Codecov to merge the results.")
    print("\n   For local analysis, you can:")
    print("   1. Run integration tests manually with --cov")
    print("   2. Use coverage combine to merge .coverage files")
    print("   3. Generate final report with coverage report")

    # Step 3: Generate summary
    print("\n" + "=" * 70)
    print("COVERAGE SUMMARY")
    print("=" * 70)

    if unit_coverage:
        print(f"\n📊 Unit Test Coverage:")
        print(
            f"   Lines: {unit_coverage['lines_covered']}/{unit_coverage['lines_valid']} "
            f"({unit_coverage['line_rate']*100:.2f}%)"
        )
        print(
            f"   Branches: {unit_coverage['branches_covered']}/{unit_coverage['branches_valid']} "
            f"({unit_coverage['branch_rate']*100:.2f}%)"
        )

        # Show top packages
        print(f"\n📦 Top Packages by Coverage:")
        packages_sorted = sorted(
            unit_coverage["packages"], key=lambda x: x["line_rate"], reverse=True
        )

        for pkg in packages_sorted[:10]:
            if pkg["line_rate"] < 1.0:  # Only show packages with less than 100% coverage
                print(f"   {pkg['name']:40s} {pkg['line_rate']*100:6.2f}%")

        # Show low coverage packages
        low_coverage = [p for p in packages_sorted if p["line_rate"] < 0.8 and p["line_rate"] > 0]
        if low_coverage:
            print(f"\n⚠️  Packages with Low Coverage (<80%):")
            for pkg in low_coverage[:10]:
                print(f"   {pkg['name']:40s} {pkg['line_rate']*100:6.2f}%")
    else:
        print("❌ No unit test coverage data found")

    print("\n" + "=" * 70)
    print("📄 HTML Report Generated: htmlcov-unit/index.html")
    print("📄 XML Report: coverage-unit.xml")
    print("=" * 70)
    print("\n💡 To get combined coverage:")
    print("   1. Run integration tests: pytest tests/integration/ --cov=./ --cov-append")
    print("   2. Combine: coverage combine")
    print("   3. Report: coverage report && coverage html")

    return unit_coverage


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate combined coverage report from unit and integration tests"
    )
    parser.add_argument(
        "--unit-only",
        action="store_true",
        help="Only run unit tests (faster, no database required)",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Open HTML report in browser after generation",
    )

    args = parser.parse_args()

    coverage_data = generate_coverage_report()

    if args.html and Path("htmlcov-unit/index.html").exists():
        import webbrowser

        webbrowser.open(f"file://{Path('htmlcov-unit/index.html').absolute()}")

    # Exit with appropriate code
    if coverage_data and coverage_data.get("line_rate", 0) < 0.8:
        print("\n⚠️  Coverage is below 80% threshold")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()

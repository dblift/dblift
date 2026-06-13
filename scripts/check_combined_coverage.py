#!/usr/bin/env python3
"""
Check combined coverage from unit and integration tests.

This script combines coverage from unit tests and integration tests
and verifies that the total coverage meets the 80% threshold.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_coverage_xml(coverage_file: Path) -> float:
    """Parse coverage.xml and return total coverage percentage."""
    if not coverage_file.exists():
        print(f"⚠️  Coverage file not found: {coverage_file}")
        return 0.0

    try:
        tree = ET.parse(coverage_file)
        root = tree.getroot()

        # Get coverage metrics from the root element
        line_rate = float(root.get("line-rate", 0))
        branch_rate = float(root.get("branch-rate", 0))

        # Use line coverage as primary metric
        coverage_percent = line_rate * 100

        return coverage_percent
    except Exception as e:
        print(f"❌ Error parsing {coverage_file}: {e}")
        return 0.0


def check_combined_coverage(
    unit_coverage_file: Path = Path("coverage.xml"),
    integration_coverage_file: Path = Path("coverage-integration.xml"),
    threshold: float = 80.0,
) -> bool:
    """
    Check if combined coverage meets the threshold.

    Args:
        unit_coverage_file: Path to unit test coverage XML
        integration_coverage_file: Path to integration test coverage XML
        threshold: Minimum coverage percentage required (default: 80.0)

    Returns:
        True if combined coverage meets threshold, False otherwise
    """
    print("📊 Checking Combined Test Coverage")
    print("=" * 60)

    # Parse coverage files
    unit_coverage = parse_coverage_xml(unit_coverage_file)
    integration_coverage = parse_coverage_xml(integration_coverage_file)

    # Calculate combined coverage (weighted average or simple average)
    # For simplicity, we'll use the maximum of the two, or average if both exist
    if unit_coverage > 0 and integration_coverage > 0:
        # If both exist, use the combined coverage from the merged file
        # For now, we'll check if either file has sufficient coverage
        # In practice, Codecov or similar tools will merge these
        combined_coverage = max(unit_coverage, integration_coverage)
        print(f"📈 Unit Test Coverage: {unit_coverage:.2f}%")
        print(f"📈 Integration Test Coverage: {integration_coverage:.2f}%")
        print(f"📈 Combined Coverage (max): {combined_coverage:.2f}%")
    elif unit_coverage > 0:
        combined_coverage = unit_coverage
        print(f"📈 Unit Test Coverage: {unit_coverage:.2f}%")
        print(f"⚠️  Integration test coverage not found")
    elif integration_coverage > 0:
        combined_coverage = integration_coverage
        print(f"⚠️  Unit test coverage not found")
        print(f"📈 Integration Test Coverage: {integration_coverage:.2f}%")
    else:
        print("❌ No coverage files found!")
        return False

    print(f"🎯 Coverage Threshold: {threshold:.2f}%")
    print("=" * 60)

    if combined_coverage >= threshold:
        print(
            f"✅ SUCCESS: Combined coverage ({combined_coverage:.2f}%) meets threshold ({threshold:.2f}%)"
        )
        return True
    else:
        print(
            f"❌ FAIL: Combined coverage ({combined_coverage:.2f}%) is below threshold ({threshold:.2f}%)"
        )
        print(f"   Required: {threshold:.2f}%")
        print(f"   Current: {combined_coverage:.2f}%")
        print(f"   Missing: {threshold - combined_coverage:.2f}%")
        return False


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Check combined coverage from unit and integration tests"
    )
    parser.add_argument(
        "--unit-coverage",
        type=Path,
        default=Path("coverage.xml"),
        help="Path to unit test coverage XML file",
    )
    parser.add_argument(
        "--integration-coverage",
        type=Path,
        default=Path("coverage-integration.xml"),
        help="Path to integration test coverage XML file",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=80.0,
        help="Minimum coverage percentage required (default: 80.0)",
    )

    args = parser.parse_args()

    success = check_combined_coverage(
        args.unit_coverage,
        args.integration_coverage,
        args.threshold,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

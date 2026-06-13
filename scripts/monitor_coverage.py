#!/usr/bin/env python3
"""
Script to monitor test coverage and generate reports.

This script:
1. Runs the test suite with coverage tracking
2. Generates coverage reports (terminal, HTML)
3. Compares coverage against historical data
4. Alerts if coverage drops below threshold
5. Tracks coverage trends over time
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Configuration
COVERAGE_THRESHOLD = 80.0  # Minimum required coverage percentage
COVERAGE_HISTORY_FILE = "coverage_history.json"
COVERAGE_REPORT_FILE = "coverage.json"
COVERAGE_HTML_DIR = "htmlcov"


def run_tests_with_coverage():
    """Run the test suite with coverage tracking."""
    print("Running tests with coverage tracking...")
    result = subprocess.run(
        ["pytest", "--cov=dblift", "--cov-report=json", "--cov-report=html"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("Error: Test suite failed!")
        print(result.stderr)
        sys.exit(1)
    return result.stdout


def load_coverage_data():
    """Load the current coverage data from coverage.json."""
    try:
        with open(COVERAGE_REPORT_FILE, "r") as f:
            data = json.load(f)
            total = data.get("totals", {}).get("percent_covered", 0.0)
            return total
    except FileNotFoundError:
        print(f"Warning: Could not find {COVERAGE_REPORT_FILE}")
        return 0.0


def load_coverage_history():
    """Load historical coverage data."""
    try:
        with open(COVERAGE_HISTORY_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save_coverage_history(history):
    """Save updated coverage history."""
    with open(COVERAGE_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def update_coverage_history(current_coverage):
    """Update coverage history with current data."""
    history = load_coverage_history()
    entry = {"date": datetime.now().isoformat(), "coverage": current_coverage}
    history.append(entry)
    save_coverage_history(history)
    return history


def analyze_coverage_trend(history):
    """Analyze coverage trend from historical data."""
    if len(history) < 2:
        return "Not enough historical data for trend analysis"

    latest = history[-1]["coverage"]
    previous = history[-2]["coverage"]
    diff = latest - previous

    if diff > 0:
        return f"Coverage increased by {diff:.1f}%"
    elif diff < 0:
        return f"Coverage decreased by {abs(diff):.1f}%"
    else:
        return "Coverage remained stable"


def generate_report(current_coverage, history):
    """Generate a coverage report with analysis."""
    print("\nCoverage Report")
    print("=" * 50)
    print(f"Current Coverage: {current_coverage:.1f}%")
    print(f"Coverage Threshold: {COVERAGE_THRESHOLD}%")

    if history:
        trend = analyze_coverage_trend(history)
        print(f"\nTrend: {trend}")

        # Show historical data
        print("\nHistorical Coverage:")
        for entry in history[-5:]:  # Show last 5 entries
            date = datetime.fromisoformat(entry["date"]).strftime("%Y-%m-%d %H:%M")
            print(f"  {date}: {entry['coverage']:.1f}%")

    # Coverage status
    if current_coverage < COVERAGE_THRESHOLD:
        print(
            f"\nWARNING: Coverage ({current_coverage:.1f}%) is below threshold ({COVERAGE_THRESHOLD}%)"
        )
        return False
    else:
        print(f"\nSuccess: Coverage meets or exceeds threshold")
        return True


def main():
    """Main function to run coverage monitoring."""
    # Run tests with coverage
    run_tests_with_coverage()

    # Load and analyze coverage data
    current_coverage = load_coverage_data()
    history = update_coverage_history(current_coverage)

    # Generate report
    success = generate_report(current_coverage, history)

    # Exit with appropriate status
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

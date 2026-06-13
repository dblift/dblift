#!/usr/bin/env python3
"""
Script to identify specific lines that are not covered by tests.

This script analyzes coverage data and generates a report showing:
1. Files with the most uncovered lines
2. Specific line numbers that are not covered
3. Suggestions for which files to prioritize for test coverage

Usage:
    # After running tests with coverage
    python scripts/identify_uncovered_lines.py

    # Focus on specific module
    python scripts/identify_uncovered_lines.py --module db

    # Show top N files with most uncovered lines
    python scripts/identify_uncovered_lines.py --top 20
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import coverage
except ImportError:
    print("❌ Error: coverage package not installed")
    print("   Install it with: pip install coverage")
    sys.exit(1)


def get_coverage_data() -> coverage.Coverage:
    """Load coverage data from .coverage file."""
    cov = coverage.Coverage()

    if not Path(".coverage").exists():
        print("❌ Error: No .coverage file found")
        print("   Run tests with coverage first:")
        print("   python scripts/run_tests_with_coverage.py --unit-only")
        sys.exit(1)

    cov.load()
    return cov


def analyze_uncovered_lines(
    cov: coverage.Coverage, module_filter: str = None
) -> Dict[str, List[int]]:
    """Analyze which lines are not covered."""
    uncovered = {}

    # Get all measured files
    measured_files = cov.get_data().measured_files()

    for filename in measured_files:
        # Filter by module if specified
        if module_filter and module_filter not in filename:
            continue

        # Skip test files and other ignored files
        if any(ignore in filename for ignore in ["tests/", "docs/", "scripts/"]):
            continue

        # Get line numbers that are not covered
        lines = cov.analysis(filename)[2]  # Returns (statements, excluded, missing, missing_branch)

        if lines:
            # Convert to relative path for cleaner output
            rel_path = (
                Path(filename).relative_to(Path.cwd()) if Path(filename).is_absolute() else filename
            )
            uncovered[str(rel_path)] = sorted(lines)

    return uncovered


def get_file_stats(cov: coverage.Coverage, filename: str) -> Tuple[int, int, float]:
    """Get coverage statistics for a file."""
    try:
        analysis = cov.analysis(filename)
        statements = analysis[0]
        missing = analysis[2]
        covered = len(statements) - len(missing)
        percentage = (covered / len(statements) * 100) if statements else 0.0
        return len(statements), len(missing), percentage
    except Exception:
        return 0, 0, 0.0


def print_summary(uncovered: Dict[str, List[int]], top_n: int = None):
    """Print summary of uncovered lines."""
    print("\n" + "=" * 80)
    print("📊 UNCOVERED LINES SUMMARY")
    print("=" * 80)

    # Sort by number of uncovered lines (descending)
    sorted_files = sorted(uncovered.items(), key=lambda x: len(x[1]), reverse=True)

    if top_n:
        sorted_files = sorted_files[:top_n]

    total_uncovered = sum(len(lines) for lines in uncovered.values())
    total_files = len(uncovered)

    print(f"\n📈 Overall Statistics:")
    print(f"   Total files with uncovered lines: {total_files}")
    print(f"   Total uncovered lines: {total_uncovered}")

    print(f"\n🔝 Top {len(sorted_files)} files with most uncovered lines:")
    print("-" * 80)

    for i, (filename, lines) in enumerate(sorted_files, 1):
        print(f"\n{i}. {filename}")
        print(f"   Uncovered lines: {len(lines)}")

        # Show first 20 line numbers
        if len(lines) <= 20:
            print(f"   Line numbers: {', '.join(map(str, lines))}")
        else:
            print(
                f"   Line numbers: {', '.join(map(str, lines[:20]))} ... (+{len(lines) - 20} more)"
            )
            print(f"   Full list: {', '.join(map(str, lines))}")


def print_detailed_report(
    cov: coverage.Coverage, uncovered: Dict[str, List[int]], module_filter: str = None
):
    """Print detailed report with coverage percentages."""
    print("\n" + "=" * 80)
    print("📋 DETAILED COVERAGE REPORT")
    print("=" * 80)

    # Get all files with their stats
    file_stats = []
    measured_files = cov.get_data().measured_files()

    for filename in measured_files:
        if module_filter and module_filter not in filename:
            continue

        # Skip test files
        if any(ignore in filename for ignore in ["tests/", "docs/", "scripts/"]):
            continue

        statements, missing, percentage = get_file_stats(cov, filename)
        if statements > 0:
            rel_path = (
                Path(filename).relative_to(Path.cwd()) if Path(filename).is_absolute() else filename
            )
            file_stats.append((str(rel_path), statements, missing, percentage))

    # Sort by percentage (ascending - lowest coverage first)
    file_stats.sort(key=lambda x: x[3])

    print(f"\n{'File':<50} {'Statements':<12} {'Missing':<10} {'Coverage':<10}")
    print("-" * 80)

    for filename, statements, missing, percentage in file_stats:
        status = "🔴" if percentage < 50 else "🟡" if percentage < 80 else "🟢"
        print(f"{status} {filename:<48} {statements:<12} {missing:<10} {percentage:>6.1f}%")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Identify lines that are not covered by tests")
    parser.add_argument(
        "--module",
        type=str,
        help="Filter by module (e.g., 'db', 'core', 'cli')",
    )
    parser.add_argument(
        "--top",
        type=int,
        help="Show only top N files with most uncovered lines",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Show detailed coverage report with percentages",
    )

    args = parser.parse_args()

    print("🔍 Analyzing coverage data...")
    cov = get_coverage_data()

    uncovered = analyze_uncovered_lines(cov, args.module)

    if not uncovered:
        print("✅ No uncovered lines found!")
        if args.module:
            print(f"   (or no files match module filter: {args.module})")
        return

    # Print summary
    print_summary(uncovered, args.top)

    # Print detailed report if requested
    if args.detailed:
        print_detailed_report(cov, uncovered, args.module)

    # Suggestions
    print("\n" + "=" * 80)
    print("💡 SUGGESTIONS")
    print("=" * 80)
    print("\nTo improve coverage:")
    print("1. Focus on files with the most uncovered lines (shown above)")
    print("2. Generate HTML report to see exact lines:")
    print("   python -m coverage html")
    print("   open htmlcov/index.html")
    print("3. Run integration tests to cover more code:")
    print("   python scripts/run_tests_with_coverage.py --integration --database postgresql")
    print("4. Check specific files in the HTML report (red lines = uncovered)")


if __name__ == "__main__":
    main()

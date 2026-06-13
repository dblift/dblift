#!/usr/bin/env python3
"""
Script to verify coverage uploads to Codecov and check GitHub Actions status.

This script helps you understand:
1. Are integration tests running in GitHub Actions?
2. Are coverage uploads succeeding?
3. How many flags are uploaded to Codecov?
4. What is the actual combined coverage?

Usage:
    python scripts/verify_coverage_uploads.py

    # With GitHub token for more API calls
    export GITHUB_TOKEN=your_github_token
    python scripts/verify_coverage_uploads.py

    # Check specific commit
    python scripts/verify_coverage_uploads.py --commit 5a20418
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import requests  # type: ignore[import-untyped]
except ImportError:
    print("❌ Error: requests package not installed")
    print("   Install it with: pip install requests")
    sys.exit(1)


class CoverageVerifier:
    def __init__(self, owner: str = "cmodiano", repo: str = "dblift"):
        self.owner = owner
        self.repo = repo
        self.github_token = os.environ.get("GITHUB_TOKEN")
        self.codecov_token = os.environ.get("CODECOV_TOKEN")

    def _get_github_headers(self) -> Dict[str, str]:
        """Get headers for GitHub API."""
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
        return headers

    def _get_codecov_headers(self) -> Dict[str, str]:
        """Get headers for Codecov API."""
        headers = {"Accept": "application/json"}
        if self.codecov_token:
            headers["Authorization"] = f"Bearer {self.codecov_token}"
        return headers

    def get_latest_commit(self) -> Optional[str]:
        """Get the latest commit SHA from main branch."""
        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/commits/main"

        try:
            response = requests.get(url, headers=self._get_github_headers())
            if response.status_code == 200:
                data = response.json()
                return str(data["sha"][:7])
            else:
                print(f"⚠️  Could not fetch latest commit: {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ Error fetching latest commit: {e}")
            return None

    def check_github_workflows(self, commit: Optional[str] = None) -> Dict[str, Any]:
        """Check GitHub Actions workflow runs."""
        print("\n" + "=" * 80)
        print("📋 GITHUB ACTIONS STATUS")
        print("=" * 80)

        url = f"https://api.github.com/repos/{self.owner}/{self.repo}/actions/runs"
        params: Dict[str, Any] = {"per_page": 10}
        if commit:
            params["head_sha"] = commit

        try:
            response = requests.get(url, headers=self._get_github_headers(), params=params)
            if response.status_code != 200:
                print(f"❌ Could not fetch workflow runs: {response.status_code}")
                return {}

            data = response.json()
            workflows = {}

            for run in data.get("workflow_runs", []):
                name = run["name"]
                status = run["status"]
                conclusion = run.get("conclusion", "N/A")
                updated = run["updated_at"]

                if name not in workflows:
                    workflows[name] = {
                        "status": status,
                        "conclusion": conclusion,
                        "updated": updated,
                        "url": run["html_url"],
                    }

            # Print summary
            print(f"\nRecent workflow runs:")
            for name, info in workflows.items():
                status_icon = (
                    "✅"
                    if info["conclusion"] == "success"
                    else "❌" if info["conclusion"] == "failure" else "🔄"
                )
                print(f"\n{status_icon} {name}")
                print(f"   Status: {info['status']}")
                print(f"   Conclusion: {info['conclusion']}")
                print(f"   Updated: {info['updated']}")
                print(f"   URL: {info['url']}")

            return workflows

        except Exception as e:
            print(f"❌ Error checking workflows: {e}")
            return {}

    def check_codecov_commit(self, commit: str) -> Optional[Dict]:
        """Check Codecov coverage for a specific commit."""
        print("\n" + "=" * 80)
        print(f"📊 CODECOV COVERAGE FOR COMMIT {commit}")
        print("=" * 80)

        # Try new API format
        url = (
            f"https://api.codecov.io/api/v2/github/{self.owner}/repos/{self.repo}/commits/{commit}"
        )

        try:
            response = requests.get(url, headers=self._get_codecov_headers())

            if response.status_code == 200:
                data = response.json()

                # Extract coverage info
                totals = data.get("totals", {})
                coverage = totals.get("coverage", 0.0)
                files = totals.get("files", 0)
                lines = totals.get("lines", 0)
                hits = totals.get("hits", 0)

                print(f"\n✅ Coverage data found!")
                print(f"   Coverage: {coverage:.2f}%")
                print(f"   Files: {files}")
                print(f"   Lines: {lines}")
                print(f"   Hits: {hits}")
                print(
                    f"   URL: https://app.codecov.io/github/{self.owner}/{self.repo}/commit/{commit}"
                )

                return data  # type: ignore[no-any-return]
            else:
                print(f"⚠️  Could not fetch coverage: {response.status_code}")
                print(f"   Response: {response.text[:200]}")
                return None

        except Exception as e:
            print(f"❌ Error fetching coverage: {e}")
            return None

    def check_codecov_flags(self, commit: str) -> List[str]:
        """Check which flags were uploaded to Codecov for a commit."""
        print("\n" + "=" * 80)
        print(f"🏴 CODECOV FLAGS FOR COMMIT {commit}")
        print("=" * 80)

        # Get flags from commit
        url = f"https://api.codecov.io/api/v2/github/{self.owner}/repos/{self.repo}/commits/{commit}/flags"

        try:
            response = requests.get(url, headers=self._get_codecov_headers())

            if response.status_code == 200:
                data = response.json()
                flags = []

                for flag_data in data.get("results", []):
                    flag_name = flag_data.get("flag_name")
                    if flag_name:
                        flags.append(flag_name)

                if flags:
                    print(f"\n✅ Found {len(flags)} flags:")

                    # Group by category
                    unit_flags = [f for f in flags if f.startswith("unit")]
                    command_flags = [f for f in flags if "commands" in f]
                    parser_flags = [f for f in flags if "parsers" in f]
                    feature_flags = [f for f in flags if "features" in f]
                    scenario_flags = [f for f in flags if "scenarios" in f]
                    concurrency_flags = [f for f in flags if "concurrency" in f]
                    introspection_flags = [f for f in flags if "introspection" in f]
                    validation_flags = [f for f in flags if "validation" in f]

                    print(f"\n   Unit: {len(unit_flags)}")
                    for flag in unit_flags:
                        print(f"      - {flag}")

                    if command_flags:
                        print(f"\n   Commands: {len(command_flags)}")
                        for flag in command_flags:
                            print(f"      - {flag}")

                    if parser_flags:
                        print(f"\n   Parsers: {len(parser_flags)}")
                        for flag in parser_flags:
                            print(f"      - {flag}")

                    if feature_flags:
                        print(f"\n   Features: {len(feature_flags)}")
                        for flag in feature_flags:
                            print(f"      - {flag}")

                    if scenario_flags:
                        print(f"\n   Scenarios: {len(scenario_flags)}")
                        for flag in scenario_flags:
                            print(f"      - {flag}")

                    if concurrency_flags:
                        print(f"\n   Concurrency: {len(concurrency_flags)}")
                        for flag in concurrency_flags:
                            print(f"      - {flag}")

                    if introspection_flags:
                        print(f"\n   Introspection: {len(introspection_flags)}")
                        for flag in introspection_flags:
                            print(f"      - {flag}")

                    if validation_flags:
                        print(f"\n   Validation: {len(validation_flags)}")
                        for flag in validation_flags:
                            print(f"      - {flag}")

                    return flags
                else:
                    print("\n⚠️  No flags found for this commit")
                    return []
            else:
                print(f"⚠️  Could not fetch flags: {response.status_code}")
                print(f"   Response: {response.text[:200]}")
                return []

        except Exception as e:
            print(f"❌ Error fetching flags: {e}")
            return []

    def analyze_coverage_status(self, commit: str):
        """Analyze overall coverage status."""
        print("\n" + "=" * 80)
        print("🔍 COVERAGE ANALYSIS")
        print("=" * 80)

        # Check Codecov
        codecov_data = self.check_codecov_commit(commit)
        flags = self.check_codecov_flags(commit)

        if codecov_data and flags:
            coverage = codecov_data.get("totals", {}).get("coverage", 0.0)

            print("\n📈 Analysis Results:")
            print("-" * 80)

            # Check coverage level
            if coverage >= 80:
                print(f"✅ Coverage is EXCELLENT: {coverage:.2f}% (target: 80%)")
            elif coverage >= 70:
                print(f"🟡 Coverage is GOOD: {coverage:.2f}% (target: 80%)")
                print(f"   Need {80 - coverage:.2f}% more to reach target")
            elif coverage >= 50:
                print(f"🟠 Coverage is MODERATE: {coverage:.2f}% (target: 80%)")
                print(f"   Need {80 - coverage:.2f}% more to reach target")
            else:
                print(f"🔴 Coverage is LOW: {coverage:.2f}% (target: 80%)")
                print(f"   Need {80 - coverage:.2f}% more to reach target")

            # Check flags
            print(f"\n📋 Flag Analysis:")
            if len(flags) >= 40:
                print(f"   ✅ {len(flags)} flags uploaded (expected: ~45)")
                print(f"   Integration tests are uploading correctly")
            elif len(flags) >= 20:
                print(f"   🟡 {len(flags)} flags uploaded (expected: ~45)")
                print(f"   Some integration tests may be missing")
            elif len(flags) >= 5:
                print(f"   🟠 {len(flags)} flags uploaded (expected: ~45)")
                print(f"   Many integration tests are missing")
            else:
                print(f"   🔴 {len(flags)} flags uploaded (expected: ~45)")
                print(f"   Integration tests are NOT uploading")

            # Recommendations
            print(f"\n💡 Recommendations:")
            if coverage < 70 and len(flags) < 40:
                print("   1. ⚠️  Integration tests are not fully running/uploading")
                print("   2. Trigger 'Integration Tests (New Structure)' workflow manually")
                print("   3. Check GitHub Actions for failed jobs")
            elif coverage < 70 and len(flags) >= 40:
                print("   1. ✅ Integration tests are uploading")
                print("   2. ⚠️  But they're not covering enough code")
                print("   3. Run local coverage analysis:")
                print("      python scripts/identify_uncovered_lines.py --top 20")
            else:
                print("   1. ✅ Coverage looks good!")
                print("   2. Continue maintaining test coverage")
        else:
            print("\n⚠️  Could not complete analysis")
            print("   Check that the commit exists and coverage was uploaded")


def main():
    parser = argparse.ArgumentParser(
        description="Verify coverage uploads to Codecov and GitHub Actions status"
    )
    parser.add_argument(
        "--commit",
        type=str,
        help="Specific commit SHA to check (default: latest on main)",
    )
    parser.add_argument(
        "--owner",
        type=str,
        default="cmodiano",
        help="GitHub repository owner (default: cmodiano)",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="dblift",
        help="GitHub repository name (default: dblift)",
    )

    args = parser.parse_args()

    print("🔍 Coverage Upload Verification Tool")
    print("=" * 80)

    verifier = CoverageVerifier(owner=args.owner, repo=args.repo)

    # Get commit
    commit = args.commit
    if not commit:
        print("\n📡 Fetching latest commit from main branch...")
        commit = verifier.get_latest_commit()
        if not commit:
            print("❌ Could not determine commit to check")
            sys.exit(1)

    print(f"\n✅ Checking commit: {commit}")

    # Check GitHub Actions
    verifier.check_github_workflows(commit)

    # Check Codecov
    verifier.check_codecov_commit(commit)
    verifier.check_codecov_flags(commit)

    # Analyze
    verifier.analyze_coverage_status(commit)

    print("\n" + "=" * 80)
    print("✅ Verification complete!")
    print("=" * 80)
    print("\nFor more details:")
    print(f"   Codecov: https://app.codecov.io/github/{args.owner}/{args.repo}/commit/{commit}")
    print(f"   GitHub: https://github.com/{args.owner}/{args.repo}/actions")


if __name__ == "__main__":
    main()

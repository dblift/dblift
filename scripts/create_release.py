#!/usr/bin/env python3
"""
Script to automate the release process for dblift.

This script:
1. Renames ``## [Unreleased]`` in ``CHANGELOG.md`` (Keep a Changelog format) to
   ``## [<version>] - <today>``, then inserts a fresh empty ``## [Unreleased]``
   section above it
2. Bumps ``version`` in ``pyproject.toml`` and ``__version__`` in ``__init__.py``
3. Creates a git commit with these changes
4. Creates an annotated git tag ``v<version>``
5. Optionally pushes the branch and tag to ``origin`` (expects ``main`` — adjust
   if your release lands on ``develop`` first)

Usage:
    python scripts/create_release.py [--dry-run] [--push] <version>

After running, update the ``[Unreleased]:`` / ``[x.y.z]:`` compare links at the
bottom of ``CHANGELOG.md`` if your release workflow expects them (this repo
typically commits those in the same release-prep PR).

Examples:
    python scripts/create_release.py --dry-run 1.7.0
    python scripts/create_release.py --push 1.7.0
"""

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path


def run_command(cmd, dry_run=False):
    """Run a shell command."""
    print(f"Running: {cmd}")
    if dry_run:
        return "Dry run", 0

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error executing command: {cmd}")
        print(f"Output: {result.stdout}")
        print(f"Error: {result.stderr}")
        return result.stderr, result.returncode
    return result.stdout.strip(), result.returncode


def update_changelog(version, dry_run=False):
    """
    Update CHANGELOG.md by moving ``## [Unreleased]`` to ``## [<version>] - <date>``.

    Expects Keep a Changelog-style headings (``## [Unreleased]``). Inserts a fresh
    empty ``## [Unreleased]`` block *above* the newly dated section.
    """
    changelog_path = Path("CHANGELOG.md")
    if not changelog_path.exists():
        print("Error: CHANGELOG.md not found!")
        return False

    today = datetime.date.today().strftime("%Y-%m-%d")

    with open(changelog_path, "r") as f:
        content = f.read()

    if "## [Unreleased]" not in content:
        print("Error: No ## [Unreleased] section found in CHANGELOG.md")
        return False

    new_unreleased = """## [Unreleased]

### Added

### Changed

### Fixed

### Removed

"""

    header = f"## [{version}] - {today}"
    # Rename the first Unreleased section to the release heading
    renamed = content.replace("## [Unreleased]", header, 1)
    pos = renamed.find(header)
    if pos < 0:
        print("Error: Could not locate release heading after rename")
        return False

    updated_content = renamed[:pos] + new_unreleased + renamed[pos:]

    if dry_run:
        print("Would update CHANGELOG.md with:")
        print(updated_content[:500] + "...")  # Show beginning of the file
    else:
        with open(changelog_path, "w") as f:
            f.write(updated_content)
        print("Updated CHANGELOG.md")

    return True


def update_version_in_files(version, dry_run=False):
    """
    Update version number in ``pyproject.toml`` and root ``__version__``.
    """
    success = True

    pyproject = Path("pyproject.toml")
    if pyproject.exists():
        text = pyproject.read_text()
        # Only the [project] version line (first occurrence at line start)
        updated = re.sub(
            r'^version = "\d+\.\d+\.\d+"',
            f'version = "{version}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if updated != text:
            if dry_run:
                print(f"Would update version in {pyproject}")
            else:
                pyproject.write_text(updated)
                print(f"Updated version in {pyproject}")
        else:
            print(f"Warning: No version line found in {pyproject}")
            success = False
    else:
        print("Warning: pyproject.toml not found")
        success = False

    init_py = Path("__init__.py")
    if init_py.exists():
        text = init_py.read_text()
        version_pattern = r'__version__\s*=\s*[\'"](\d+\.\d+\.\d+)[\'"]'
        if re.search(version_pattern, text):
            updated = re.sub(version_pattern, f'__version__ = "{version}"', text)
            if dry_run:
                print(f"Would update version in {init_py}")
            else:
                init_py.write_text(updated)
                print(f"Updated version in {init_py}")
        else:
            print(f"Warning: No __version__ pattern in {init_py}")
            success = False

    return success


def create_git_commit(version, dry_run=False):
    """
    Create a git commit with the version changes.
    """
    commit_message = f"Bump version to {version}"
    output, returncode = run_command(f'git commit -am "{commit_message}"', dry_run)

    if returncode != 0:
        print(f"Error creating commit: {output}")
        return False

    print(f"Created commit: {output}")
    return True


def create_git_tag(version, dry_run=False):
    """
    Create a git tag for the new version.
    """
    tag_name = f"v{version}"
    tag_message = f"Release version {version}"

    output, returncode = run_command(f'git tag -a {tag_name} -m "{tag_message}"', dry_run)

    if returncode != 0:
        print(f"Error creating tag: {output}")
        return False

    print(f"Created tag: {tag_name}")
    return True


def push_to_github(version, dry_run=False):
    """
    Push changes and tag to GitHub.
    """
    # Push commits
    output, returncode = run_command("git push origin main", dry_run)
    if returncode != 0:
        print(f"Error pushing commits: {output}")
        return False

    # Push tag
    tag_name = f"v{version}"
    output, returncode = run_command(f"git push origin {tag_name}", dry_run)
    if returncode != 0:
        print(f"Error pushing tag: {output}")
        return False

    print("Successfully pushed changes and tag to GitHub")
    return True


def extract_version_changelog(version):
    """
    Extract the changelog for the specified version to use in GitHub release.
    """
    changelog_path = Path("CHANGELOG.md")
    if not changelog_path.exists():
        return None

    with open(changelog_path, "r") as f:
        content = f.read()

    # Find the section for this version (Keep a Changelog: ## [x.y.z] - date)
    # Body until the next version heading at column 0 (``## [``)
    pattern = rf"## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}\n" r"(.*?)(?=^## \[|\Z)"
    match = re.search(pattern, content, re.DOTALL | re.MULTILINE)

    if not match:
        return None

    # Extract and clean up the section
    section = match.group(1).strip()
    return section


def validate_version(version):
    """
    Validate that the version string follows semantic versioning.
    """
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        print("Error: Version must be in the format 'x.y.z' (e.g., '1.2.3')")
        return False
    return True


def check_git_status():
    """
    Check if the git working directory is clean.
    """
    output, _ = run_command("git status --porcelain")
    if output:
        print("Error: Git working directory is not clean. Please commit or stash your changes.")
        print(output)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Create a new release for dblift")
    parser.add_argument("version", help="The version number to release (e.g., 0.4.0)")
    parser.add_argument("--dry-run", action="store_true", help="Don't make any actual changes")
    parser.add_argument(
        "--push", action="store_true", help="Push changes to GitHub after creating the release"
    )

    args = parser.parse_args()
    version = args.version
    dry_run = args.dry_run

    # Validate the version format
    if not validate_version(version):
        sys.exit(1)

    # Check if git is clean
    if not dry_run and not check_git_status():
        sys.exit(1)

    print(f"Creating release for version {version}" + (" (DRY RUN)" if dry_run else ""))

    # Update CHANGELOG.md
    if not update_changelog(version, dry_run):
        sys.exit(1)

    # Update version in files
    if not update_version_in_files(version, dry_run):
        print("Warning: Some version files could not be updated")

    # Create git commit
    if not create_git_commit(version, dry_run):
        sys.exit(1)

    # Create git tag
    if not create_git_tag(version, dry_run):
        sys.exit(1)

    # Extract changelog section for this version
    if not dry_run:
        changelog_section = extract_version_changelog(version)
        if changelog_section:
            print("\nChangelog for this release:")
            print(changelog_section)

            # Save to a file for GitHub release
            with open("RELEASE_NOTES.md", "w") as f:
                f.write(changelog_section)
            print("\nSaved release notes to RELEASE_NOTES.md")

    # Push to GitHub if requested
    if args.push:
        if not push_to_github(version, dry_run):
            sys.exit(1)

        print(f"\nRelease {version} has been created and pushed to GitHub")
        print("The GitHub Actions workflow should now build and create the release.")
    else:
        print(f"\nRelease {version} has been created locally")
        print("To push it to GitHub, run:")
        print(f"  git push origin main && git push origin v{version}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

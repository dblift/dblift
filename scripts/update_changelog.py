#!/usr/bin/env python3
"""
Script to update the CHANGELOG.md file with new entries.

This script:
1. Adds new entries to the "Unreleased" section of the CHANGELOG.md
2. Creates a new section if needed
3. Organizes entries into Added/Changed/Fixed categories

Usage:
    python update_changelog.py [--type TYPE] "Your changelog entry"

Options:
    --type TYPE  Type of change: added, changed, fixed (default: added)

Examples:
    python update_changelog.py --type added "Added new feature X"
    python update_changelog.py --type fixed "Fixed bug in function Y"
    python update_changelog.py --type changed "Updated dependency Z"
"""

import argparse
import re
import sys
from pathlib import Path


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Update CHANGELOG.md with new entries")
    parser.add_argument("entry", help="The changelog entry text")
    parser.add_argument(
        "--type",
        choices=["added", "changed", "fixed"],
        default="added",
        help="Type of change: added, changed, fixed (default: added)",
    )
    return parser.parse_args()


def ensure_unreleased_section(content):
    """
    Ensure there's an "Unreleased" section in the changelog.
    If not, create one after the title.
    """
    unreleased_pattern = (
        r"## Version \d+\.\d+\.\d+ \(Unreleased\)|## Version x\.y\.z \(Unreleased\)"
    )
    if not re.search(unreleased_pattern, content):
        # Create a new unreleased section after the title
        title_match = re.search(r"# Changelog\n+", content)
        if title_match:
            position = title_match.end()
            new_unreleased = """## Version x.y.z (Unreleased)

### Added
- 

### Changed
- 

### Fixed
- 

"""
            content = content[:position] + new_unreleased + content[position:]

    return content


def add_entry_to_section(content, entry_type, entry_text):
    """
    Add a new entry to the appropriate section (Added/Changed/Fixed)
    within the Unreleased section.
    """
    # Find the unreleased section
    unreleased_pattern = (
        r"## Version \d+\.\d+\.\d+ \(Unreleased\)|## Version x\.y\.z \(Unreleased\)"
    )
    unreleased_match = re.search(unreleased_pattern, content)

    if not unreleased_match:
        print("Error: Couldn't find or create Unreleased section")
        return content

    # Capitalize the entry type for section matching
    section_type = entry_type.capitalize()

    # Find the appropriate section within Unreleased
    section_pattern = rf"(### {section_type}.*?)(?=### |## |$)"
    section_match = re.search(section_pattern, content[unreleased_match.end() :], re.DOTALL)

    if not section_match:
        print(f"Error: Couldn't find {section_type} section within Unreleased")
        return content

    # Calculate the absolute position in the content
    section_start = unreleased_match.end() + section_match.start()
    section_end = unreleased_match.end() + section_match.end()

    # Extract the section content
    section_content = content[section_start:section_end]

    # Check if there's already content in the section
    if re.search(r"- [^\s]", section_content):
        # There are existing entries, add new entry at the end
        new_section = section_content.rstrip() + f"\n- {entry_text}\n"
    else:
        # The section is empty (just has placeholder), replace it
        new_section = f"### {section_type}\n- {entry_text}\n"

    # Replace the section in the content
    new_content = content[:section_start] + new_section + content[section_end:]

    return new_content


def update_changelog(entry_type, entry_text):
    """
    Update the CHANGELOG.md file with a new entry.
    """
    changelog_path = Path("CHANGELOG.md")

    if not changelog_path.exists():
        print("Error: CHANGELOG.md not found!")
        return False

    with open(changelog_path, "r") as f:
        content = f.read()

    # Ensure there's an Unreleased section
    content = ensure_unreleased_section(content)

    # Add the entry to the appropriate section
    content = add_entry_to_section(content, entry_type, entry_text)

    # Write the updated content back to the file
    with open(changelog_path, "w") as f:
        f.write(content)

    print(f"Added '{entry_text}' to {entry_type.capitalize()} section in CHANGELOG.md")
    return True


def main():
    args = parse_args()
    success = update_changelog(args.type, args.entry)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

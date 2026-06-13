#!/usr/bin/env python3
"""
Script to refactor database-specific test files to use @pytest.mark.parametrize with db_container.

This script refactors test files for MySQL, Oracle, SQL Server, etc. to use the same pattern
as the general tests, using @pytest.mark.parametrize with db_container limited to a single database.
"""

import re
from pathlib import Path
from typing import List, Tuple


def refactor_test_file(file_path: Path, db_type: str, fixture_name: str) -> bool:
    """
    Refactor a database-specific test file.

    Args:
        file_path: Path to the test file
        db_type: Database type (e.g., "mysql", "oracle", "sqlserver")
        fixture_name: Name of the fixture (e.g., "mysql_container", "oracle_container")

    Returns:
        True if file was modified, False otherwise
    """
    with open(file_path, "r") as f:
        content = f.read()

    original_content = content

    # 1. Add @pytest.mark.parametrize decorator if not present
    if "@pytest.mark.parametrize" not in content:
        # Find the @pytest.mark.integration line and add parametrize after it
        content = re.sub(
            r"(@pytest\.mark\.integration)\nclass",
            rf'\1\n@pytest.mark.parametrize(\n    "db_container",\n    ["{db_type}"],\n    indirect=True,\n)\nclass',
            content,
        )

    # 2. Replace fixture_name with db_container everywhere
    content = content.replace(fixture_name, "db_container")

    # 3. Update _get_provider method if it exists
    # We need to make it generic like the multi-database tests

    # Check if we need to update _get_provider to be generic
    if f"def _get_provider(self, db_container):" in content:
        # Extract db_type from db_container["type"]
        # Update type="db_type" to type=db_type
        if f'type="{db_type}"' in content:
            # Check if already has db_type extraction
            if 'db_type = db_container["type"]' not in content:
                # Insert db_type and schema extraction after docstring
                pattern = rf'(def _get_provider\(self, db_container\):\s*"""[^"]*?"""\s*\n\s*)(from config import)'
                replacement = r'\1\2\n        from config.database_config import DatabaseConfig\n        from db.provider_registry import ProviderRegistry\n\n        db_type = db_container["type"]\n        schema = db_container.get("schema", "TEST_SCHEMA")\n\n        '
                content = re.sub(pattern, replacement, content, flags=re.DOTALL)

            # Replace type="db_type" with type=db_type
            content = content.replace(f'type="{db_type}",', "type=db_type,")

        # Update schema default if needed
        # This depends on the database - we'll use TEST_SCHEMA as default
        schema_patterns = [
            (r'schema=db_container\.get\("schema", "[^"]+"\),', "schema=schema,"),
        ]
        for pattern, replacement in schema_patterns:
            content = re.sub(pattern, replacement, content)

    # Only write if content changed
    if content != original_content:
        with open(file_path, "w") as f:
            f.write(content)
        return True
    return False


def main():
    """Refactor all database-specific test files."""
    test_dir = Path(__file__).parent.parent / "tests" / "integration" / "validation"

    # Database mappings: (pattern, db_type, fixture_name)
    databases = [
        ("test_mysql_*.py", "mysql", "mysql_container"),
        ("test_oracle_*.py", "oracle", "oracle_container"),
        ("test_sqlserver_*.py", "sqlserver", "sqlserver_container"),
    ]

    total_updated = 0

    for pattern, db_type, fixture_name in databases:
        files = sorted(test_dir.glob(pattern))
        print(f"\n=== Refactoring {db_type.upper()} tests ({len(files)} files) ===")

        for file_path in files:
            if refactor_test_file(file_path, db_type, fixture_name):
                print(f"  ✓ {file_path.name}")
                total_updated += 1
            else:
                # Check if already refactored
                content = file_path.read_text()
                if "@pytest.mark.parametrize" in content and f'["{db_type}"]' in content:
                    print(f"  - {file_path.name} (already refactored)")
                elif fixture_name not in content:
                    print(f"  - {file_path.name} (no {fixture_name} found)")
                else:
                    print(f"  ✗ {file_path.name} (needs manual refactoring)")

    print(f"\n✅ Updated {total_updated} files total")


if __name__ == "__main__":
    main()

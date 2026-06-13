#!/usr/bin/env python3
"""
Script to find unused functions, classes, and imports in the dblift codebase.
This script combines multiple approaches for comprehensive analysis.
"""

import argparse
import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


class UnusedCodeFinder:
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.python_files: list[Path] = []
        self.definitions: dict[str, dict] = {}  # file -> {functions, classes, imports}
        self.usages: dict[str, dict] = {}  # file -> {called_functions, used_classes}

        # Patterns to ignore (common test patterns, fixtures, etc.)
        self.ignore_patterns = {
            "test_*",
            "*_test",
            "conftest",
            "setup",
            "teardown",
            "cleanup_*",
            "mock_*",
            "__*__",
            "main",
            "cli_main",
        }

        # Directories to exclude
        self.exclude_dirs = {
            "venv",
            "htmlcov",
            ".mypy_cache",
            "__pycache__",
            ".git",
            "dist",
            "build",
            ".pytest_cache",
            "dblift.egg-info",
            ".cursor",
        }

    def find_python_files(self) -> List[Path]:
        """Find all Python files in the project."""
        files = []
        for root, dirs, file_names in os.walk(self.root_dir):
            # Remove excluded directories
            dirs[:] = [d for d in dirs if d not in self.exclude_dirs]

            for file_name in file_names:
                if file_name.endswith(".py"):
                    files.append(Path(root) / file_name)
        return files

    def extract_definitions(self, file_path: Path) -> dict[str, list[dict]]:
        """Extract function and class definitions from a Python file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content)
            definitions: dict[str, list[dict]] = {"functions": [], "classes": [], "imports": []}

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Skip private/special methods and test functions
                    if not any(
                        pattern.replace("*", "") in node.name for pattern in self.ignore_patterns
                    ):
                        definitions["functions"].append(
                            {
                                "name": node.name,
                                "line": node.lineno,
                                "is_public": not node.name.startswith("_"),
                            }
                        )

                elif isinstance(node, ast.ClassDef):
                    if not any(
                        pattern.replace("*", "") in node.name for pattern in self.ignore_patterns
                    ):
                        definitions["classes"].append(
                            {
                                "name": node.name,
                                "line": node.lineno,
                                "is_public": not node.name.startswith("_"),
                            }
                        )

                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        import_name = alias.name if alias.name != "*" else None
                        if import_name:
                            definitions["imports"].append(
                                {"name": import_name, "line": node.lineno, "alias": alias.asname}
                            )

            return definitions
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            return {"functions": [], "classes": [], "imports": []}

    def extract_usages(self, file_path: Path) -> dict[str, set]:
        """Extract function calls and class usage from a Python file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            tree = ast.parse(content)
            usages: dict[str, set] = {
                "function_calls": set(),
                "class_uses": set(),
                "name_uses": set(),
            }

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        usages["function_calls"].add(node.func.id)
                    elif isinstance(node.func, ast.Attribute):
                        usages["function_calls"].add(node.func.attr)

                elif isinstance(node, ast.Name):
                    usages["name_uses"].add(node.id)

            return usages
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            return {"function_calls": set(), "class_uses": set(), "name_uses": set()}

    def run_vulture(self) -> List[str]:
        """Run vulture and return its findings."""
        try:
            cmd = [
                "vulture",
                str(self.root_dir),
                "--exclude",
                ",".join(self.exclude_dirs),
                "--min-confidence",
                "80",
                "--ignore-names",
                ",".join(self.ignore_patterns),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.stdout.split("\n") if result.stdout else []
        except subprocess.CalledProcessError:
            return []
        except FileNotFoundError:
            print("Vulture not installed. Install with: pip install vulture")
            return []

    def analyze_project(self) -> Dict:
        """Perform comprehensive analysis of the project."""
        print("🔍 Finding Python files...")
        self.python_files = self.find_python_files()
        print(f"Found {len(self.python_files)} Python files")

        print("📖 Extracting definitions and usages...")
        all_definitions: dict[str, dict] = {}
        all_usages: set[str] = set()

        for file_path in self.python_files:
            rel_path = str(file_path.relative_to(self.root_dir))
            definitions = self.extract_definitions(file_path)
            usages = self.extract_usages(file_path)

            all_definitions[rel_path] = definitions
            all_usages.update(usages["function_calls"])
            all_usages.update(usages["name_uses"])

        print("🔍 Running vulture analysis...")
        vulture_findings = self.run_vulture()

        print("🧹 Finding potentially unused functions...")
        unused_functions = []

        for file_path_str, definitions in all_definitions.items():
            for func in definitions["functions"]:
                if func["name"] not in all_usages and func["is_public"]:
                    unused_functions.append(
                        {
                            "file": file_path_str,
                            "name": func["name"],
                            "line": func["line"],
                            "type": "function",
                        }
                    )

        unused_classes = []
        for file_path_str, definitions in all_definitions.items():
            for cls in definitions["classes"]:
                if cls["name"] not in all_usages and cls["is_public"]:
                    unused_classes.append(
                        {
                            "file": file_path_str,
                            "name": cls["name"],
                            "line": cls["line"],
                            "type": "class",
                        }
                    )

        return {
            "unused_functions": unused_functions,
            "unused_classes": unused_classes,
            "vulture_findings": vulture_findings,
            "total_files": len(self.python_files),
        }

    def generate_report(self, analysis: Dict, output_format: str = "text"):
        """Generate a report of findings."""
        if output_format == "json":
            return json.dumps(analysis, indent=2)

        report = []
        report.append("=" * 60)
        report.append("🔍 UNUSED CODE ANALYSIS REPORT")
        report.append("=" * 60)
        report.append(f"📁 Analyzed {analysis['total_files']} Python files")
        report.append("")

        # Unused functions
        if analysis["unused_functions"]:
            report.append("🚫 POTENTIALLY UNUSED FUNCTIONS:")
            report.append("-" * 40)
            for func in analysis["unused_functions"]:
                report.append(f"  📄 {func['file']}:{func['line']} - {func['name']}()")
            report.append("")
        else:
            report.append("✅ No unused functions found")
            report.append("")

        # Unused classes
        if analysis["unused_classes"]:
            report.append("🚫 POTENTIALLY UNUSED CLASSES:")
            report.append("-" * 40)
            for cls in analysis["unused_classes"]:
                report.append(f"  📄 {cls['file']}:{cls['line']} - {cls['name']}")
            report.append("")
        else:
            report.append("✅ No unused classes found")
            report.append("")

        # Vulture findings
        if analysis["vulture_findings"]:
            report.append("🐍 VULTURE FINDINGS (imports, variables, etc.):")
            report.append("-" * 50)
            for finding in analysis["vulture_findings"]:
                if finding.strip():
                    report.append(f"  {finding}")
            report.append("")

        report.append("=" * 60)
        report.append("💡 RECOMMENDATIONS:")
        report.append("=" * 60)
        report.append("1. Review each finding manually - some may be:")
        report.append("   • Entry points (CLI commands, main functions)")
        report.append("   • Public API functions")
        report.append("   • Used via reflection or dynamic calls")
        report.append("   • Test fixtures or utilities")
        report.append("")
        report.append("2. For confirmed unused code:")
        report.append("   • Remove unused imports first")
        report.append("   • Remove unused variables")
        report.append("   • Consider deprecating public functions before removal")
        report.append("   • Remove unused classes and private functions")
        report.append("")
        report.append("3. Use your IDE's 'Find Usages' feature to double-check")
        report.append("")

        return "\n".join(report)


def main():
    parser = argparse.ArgumentParser(description="Find unused code in the dblift project")
    parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format (default: text)"
    )
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    parser.add_argument("--root", default=".", help="Root directory to analyze")

    args = parser.parse_args()

    finder = UnusedCodeFinder(args.root)
    analysis = finder.analyze_project()
    report = finder.generate_report(analysis, args.format)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        print(f"Report saved to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()

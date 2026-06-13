#!/usr/bin/env python3
"""Extract useful patterns from ANTLR grammar files to improve regex parsers.

This script reads ANTLR grammar files (without requiring ANTLR runtime)
and extracts:
- Keywords (reserved words)
- Operators
- Identifier patterns
- Statement patterns
- Syntax rules

These can then be used to improve regex patterns in our parsers.
"""

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set


def extract_keywords(lexer_content: str) -> Set[str]:
    """Extract keywords from ANTLR lexer file.

    Keywords are typically defined as:
    - KEYWORD: 'keyword';
    - Or in a fragment with case-insensitive matching

    Args:
        lexer_content: Content of lexer .g4 file

    Returns:
        Set of keyword strings
    """
    keywords: Set[str] = set()

    # Pattern 1: Explicit keyword definitions
    # KEYWORD: 'keyword';
    keyword_pattern = r"(\w+)\s*:\s*['\"]([\w\s]+)['\"]\s*;"
    for match in re.finditer(keyword_pattern, lexer_content):
        keyword_name = match.group(1)
        keyword_value = match.group(2).upper()

        # Skip if it's clearly not a keyword (operators, etc.)
        if keyword_name in ["OPEN_PAREN", "CLOSE_PAREN", "COMMA", "SEMI"]:
            continue

        # Add if it looks like a keyword
        if keyword_value.isalpha() and len(keyword_value) > 1:
            keywords.add(keyword_value)

    # Pattern 2: Keywords in reserved word lists
    # Look for patterns like: KEYWORD: 'SELECT' | 'INSERT' | ...
    reserved_pattern = r"(\w+)\s*:\s*(?:['\"](\w+)['\"]\s*\|?\s*)+"
    for match in re.finditer(reserved_pattern, lexer_content):
        keyword_value = match.group(2).upper()
        if keyword_value.isalpha():
            keywords.add(keyword_value)

    # Pattern 3: Keywords in case-insensitive fragments
    # Fragment keywords often have case variants
    fragment_pattern = r"fragment\s+\w+\s*:\s*['\"](\w+)['\"]"
    for match in re.finditer(fragment_pattern, lexer_content, re.IGNORECASE):
        keyword_value = match.group(1).upper()
        if keyword_value.isalpha():
            keywords.add(keyword_value)

    return keywords


def extract_operators(lexer_content: str) -> Dict[str, str]:
    """Extract operators from ANTLR lexer file.

    Operators are typically defined as:
    - PLUS: '+';
    - EQUAL: '=';

    Args:
        lexer_content: Content of lexer .g4 file

    Returns:
        Dict mapping operator names to symbols
    """
    operators: Dict[str, str] = {}

    # Pattern: OPERATOR_NAME: 'symbol';
    operator_pattern = r"(\w+)\s*:\s*['\"]([^\'\"]+)['\"]\s*;"
    for match in re.finditer(operator_pattern, lexer_content):
        op_name = match.group(1)
        op_symbol = match.group(2)

        # Only include if it looks like an operator
        if op_name in [
            "PLUS",
            "MINUS",
            "STAR",
            "SLASH",
            "EQUAL",
            "NOT_EQUAL",
            "LESS_THAN",
            "GREATER_THAN",
            "LESS_EQUAL",
            "GREATER_EQUAL",
            "AND",
            "OR",
            "NOT",
            "DOT",
            "COMMA",
            "SEMI",
            "COLON",
            "OPEN_PAREN",
            "CLOSE_PAREN",
        ]:
            operators[op_name] = op_symbol

    return operators


def extract_identifier_patterns(lexer_content: str) -> List[str]:
    """Extract identifier patterns from lexer file.

    Identifiers are typically defined with regex-like patterns.

    Args:
        lexer_content: Content of lexer .g4 file

    Returns:
        List of identifier pattern strings
    """
    patterns: List[str] = []

    # Pattern: IDENTIFIER: [a-zA-Z_][a-zA-Z0-9_]*;
    identifier_pattern = r"IDENTIFIER\s*:\s*\[([^\]]+)\]\s*([^\s;]+)\s*;"
    for match in re.finditer(identifier_pattern, lexer_content):
        char_class = match.group(1)
        rest = match.group(2)
        patterns.append(f"[{char_class}]{rest}")

    # Also look for quoted identifier patterns
    quoted_pattern = r"QUOTED_IDENTIFIER\s*:\s*([^\s;]+)\s*;"
    for match in re.finditer(quoted_pattern, lexer_content):
        patterns.append(match.group(1))

    return patterns


def extract_statement_patterns(parser_content: str) -> Dict[str, str]:
    """Extract statement patterns from parser file.

    Statements are typically defined as parser rules like:
    createTableStatement: CREATE TABLE ...

    Args:
        parser_content: Content of parser .g4 file

    Returns:
        Dict mapping statement type names to their patterns
    """
    statements: Dict[str, str] = {}

    # Pattern: statementName: rule_body;
    statement_pattern = r"(\w+)\s*:\s*([^;]+);"
    for match in re.finditer(statement_pattern, parser_content):
        stmt_name = match.group(1)
        stmt_body = match.group(2).strip()

        # Only include if it looks like a statement definition
        if any(keyword in stmt_name.lower() for keyword in ["statement", "clause", "definition"]):
            statements[stmt_name] = stmt_body

    return statements


def analyze_grammar_file(grammar_path: Path) -> Dict[str, Any]:
    """Analyze a single ANTLR grammar file.

    Args:
        grammar_path: Path to .g4 file

    Returns:
        Dict with extracted information
    """
    try:
        content = grammar_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading {grammar_path}: {e}", file=sys.stderr)
        return {}

    is_lexer = "lexer grammar" in content or "LEXER" in grammar_path.name.upper()
    is_parser = "parser grammar" in content or "PARSER" in grammar_path.name.upper()

    result = {
        "file": str(grammar_path),
        "is_lexer": is_lexer,
        "is_parser": is_parser,
    }

    if is_lexer:
        result["keywords"] = sorted(extract_keywords(content))
        result["operators"] = extract_operators(content)
        result["identifier_patterns"] = extract_identifier_patterns(content)

    if is_parser:
        result["statements"] = extract_statement_patterns(content)

    return result


def generate_regex_keyword_pattern(keywords: Set[str]) -> str:
    """Generate a regex pattern that matches any of the keywords.

    Args:
        keywords: Set of keyword strings

    Returns:
        Regex pattern string
    """
    if not keywords:
        return ""

    # Sort by length (longest first) to match longest keywords first
    sorted_keywords = sorted(keywords, key=len, reverse=True)

    # Escape special regex characters
    escaped = [re.escape(kw) for kw in sorted_keywords]

    # Create alternation pattern
    pattern = "|".join(escaped)

    return f"\\b({pattern})\\b"


def generate_python_keyword_list(keywords: Set[str]) -> str:
    """Generate Python list of keywords.

    Args:
        keywords: Set of keyword strings

    Returns:
        Python code string
    """
    sorted_keywords = sorted(keywords)
    return "[\n    " + ",\n    ".join(f'"{kw}"' for kw in sorted_keywords) + "\n]"


def main():
    """Main function to extract patterns from grammar files."""
    if len(sys.argv) < 2:
        print("Usage: extract_grammar_patterns.py <grammar_file_or_dir> [output_file]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    grammar_files: List[Path] = []

    if input_path.is_file():
        grammar_files = [input_path]
    elif input_path.is_dir():
        grammar_files = list(input_path.glob("*.g4"))
    else:
        print(f"Error: {input_path} is not a file or directory", file=sys.stderr)
        sys.exit(1)

    if not grammar_files:
        print(f"No .g4 files found in {input_path}", file=sys.stderr)
        sys.exit(1)

    results = []
    all_keywords: Set[str] = set()
    all_operators: Dict[str, str] = {}

    for grammar_file in grammar_files:
        print(f"Analyzing {grammar_file}...", file=sys.stderr)
        result = analyze_grammar_file(grammar_file)
        results.append(result)

        if "keywords" in result:
            all_keywords.update(result["keywords"])
        if "operators" in result:
            all_operators.update(result["operators"])

    # Generate output
    output_lines = [
        "# Extracted patterns from ANTLR grammar files",
        "# Generated by extract_grammar_patterns.py",
        "",
        f"# Total keywords found: {len(all_keywords)}",
        f"# Total operators found: {len(all_operators)}",
        "",
    ]

    # Generate keyword regex pattern
    if all_keywords:
        output_lines.extend(
            [
                "# Keyword regex pattern (for use in regex parsers)",
                "# This pattern matches any of the extracted keywords",
                f'KEYWORD_PATTERN = r"{generate_regex_keyword_pattern(all_keywords)}"',
                "",
                "# Python list of keywords",
                "KEYWORDS = " + generate_python_keyword_list(all_keywords),
                "",
            ]
        )

    # Generate operator info
    if all_operators:
        output_lines.extend(
            [
                "# Operators",
                "OPERATORS = {",
            ]
        )
        for op_name, op_symbol in sorted(all_operators.items()):
            output_lines.append(f'    "{op_name}": "{op_symbol}",')
        output_lines.append("}")
        output_lines.append("")

    # Detailed results per file
    output_lines.append("# Detailed results per file:")
    output_lines.append("")
    for result in results:
        output_lines.append(f"# File: {result['file']}")
        if result.get("keywords"):
            output_lines.append(f"# Keywords: {len(result['keywords'])}")
        if result.get("operators"):
            output_lines.append(f"# Operators: {len(result['operators'])}")
        output_lines.append("")

    output_text = "\n".join(output_lines)

    if output_file:
        Path(output_file).write_text(output_text, encoding="utf-8")
        print(f"Output written to {output_file}", file=sys.stderr)
    else:
        print(output_text)

    print(
        f"\nExtracted {len(all_keywords)} keywords and {len(all_operators)} operators",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()

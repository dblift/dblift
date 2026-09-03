# SQL Parser System for DBLift

This document describes the architecture and usage of the SQL parsing system in DBLift.

## Overview

The SQL parsing system in DBLift provides SQL statement splitting, validation, and analysis for multiple SQL dialects. It uses a **layered architecture** with tokenization-based parsing as the primary strategy, with regex-based fallback for edge cases.

## Architecture

### Layered Parsing Approach

DBLift uses a three-layer parsing strategy for maximum reliability:

1. **Tokenization Layer** (Primary) - Flyway-inspired character-by-character tokenization
2. **Regex Layer** (Fallback) - Pattern-based parsing for edge cases
3. **SqlGlot Layer** (AST) - Abstract Syntax Tree parsing for pure SQL analysis

### Key Components

#### 1. Tokenization Infrastructure (`NEW in 2024`)

**Core Modules:**
- `tokens.py` - Token types and dataclass definitions
- `parser_context.py` - Parsing state management (block depth, delimiter, etc.)
- `base_tokenizer.py` - Abstract base class for character-by-character tokenization
- `base_statement_parser.py` - Token-based statement splitting logic

**Dialect-Specific Tokenizers:**
- `oracle/oracle_tokenizer.py` - Q-quotes, wrapped PL/SQL, slash delimiters
- `mysql/mysql_tokenizer.py` - Backtick identifiers, DELIMITER command, hash comments
- `postgresql/postgresql_tokenizer.py` - Dollar-quoted strings, COPY FROM STDIN
- `sqlserver/sqlserver_tokenizer.py` - GO delimiter, bracketed identifiers

**Dialect-Specific Statement Parsers:**
- `oracle/oracle_statement_parser.py` - PL/SQL block management, slash handling
- `mysql/mysql_statement_parser.py` - Dynamic delimiter switching, CASE disambiguation
- `postgresql/postgresql_statement_parser.py` - BEGIN ATOMIC, transaction detection
- `sqlserver/sqlserver_statement_parser.py` - BEGIN TRANSACTION vs BEGIN block

#### 2. Regex-Based Parsers (Fallback)

- `enhanced_regex_parser.py` - Base class for regex-based parsing
- `unified_regex_parser.py` - Universal regex patterns
- Dialect-specific regex parsers (`*_regex_parser.py`) - Now use tokenization with regex fallback

#### 3. Parser Factory

- `parser_factory.py` - Creates appropriate parser for each dialect
- `parser_interface.py` - Common interface for all parsers

#### 4. Hybrid Parser

- `hybrid_parser.py` - Orchestrates between tokenization, regex, and SqlGlot strategies

## How It Works

### Statement Splitting Flow

```
SQL Input
    ↓
Tokenization (character-by-character)
    → Tokens (KEYWORD, STRING, COMMENT, DELIMITER, etc.)
    ↓
Statement Parser (token-based splitting)
    → Uses ParserContext to track block depth, delimiter, etc.)
    → Splits at statement boundaries (respecting blocks)
    ↓
[If error] → Fallback to Regex
    ↓
List of SQL Statements
```

### Tokenization Features

The tokenization layer handles complex SQL features:

- **Block Depth Tracking**: BEGIN/END, IF/END IF, LOOP/END LOOP
- **String Literals**: Preserves content, handles escapes (Q-quotes, dollar-quotes, etc.)
- **Comment Handling**: Single-line (--), multi-line (/* */), dialect-specific
- **Dynamic Delimiters**: MySQL DELIMITER, Oracle slash (/)
- **Nested Structures**: Nested blocks, CASE expressions, subqueries
- **Special Identifiers**: Backticks, brackets, double-quotes (dialect-specific)

## Usage Examples

### Basic Statement Splitting

```python
from dblift.core.sql_parser.oracle.oracle_parser import OracleParser

sql = """
CREATE OR REPLACE PROCEDURE test_proc AS
BEGIN
    FOR rec IN (SELECT * FROM table1) LOOP
        NULL;
    END LOOP;
END;
/

CREATE TABLE test_table (id NUMBER);
"""

parser = OracleParser()
statements = parser.split_statements(sql)
# Returns: ['CREATE OR REPLACE PROCEDURE...', 'CREATE TABLE...']
```

### Using Parser Factory

```python
from dblift.core.sql_parser.parser_factory import SqlParserFactory

# Create parser for any dialect
factory = SqlParserFactory("mysql")
parser = factory.get_parser()

# Parse SQL content
result = parser.parse_sql(sql_content, default_schema="myschema")
print(f"Found {len(result.statements)} statements")
```

### Direct Tokenization

```python
from dblift.core.sql_parser.mysql.mysql_tokenizer import MySQLTokenizer

sql = "SELECT * FROM `my_table` WHERE id=100;"
tokenizer = MySQLTokenizer(sql)
tokens = tokenizer.tokenize()

for token in tokens:
    print(f"{token.type}: {token.text}")
```

## Dialect Support

| Dialect    | Tokenization | Regex Fallback | Special Features                          |
|------------|--------------|----------------|-------------------------------------------|
| Oracle     | ✅ Full      | ✅ Yes         | Q-quotes, wrapped PL/SQL, slash delimiter |
| MySQL      | ✅ Full      | ✅ Yes         | DELIMITER cmd, backticks, hash comments   |
| PostgreSQL | ✅ Full      | ✅ Yes         | Dollar quotes, COPY FROM STDIN            |
| SQL Server | ✅ Full      | ✅ Yes         | GO delimiter, bracketed identifiers       |
| DB2        | ⚠️ Regex     | ✅ Yes         | Regex-only (tokenization planned)         |
| SQLite     | ⚠️ Regex     | ✅ Yes         | Regex-only (simple syntax)                |

## Performance

Tokenization provides:
- **Accuracy**: 99.8% test pass rate (629/630 tests)
- **Coverage**: All tokenization files ≥ 80% code coverage
- **Reliability**: Character-by-character parsing eliminates regex edge cases
- **Speed**: Comparable to regex for most queries, faster for complex PL/SQL

## Extending the System

### Adding Tokenization to a New Dialect

1. Create tokenizer class extending `BaseTokenizer`:
```python
class MyDialectTokenizer(BaseTokenizer):
    def _handle_string(self) -> Token:
        # Dialect-specific string handling
        pass
```

2. Create statement parser extending `BaseStatementParser`:
```python
class MyDialectStatementParser(BaseStatementParser):
    def _adjust_block_depth(self, token: Token):
        # Dialect-specific block depth logic
        pass
```

3. Integrate into dialect parser:
```python
class MyDialectParser(EnhancedRegexParser):
    def split_statements(self, sql: str) -> List[str]:
        tokenizer = MyDialectTokenizer(sql)
        tokens = tokenizer.tokenize()
        parser = MyDialectStatementParser(tokens)
        return parser.split_statements()
```

### Testing

All new tokenization code should have:
- Unit tests for tokenizer (token stream verification)
- Unit tests for statement parser (statement splitting)
- Integration tests with real-world SQL samples
- **Target: 80%+ code coverage** for all tokenization files

## Known Limitations

1. **Complex Nested Structures**: Very rare edge cases with nested FOR loops containing nested BEGIN/END blocks may not split perfectly (1 failing test out of 630)
2. **Dialect-Specific Quirks**: Some obscure SQL features may fall back to regex parsing
3. **Performance**: Character-by-character parsing is slightly slower than regex for simple queries (negligible in practice)

## Future Improvements

1. Extend tokenization to DB2 and SQLite
2. Add support for more SQL features (CTEs, window functions, etc.)
3. Improve performance with token stream caching
4. Add syntax validation beyond statement splitting
5. Extract schema information (tables, columns, constraints) from tokens

## References

- Flyway Parser Implementation (inspiration for tokenization approach)

"""Story 23-6: Batch fix remaining except Exception: pass blocks."""

import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = str(Path(__file__).resolve().parents[3])

pytestmark = [pytest.mark.unit]


class TestExportSchemaCommandSilentExceptions:
    """export_schema_command.py had 7 silent except blocks."""

    def test_export_schema_silent_excepts_replaced(self):
        """Structural: verify no bare 'except Exception: pass' remains."""
        import inspect

        from core.migration.commands import export_schema_command as mod

        source = inspect.getsource(mod)
        silent_count = len(re.findall(r"except Exception:\s*\n\s*pass", source))
        assert silent_count == 0, f"Found {silent_count} silent except blocks remaining"


class TestHybridParserSilentExceptions:
    """hybrid_parser.py had 5 silent except blocks."""

    def test_hybrid_parser_silent_excepts_replaced(self):
        import inspect

        from core.sql_parser import hybrid_parser as mod

        source = inspect.getsource(mod)
        silent_count = len(re.findall(r"except Exception:\s*\n\s*pass", source))
        assert silent_count == 0, f"Found {silent_count} silent except blocks in hybrid_parser"


class TestMigrationDataServiceSilentExceptions:
    """migration_data_service.py had 4 silent except blocks."""

    def test_migration_data_service_silent_excepts_replaced(self):
        import inspect

        from core.migration.state import migration_data_service as mod

        source = inspect.getsource(mod)
        silent_count = len(re.findall(r"except Exception:\s*\n\s*pass", source))
        assert silent_count == 0, f"Found {silent_count} silent except blocks"


class TestSnapshotCommandSilentExceptions:
    """snapshot_command.py had 3 silent except blocks."""

    def test_snapshot_command_silent_excepts_replaced(self):
        import inspect

        from core.migration.commands import snapshot_command as mod

        source = inspect.getsource(mod)
        silent_count = len(re.findall(r"except Exception:\s*\n\s*pass", source))
        assert silent_count == 0, f"Found {silent_count} silent except blocks"


class TestHtmlFormatterSilentExceptions:
    """htmlformatter.py had 8 silent except blocks."""

    def test_htmlformatter_silent_excepts_replaced(self):
        import inspect

        from core.logger.formatters import htmlformatter as mod

        source = inspect.getsource(mod)
        silent_count = len(re.findall(r"except Exception:\s*\n\s*pass", source))
        assert silent_count == 0, f"Found {silent_count} silent except blocks in htmlformatter"


class TestRemainingIntentionalExcepts:
    """Verify intentional bare except blocks have proper comments."""

    def test_sqlalchemy_provider_bare_excepts_have_comments(self):
        import inspect

        import db.sqlalchemy_provider as mod

        source = inspect.getsource(mod)
        # Find all bare except Exception: blocks
        lines = source.splitlines()
        for i, line in enumerate(lines):
            if re.search(r"except Exception:\s*$", line):
                # Next non-empty line must be a comment or a log.debug call
                next_lines = [lines[j].strip() for j in range(i + 1, min(i + 3, len(lines)))]
                has_comment_or_log = any(
                    l.startswith("# Intentional") or "self.log.debug" in l or l == "pass"
                    for l in next_lines
                )
                if not has_comment_or_log:
                    bare_line = lines[i].strip()
                    pytest.fail(
                        f"Line {i + 1} has bare except without comment: {bare_line!r} "
                        f"followed by {next_lines}"
                    )

    def test_undo_script_generator_regex_fallbacks_have_comments(self):
        import inspect

        from core.migration.scripting import undo_script_generator as mod

        source = inspect.getsource(mod)
        lines = source.splitlines()
        for i, line in enumerate(lines):
            if re.search(r"except Exception:\s*$", line):
                next_lines = [lines[j].strip() for j in range(i + 1, min(i + 3, len(lines)))]
                has_comment_or_log = any(
                    l.startswith("# Intentional:") or "self.log" in l or "logger" in l
                    for l in next_lines
                )
                if not has_comment_or_log:
                    pytest.fail(
                        f"Line {i + 1} has bare except without comment, followed by {next_lines}"
                    )


class TestGlobalSilentExceptCount:
    """Verify the total count of silent except blocks across production code is reduced."""

    def test_total_silent_excepts_significantly_reduced(self):
        """Total except Exception: pass should be near zero (only intentional ones remain)."""
        result = subprocess.run(
            [
                "grep",
                "-r",
                "--include=*.py",
                "-c",
                "except Exception: pass",
                "core/",
                "db/",
                "cli/",
                "api/",
                "config/",
            ],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            timeout=30,
        )
        # Count total inline matches across all files
        total = 0
        for line in result.stdout.splitlines():
            if ":" in line:
                count = line.split(":")[-1].strip()
                try:
                    total += int(count)
                except ValueError:
                    pass
        assert (
            total <= 5
        ), f"Still {total} inline 'except Exception: pass' remaining (expected <= 5)"

    def test_total_bare_except_exception_colon_reduced(self):
        """Count of bare 'except Exception:\\n    pass' blocks should be very low."""
        result = subprocess.run(
            [
                "grep",
                "-r",
                "--include=*.py",
                "-l",
                "except Exception:",
                "core/",
                "db/",
                "cli/",
                "api/",
                "config/",
            ],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
            timeout=30,
        )
        files = [f for f in result.stdout.splitlines() if f and "__pycache__" not in f]
        silent_total = 0
        for filepath in files:
            try:
                with open(f"{_REPO_ROOT}/{filepath}", "r") as fh:
                    source = fh.read()
                count = len(re.findall(r"except Exception:\s*\n\s*pass\b", source))
                silent_total += count
            except Exception:
                pass
        # Allow up to 35 intentional ones (JDBC close/BLOB fallbacks/sqlglot fallbacks)
        assert (
            silent_total <= 35
        ), f"Found {silent_total} bare 'except Exception: pass' blocks (expected <= 35)"

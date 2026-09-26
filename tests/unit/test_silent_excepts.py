"""Silent ``except Exception: pass`` blocks stay out of the modules that once had them."""

import re

import pytest

pytestmark = [pytest.mark.unit]


class TestHybridParserSilentExceptions:
    """hybrid_parser.py had 5 silent except blocks."""

    def test_hybrid_parser_silent_excepts_replaced(self):
        import inspect

        from dblift.core.sql_parser import hybrid_parser as mod

        source = inspect.getsource(mod)
        silent_count = len(re.findall(r"except Exception:\s*\n\s*pass", source))
        assert silent_count == 0, f"Found {silent_count} silent except blocks in hybrid_parser"


class TestMigrationDataServiceSilentExceptions:
    """migration_data_service.py had 4 silent except blocks."""

    def test_migration_data_service_silent_excepts_replaced(self):
        import inspect

        from dblift.core.migration.state import migration_data_service as mod

        source = inspect.getsource(mod)
        silent_count = len(re.findall(r"except Exception:\s*\n\s*pass", source))
        assert silent_count == 0, f"Found {silent_count} silent except blocks"


class TestHtmlFormatterSilentExceptions:
    """htmlformatter.py had 8 silent except blocks."""

    def test_htmlformatter_silent_excepts_replaced(self):
        import inspect

        from dblift.core.logger.formatters import htmlformatter as mod

        source = inspect.getsource(mod)
        silent_count = len(re.findall(r"except Exception:\s*\n\s*pass", source))
        assert silent_count == 0, f"Found {silent_count} silent except blocks in htmlformatter"


class TestRemainingIntentionalExcepts:
    """Verify intentional bare except blocks have proper comments."""

    def test_sqlalchemy_provider_bare_excepts_have_comments(self):
        import inspect

        import dblift.db.sqlalchemy_provider as mod

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

        from dblift.core.migration.scripting import undo_script_generator as mod

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

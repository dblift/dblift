"""Tests vérifiant que les handlers de cleanup loggent au lieu d'avaler les exceptions."""

import inspect

import pytest

from core.validation.round_trip_tester import RoundTripTester


@pytest.mark.unit
class TestRoundTripTesterCleanupLogging:
    """Vérifie que les except Exception: pass sont remplacés par des logs debug."""

    def test_no_silent_pass_in_round_trip_tester(self):
        """Vérifie structurellement qu'il n'y a plus de 'except Exception: pass' bare."""
        source = inspect.getsource(RoundTripTester)
        lines = source.splitlines()

        silent_passes = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "except Exception:" or stripped == "except Exception :":
                # Check next non-empty line
                for j in range(i + 1, min(i + 4, len(lines))):
                    next_stripped = lines[j].strip()
                    if next_stripped.startswith("#"):
                        continue  # skip comment lines
                    if next_stripped == "pass":
                        silent_passes.append(f"Line ~{i + 1}: '{line.strip()}' followed by 'pass'")
                    break

        assert silent_passes == [], (
            f"Found {len(silent_passes)} silent 'except Exception: pass' — "
            f"replace with logger.debug:\n" + "\n".join(silent_passes)
        )

    def test_except_exception_handlers_have_logging_or_action(self):
        """Vérifie que chaque 'except Exception' a soit un logger.debug, soit une action réelle."""
        source = inspect.getsource(RoundTripTester)
        lines = source.splitlines()

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("except Exception"):
                # Gather the body of the except block (next 1-5 non-comment lines)
                body_lines = []
                for j in range(i + 1, min(i + 6, len(lines))):
                    next_stripped = lines[j].strip()
                    if next_stripped.startswith("#"):
                        continue
                    if next_stripped == "":
                        break
                    # Stop if we hit a new except/else/finally/try or dedented code
                    body_lines.append(next_stripped)
                    if len(body_lines) >= 3:
                        break

                body = " ".join(body_lines)
                # Should have either: logger call, variable assignment, or a real action (try block, if, etc.)
                has_action = (
                    "logger." in body
                    or "=" in body
                    or body.startswith("try")
                    or body.startswith("if")
                    or "(" in body  # method calls: rollback(), commit(), etc.
                )
                assert (
                    has_action
                ), f"Line {i + 1}: 'except Exception' handler has no logging or action: {body}"

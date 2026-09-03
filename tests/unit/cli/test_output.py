"""Tests for the ``CommandOutput`` routing abstraction.

Covers:
  * the ``is_machine_format`` predicate for every format in
    ``MACHINE_READABLE_FORMATS`` plus human defaults;
  * ``machine()`` payload serialisation (dict, list, pre-rendered
    string) and no-op in human mode;
  * ``status()`` / ``banner()`` routing to the correct stream
    depending on mode;
  * the ``from_args`` convenience constructor.
"""

from __future__ import annotations

import io
from argparse import Namespace

import pytest

from dblift.cli._constants import MACHINE_READABLE_FORMATS
from dblift.cli._output import CommandOutput, from_args


def _streams() -> tuple[io.StringIO, io.StringIO, CommandOutput]:
    """Return (stdout_buf, stderr_buf, output) for a machine-format run."""
    out = io.StringIO()
    err = io.StringIO()
    return out, err, CommandOutput("json", stdout=out, stderr=err)


# --- is_machine_format ------------------------------------------------------


class TestIsMachineFormat:
    @pytest.mark.parametrize("fmt", sorted(MACHINE_READABLE_FORMATS))
    def test_every_machine_format_reports_true(self, fmt):
        out = CommandOutput(fmt)
        assert out.is_machine_format is True

    @pytest.mark.parametrize("fmt", ["table", "console", "text", "html"])
    def test_human_formats_report_false(self, fmt):
        out = CommandOutput(fmt)
        assert out.is_machine_format is False

    def test_none_is_treated_as_human(self):
        out = CommandOutput(None)
        assert out.is_machine_format is False

    def test_unknown_format_is_treated_as_human(self):
        out = CommandOutput("weird")
        assert out.is_machine_format is False


# --- machine() --------------------------------------------------------------


class TestMachinePayload:
    def test_dict_is_json_serialised_to_stdout(self):
        out, err, output = _streams()
        output.machine({"a": 1, "b": [2, 3]})
        assert err.getvalue() == ""
        # Parseable as JSON and round-trips to the exact payload
        import json as _json

        assert _json.loads(out.getvalue()) == {"a": 1, "b": [2, 3]}

    def test_list_is_json_serialised_to_stdout(self):
        out, err, output = _streams()
        output.machine([{"x": 1}, {"y": 2}])
        import json as _json

        assert _json.loads(out.getvalue()) == [{"x": 1}, {"y": 2}]

    def test_pre_rendered_string_is_written_verbatim(self):
        # SARIF / github-actions formatters produce a pre-rendered string;
        # CommandOutput must not wrap or re-serialise them.
        out, err, output = _streams()
        output.machine("<?xml version='1.0'?>\n<sarif/>\n")
        assert out.getvalue() == "<?xml version='1.0'?>\n<sarif/>\n\n"

    def test_machine_is_noop_in_human_format(self):
        out = io.StringIO()
        err = io.StringIO()
        output = CommandOutput("console", stdout=out, stderr=err)
        output.machine({"should": "not appear"})
        assert out.getvalue() == ""
        assert err.getvalue() == ""


# --- status() / banner() ----------------------------------------------------


class TestStatusAndBanner:
    def test_status_goes_to_stderr_in_machine_mode(self):
        out, err, output = _streams()
        output.status("migrating...")
        assert "migrating..." in err.getvalue()
        assert out.getvalue() == ""  # stdout must stay clean

    def test_status_goes_to_stdout_in_human_mode(self):
        out = io.StringIO()
        err = io.StringIO()
        output = CommandOutput("console", stdout=out, stderr=err)
        output.status("migrating...")
        assert "migrating..." in out.getvalue()
        assert err.getvalue() == ""

    def test_banner_goes_to_stderr_in_machine_mode(self):
        out, err, output = _streams()
        output.banner("=== DBLIFT ===")
        assert "=== DBLIFT ===" in err.getvalue()
        assert out.getvalue() == ""

    def test_banner_goes_to_stdout_in_human_mode(self):
        out = io.StringIO()
        err = io.StringIO()
        output = CommandOutput("table", stdout=out, stderr=err)
        output.banner("=== DBLIFT ===")
        assert "=== DBLIFT ===" in out.getvalue()
        assert err.getvalue() == ""

    def test_banner_uses_primary_format_for_comma_separated_machine_output(self):
        out = io.StringIO()
        err = io.StringIO()
        output = from_args(Namespace(format="json,html"), stdout=out, stderr=err)

        output.banner("=== DBLIFT ===")

        assert out.getvalue() == ""
        assert "=== DBLIFT ===" in err.getvalue()

    def test_status_then_machine_payload_is_parseable(self):
        # Machine mode contract: stdout remains pure JSON even when
        # status was called before / after the machine payload.
        out, err, output = _streams()
        output.status("starting...")
        output.machine({"ok": True})
        output.status("done")
        import json as _json

        # Stdout is nothing but the JSON document.
        assert _json.loads(out.getvalue()) == {"ok": True}
        # Stderr has both status lines in order.
        lines = err.getvalue().splitlines()
        assert "starting..." in lines[0]
        assert "done" in lines[-1]


# --- error -----------------------------------------------------------------


class TestError:
    def test_error_goes_to_stderr_in_machine_mode(self):
        out, err, output = _streams()
        output.error("boom")
        assert "boom" in err.getvalue()
        assert out.getvalue() == ""

    def test_error_goes_to_stderr_in_human_mode(self):
        out = io.StringIO()
        err = io.StringIO()
        output = CommandOutput("table", stdout=out, stderr=err)
        output.error("boom")
        # Human mode does NOT route errors to stdout — stderr is the
        # contract regardless of mode.
        assert "boom" in err.getvalue()
        assert out.getvalue() == ""

    def test_error_does_not_corrupt_machine_stdout(self):
        out, err, output = _streams()
        output.error("warning before payload")
        output.machine({"ok": True})
        output.error("warning after payload")
        import json as _json

        assert _json.loads(out.getvalue()) == {"ok": True}
        lines = err.getvalue().splitlines()
        assert lines[0] == "warning before payload"
        assert lines[-1] == "warning after payload"


# --- from_args --------------------------------------------------------------


class TestFromArgs:
    def test_extracts_format_from_namespace(self):
        ns = Namespace(format="json")
        output = from_args(ns)
        assert output.is_machine_format is True

    def test_missing_format_defaults_to_console(self):
        ns = Namespace()  # no .format at all
        output = from_args(ns)
        assert output.is_machine_format is False
        assert output.output_format == "console"

    def test_falsy_format_defaults_to_console(self):
        # getattr returns None; from_args must handle that without AttributeError
        ns = Namespace(format=None)
        output = from_args(ns)
        assert output.output_format == "console"

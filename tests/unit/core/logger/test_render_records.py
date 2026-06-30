"""Tests for the shared generic records-table helper and state palette."""

from rich.text import Text

from core.logger.console import render_records_table, state_text


def test_render_records_table_is_plain_text_with_title_and_cells():
    out = render_records_table(
        [("ID", "left"), ("Count", "right")],
        [["alpha", 1], ["beta", 22]],
        title="My Title",
    )
    assert "My Title" in out
    assert "ID" in out and "Count" in out
    assert "alpha" in out and "22" in out
    # No ANSI escape codes — safe for pipes/files.
    assert "\x1b[" not in out


def test_render_records_table_accepts_rich_text_cells():
    out = render_records_table([("State", "left")], [[state_text("failed")]])
    assert "failed" in out


def test_render_records_table_empty_rows_renders_header_only():
    out = render_records_table([("ID", "left")], [], title="Empty")
    assert "Empty" in out and "ID" in out


def test_state_text_styles_known_state():
    t = state_text("failed")
    assert isinstance(t, Text)
    assert str(t) == "failed"
    assert t.spans  # stylize applied a span


def test_state_text_unknown_state_has_no_style():
    t = state_text("totally-unknown")
    assert str(t) == "totally-unknown"
    assert not t.spans


def test_state_text_empty_string_renders_unstyled():
    t = state_text("")
    assert str(t) == ""
    assert not t.spans


def test_state_text_is_case_insensitive_preserves_casing():
    t = state_text("PENDING")
    assert t.spans  # styled despite uppercase
    assert str(t) == "PENDING"  # original casing preserved


def test_render_records_table_color_mode_returns_content():
    # In a non-tty test context, color=True still returns the plain content
    # (rich auto-strips ANSI when stdout is not a terminal).
    out = render_records_table([("ID", "left")], [["alpha"]], title="T", color=True)
    assert "alpha" in out and "T" in out
    assert "\x1b[" not in out  # captured under pytest (no tty) → no ANSI
